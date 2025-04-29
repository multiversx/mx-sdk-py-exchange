from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from typing import Any, List
import json
import config
from context import Context
from multiversx_sdk.core.transactions_factories import TransactionsFactoryConfig, SmartContractTransactionsFactory
from multiversx_sdk import Address
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from contracts.locked_asset_contract import LockedAssetContract
from contracts.dex_proxy_contract import DexProxyContract
from tools.common import get_user_continue, fetch_contracts_states, fetch_new_and_compare_contract_states
from tools.runners.common_runner import ExportedAccount, ExportedToken, add_generate_transaction_command, add_upgrade_command, add_verify_command,\
      fund_shadowfork_accounts, get_acounts_with_token, get_default_signature, read_accounts_from_json,\
        sync_account_nonce, verify_contracts, write_accounts_to_json

from utils.utils_tx import ESDTToken, NetworkProviders, prepare_contract_call_tx
from utils.utils_generic import get_file_from_url_or_path, split_to_chunks
from utils.utils_chain import Account, WrapperAddress, get_bytecode_codehash, decode_merged_attributes, base64_to_hex, string_to_hex, dec_to_padded_hex
from utils.decoding_structures import XMEX_ATTRIBUTES, XMEXFARM_ATTRIBUTES


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for energy factory commands"""
    group_parser = subparsers.add_parser('energy-factory', help='energy factory group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='energy factory contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_energy_factory)
    add_verify_command(contract_group, verify_energy_factory)

    command_parser = contract_group.add_parser('pause', help='pause contract command')
    command_parser.set_defaults(func=pause_energy_factory)
    command_parser = contract_group.add_parser('resume', help='resume contract command')
    command_parser.set_defaults(func=resume_energy_factory)

    transactions_parser = subgroup_parser.add_parser('generate-transactions', help='energy factory transactions commands')

    transactions_group = transactions_parser.add_subparsers()
    add_generate_transaction_command(transactions_group, generate_energy_change_transactions, 'energyChange', 'generate energy change transactions command')
    add_generate_transaction_command(transactions_group, generate_unlock_tokens_transactions, 'unlockTokens', 'generate unlock tokens transactions command')

    return group_parser


def pause_energy_factory(_):
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.pause(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"pause energy contract: {energy_contract}")


def resume_energy_factory(_):
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.resume(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"resume energy contract: {energy_contract}")


def upgrade_energy_factory(args: Any):
    compare_states = args.compare_states
    context = Context()
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    energy_contract = SimpleLockEnergyContract.load_contract_by_address(energy_factory_address)
    print(f"Upgrade energy factory contract: {energy_factory_address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = get_file_from_url_or_path(config.SIMPLE_LOCK_ENERGY_BYTECODE_PATH)
    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", context.network_provider, [energy_contract.address], "energy")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = energy_contract.contract_upgrade(context.deployer_account, context.network_provider.proxy,
                                               bytecode_path,
                                               [], True)

    if not context.network_provider.check_complex_tx_status(tx_hash, f"upgrade energy contract: {energy_contract}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("energy", energy_contract.address, context.network_provider)


def verify_energy_factory(args: Any):
    print("Verifying energy contract...")

    context = Context()
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    verify_contracts(args, [energy_factory_address])
    
    print("All contracts have been verified.")


def generate_energy_change_transactions(args: Any):
    """Generate energy change transactions"""

    number_of_accounts_per_tx = 300
    tx_batches_to_send = 10

    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    # read the accounts export file
    # accounts export format:
    # {
    #     "bech32 address": "energy amount mismatch in signed integer",
    #     "bech32 address": "energy amount mismatch in signed integer",
    #     ...
    # }
    exported_accounts_path = args.accounts_export
    if not exported_accounts_path:
        print("Missing accounts export path!")
        return
    
    with open(exported_accounts_path, "r") as f:
        exported_accounts = json.load(f)
    
    # Create batches of accounts
    txs = []
    current_batch = []

    network_config = context.network_provider.proxy.get_network_config()
    def compose_tx(batch: list[Any]):
        tx = prepare_contract_call_tx(Address.new_from_bech32(energy_contract.address), 
                          context.deployer_account, 
                          network_config, 
                          200000000, 
                          "adjustUserEnergy", 
                          batch)
        context.deployer_account.nonce += 1
        return tx
    
    for address, energy_change in exported_accounts.items():
        current_batch.extend([address, int(energy_change), 0])
        
        if len(current_batch) >= number_of_accounts_per_tx:
            # compose the tx for the current batch
            tx = compose_tx(current_batch)
            txs.append(tx)
            current_batch = []
    
    # Add any remaining accounts in the last batch
    if current_batch:
        tx = compose_tx(current_batch)
        txs.append(tx)

    print(f"Created {len(txs)} transactions")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    # split the txs by batches of tx_batches_to_send
    txs_batches = split_to_chunks(txs, tx_batches_to_send)

    counter = 0
    for tx_batch in txs_batches:
        counter += len(tx_batch)
        print(f"Progress: {counter} / {len(txs)} transactions")

        # get the current nonce of the deployer account from proxy, send the txs and wait for the nonce on the account to be incremented with the number of txs sent
        current_nonce = context.network_provider.proxy.get_account(context.deployer_account.address).nonce
        expected_nonce = current_nonce + len(tx_batch)

        num_sent, hashes = context.network_provider.proxy.send_transactions(tx_batch)
        print(f"Sent {num_sent} transactions out of {len(tx_batch)}")
        print(f"Hashes: {hashes}")
        
        while current_nonce < expected_nonce:
            if "localhost" in context.network_provider.proxy.url:
                context.network_provider.proxy.do_post_generic(f"{context.network_provider.proxy.url}/simulator/generate-blocks/{10}", {})      # TODO: remove this; only for local testing
            print(f"Current nonce: {current_nonce}, waiting for nonce: {expected_nonce}")
            sleep(6)
            current_nonce = context.network_provider.proxy.get_account(context.deployer_account.address).nonce
        

def generate_unlock_tokens_transactions(args: Any):
    """Generate unlock tokens transactions"""

    ON_CHAIN_NONCES = False
    METABONDING_UNBOND_UNSTAKE = True
    # TODO: remove this
    LOCAL_RUN = False
    FETCH_ON_CHAIN_TOKEN_DATA = False
    ONCHAIN_AMOUNT_RESYNC = False

    context = Context()

    exported_accounts_path = args.accounts_export

    if not exported_accounts_path:
        print("Missing required arguments!")
        return

    network_providers = NetworkProviders(config.DEFAULT_API, config.DEFAULT_PROXY)
    network_providers.network = network_providers.proxy.get_network_config()
    chain_id = network_providers.proxy.get_network_config().chain_id
    config_tx = TransactionsFactoryConfig(chain_id=chain_id)
    signature = get_default_signature()
    default_account = Account(None, config.DEFAULT_OWNER)
    default_account.sync_nonce(network_providers.proxy)

    current_epoch = network_providers.proxy.get_network_status(1).current_epoch

    exported_accounts = read_accounts_from_json(exported_accounts_path)
    
    if LOCAL_RUN:
        # TODO: temporary accounts selector from users_with_energy_with_tokens.json
        # TODO: remove this
        filtered_addresses = {}
        with open("energy-fix/users_with_energy_no_tokens.json", "r") as f:
            raw_load = json.load(f)
        for entry in raw_load:
            if entry['total_locked_tokens'] > 0:
                filtered_addresses[entry["address"]] = entry["tokens"]

        exported_accounts = [
            account for account in exported_accounts
            if account.address in filtered_addresses
        ]

        if FETCH_ON_CHAIN_TOKEN_DATA:
            # TODO: fetch on-chain token data
            def fetch_on_chain_token_data(account: ExportedAccount):
                tokens = network_providers.proxy.get_non_fungible_tokens_of_account(Address.new_from_bech32(account.address))
                new_exported_tokens = []
                for token in tokens:
                    exported_account_token = ExportedToken(token.collection, dec_to_padded_hex(token.nonce), token.balance, token.attributes)
                    new_exported_tokens.append(exported_account_token)
                account.account_tokens_supply = new_exported_tokens
                return account
            
            new_exported_accounts = []
            length = len(exported_accounts)
            with ThreadPoolExecutor(max_workers=100) as executor:
                for i, account in enumerate(executor.map(fetch_on_chain_token_data, exported_accounts)):
                    new_exported_accounts.append(account)
                    print(f"Fetched onchain tokens for {i + 1} / {length} accounts", end="\r")
            exported_accounts = new_exported_accounts
        
        print(f"Filtered down to {len(exported_accounts)} accounts")
        input("Press Enter to continue...")

    fund_shadowfork_accounts(exported_accounts)
    sleep(35)
    input("Funded accounts, press Enter to continue...")

    # # used only when wanting to sync on-chain, but it takes an eternity
    if ON_CHAIN_NONCES:
        with ThreadPoolExecutor(max_workers=100) as executor:
            exported_accounts = list(executor.map(sync_account_nonce, exported_accounts))

    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]
    locked_token_factory_contract: LockedAssetContract = context.get_contracts(config.LOCKED_ASSETS)[0]
    proxy_v2_contract: DexProxyContract = context.get_contracts(config.PROXIES_V2)[0]
    proxy_v1_contract: DexProxyContract = context.get_contracts(config.PROXIES)[0]

    searched_tokens_map = {
        energy_contract.locked_token: {
            "contract_address": energy_contract.address,
            "unlocking_function": "unlockTokens",
            "args": [],
            "gas_limit": 80000000
        },
        locked_token_factory_contract.locked_asset: {
            "contract_address": locked_token_factory_contract.address,
            "unlocking_function": "unlockAssets",
            "args": [],
            "gas_limit": 50000000
        },
        proxy_v2_contract.proxy_lp_token: {
            "contract_address": proxy_v2_contract.address,
            "unlocking_function": "removeLiquidityProxy",
            "args": [Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqa0fsfshnff4n76jhcye6k7uvd7qacsq42jpsp6shh2"), 1, 1],
            "gas_limit": 50000000
        },
        proxy_v2_contract.proxy_farm_token: {
            "contract_address": proxy_v2_contract.address,
            "unlocking_function": "exitFarmProxy",
            "args": [Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqapxdp9gjxtg60mjwhle3n6h88zch9e7kkp2s8aqhkg")],
            "gas_limit": 50000000
        },
        proxy_v1_contract.proxy_farm_token: {
            "contract_address": proxy_v1_contract.address,
            "unlocking_function": "exitFarmProxy",
            "args": [Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqe9v45fnpkv053fj0tk7wvnkred9pms892jps9lkqrn")],
            "gas_limit": 50000000
        },
        proxy_v1_contract.proxy_lp_token: {
            "contract_address": proxy_v1_contract.address,
            "unlocking_function": "removeLiquidityProxy",
            "args": [Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqa0fsfshnff4n76jhcye6k7uvd7qacsq42jpsp6shh2"), 1, 1],
            "gas_limit": 50000000
        },
        "MEXFARM-e7af52": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqv4ks4nzn2cw96mm06lt7s2l3xfrsznmp2jpsszdry5",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "MEXFARM-5d1dbb": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqe9v45fnpkv053fj0tk7wvnkred9pms892jps9lkqrn",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "EGLDMEXF-5bcc57": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqye633y7k0zd7nedfnp3m48h24qygm5jl2jpslxallh",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "EGLDMEXF-a4d81e": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqnqvjnn4haygsw2hls2k9zjjadnjf9w7g2jpsmc60a4",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "MEXRIDEF-bf0320": {
            "contract_address": "erd1qqqqqqqqqqqqqpgq5e2m9df5yxxkmr86rusejc979arzayjk2jpsz2q43s",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "EGLDMEXFL-ef2065": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqyawg3d9r4l27zue7e9sz7djf7p9aj3sz2jpsm070jf",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "EGLDUSDCFL-f0031c": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqwtzqckt793q8ggufxxlsv3za336674qq2jpszzgqra",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "MEXFARML-28d646": {
            "contract_address": "erd1qqqqqqqqqqqqqpgq7qhsw8kffad85jtt79t9ym0a4ycvan9a2jps0zkpen",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "EGLDRIDEFL-74b819": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqs2mmvzpu6wz83z3vthajl4ncpwz67ctu2jpsrcl0ct",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "ITHWEGLDFL-332f38": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqdt892e0aflgm0xwryhhegsjhw0zru60m2jps959w5z",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "UTKWEGLDFL-082aec": {
            "contract_address": "erd1qqqqqqqqqqqqqpgq3f8jfeg34ujzy0muhe9dvn5yngwgud022jpsscjxgl",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "CRTWEGLDFL-e0454e": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqcejzfjfmmgvq7yjch2tqnhhsngr7hqyw2jpshce5u2",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "ASHWEGLDFL-cf0194": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqlu6vrtkgfjh68nycf5sdw4nyzudncns42jpsr7szch",
            "unlocking_function": "exitFarm",
            "args": [],
            "gas_limit": 30000000
        },
        "LKFARM-321c30": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqs0jjyjmx0cvek4p8yj923q5yreshtpa62jpsz6vt84",
            "unlocking_function": "exitFarmLockedToken",
            "args": [],
            "gas_limit": 7000000
        },
        "LKFARM-9620e7": {
            "contract_address": "erd1qqqqqqqqqqqqqpgqawujux7w60sjhm8xdx3n0ed8v9h7kpqu2jpsecw6ek",
            "unlocking_function": "exitFarmLockedToken",
            "args": [],
            "gas_limit": 7000000
        },
        "METARIDELK-bd8cda": {
            "contract_address": "erd1qqqqqqqqqqqqqpgq389gc8qnqy0ksha948jf72c9cks9g3rf2jpsl5z0aa",
            "unlocking_function": "unstakeFarmTokens",
            "args": [1, 1],
            "gas_limit": 70000000
        }
    }

    accounts_with_token: List[ExportedAccount] = []
    for token_name in searched_tokens_map:
        accounts_for_current_token = get_acounts_with_token(exported_accounts, token_name)
        print(f"Found {len(accounts_for_current_token)} accounts with token {token_name}")

        new_accounts = [acc for acc in accounts_for_current_token if acc.address not in [existing.address for existing in accounts_with_token]]
        accounts_with_token.extend(new_accounts)
    print(f"Total accounts with searched tokens: {len(accounts_with_token)}")

    transactions = []
    accounts_index = 1
    for account_with_token in accounts_with_token:
        print(f"Processing account {accounts_index} / {len(accounts_with_token)}")

        account = Account(pem_file=config.DEFAULT_OWNER)
        account.address = WrapperAddress.from_bech32(account_with_token.address)
        account.nonce = account_with_token.nonce

        tokens = [
            token for token in account_with_token.account_tokens_supply
            if token.token_name in searched_tokens_map
        ]

        print(f"Found {len(tokens)} tokens to unstake for account {account_with_token.address}")

        for token in tokens:

            receiver_address = searched_tokens_map[token.token_name]["contract_address"]
            function_name = searched_tokens_map[token.token_name]["unlocking_function"]
            gas_limit = searched_tokens_map[token.token_name]["gas_limit"]
            args = searched_tokens_map[token.token_name]["args"]

            # for energy contract, we need to check if the token is already unlockable to use another function
            if token.token_name == energy_contract.locked_token:
                decoded_attributes = decode_merged_attributes(base64_to_hex(token.attributes), XMEX_ATTRIBUTES)
                if int(decoded_attributes.get("unlock_epoch")) < current_epoch:
                    function_name = "unlockTokens"
                else:
                    function_name = "unlockEarly"
            # proxy farm tokens need to be unlocked using the according address for the underlying farm token
            elif token.token_name == proxy_v1_contract.proxy_farm_token:
                decoded_attributes = decode_merged_attributes(base64_to_hex(token.attributes), XMEXFARM_ATTRIBUTES)
                if decoded_attributes.get("farm_token_id") in searched_tokens_map:
                    destination_farm_address = searched_tokens_map[decoded_attributes.get("farm_token_id")]["contract_address"]
                    args = [Address.new_from_bech32(destination_farm_address)]

            esdt_token = ESDTToken(token.token_name, int(token.token_nonce_hex, 16), int(token.supply))
            
            if ONCHAIN_AMOUNT_RESYNC:
                # TODO: temporary skip if the token is no longer owned by the account (already unlocked since the last snapshot)
                if esdt_token.get_full_token_name() not in filtered_addresses[account_with_token.address]:
                    continue
                on_chain_amount = network_providers.proxy.get_nonfungible_token_of_account(account.address, esdt_token.token_id, esdt_token.token_nonce).balance
                if on_chain_amount == 0:
                    continue
                esdt_token.token_amount = on_chain_amount

            payment_tokens = [esdt_token.to_token_transfer()]
            if not account.address.is_smart_contract():
                factory = SmartContractTransactionsFactory(config_tx)
                tx = factory.create_transaction_for_execute(
                    account.address,
                    Address.new_from_bech32(receiver_address),
                    function_name,
                    gas_limit,
                    args,
                    0,
                    payment_tokens
                )
                tx.nonce = account.nonce
                tx.signature = signature

                transactions.append(tx)
                account.nonce += 1
            else:
                # factory = SmartContractTransactionsFactory(config_tx)
                # tx = factory.create_transaction_for_execute(
                #     default_account.address,
                #     account.address,
                #     "callInternalTransferEndpoint",
                #     50000000,
                #     [
                #         token.token_name,
                #         int(token.token_nonce_hex, 16),
                #         int(token.supply),
                #         Address.new_from_bech32(energy_contract.address),
                #         function_name,
                #     ]
                # )
                # tx.nonce = default_account.nonce
                # tx.signature = signature
                # transactions.append(tx)
                # default_account.nonce += 1
                pass

        if METABONDING_UNBOND_UNSTAKE:
            # unstake tokens from metabonding contract
            factory = SmartContractTransactionsFactory(config_tx)
            tx = factory.create_transaction_for_execute(
                account.address,
                Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqt7tyyswqvplpcqnhwe20xqrj7q7ap27d2jps7zczse"),
                "unstake",
                10000000
            )
            tx.nonce = account.nonce
            tx.signature = signature

            transactions.append(tx)
            account.nonce += 1

            # unbond tokens from metabonding contract
            factory = SmartContractTransactionsFactory(config_tx)
            tx = factory.create_transaction_for_execute(
                account.address,
                Address.new_from_bech32("erd1qqqqqqqqqqqqqpgqt7tyyswqvplpcqnhwe20xqrj7q7ap27d2jps7zczse"),
                "unbond",
                10000000
            )
            tx.nonce = account.nonce
            tx.signature = signature

            transactions.append(tx)
            account.nonce += 1

        index = exported_accounts.index(account_with_token)
        exported_accounts[index].nonce = account.nonce
        accounts_index += 1

    print(f"Starting to send {len(transactions)} transactions")
    transactions_chunks = split_to_chunks(transactions, 100)
    i = 0
    for chunk in transactions_chunks:
        num_sent, _ = network_providers.proxy.send_transactions(chunk)
        i += 1
        print(f"Sent {i} / {len(transactions) // 100 + 1 } chunks, {num_sent} / {len(chunk)} transactions")

    print(f"Writing accounts to json file? {exported_accounts_path}")
    if get_user_continue():
        write_accounts_to_json(exported_accounts, exported_accounts_path)
