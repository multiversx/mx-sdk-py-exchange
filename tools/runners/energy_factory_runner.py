from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from typing import Any
import json
import config
from context import Context
from multiversx_sdk.core.transactions_factories import TransactionsFactoryConfig, SmartContractTransactionsFactory
from multiversx_sdk import Address
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from tools.common import get_user_continue, fetch_contracts_states, fetch_new_and_compare_contract_states
from tools.runners.common_runner import add_generate_transaction_command, add_upgrade_command, add_verify_command,\
      fund_shadowfork_accounts, get_acounts_with_token, get_default_signature, read_accounts_from_json,\
        sync_account_nonce, verify_contracts, write_accounts_to_json

from utils.utils_tx import ESDTToken, NetworkProviders, prepare_contract_call_tx
from utils.utils_generic import get_file_from_url_or_path, split_to_chunks
from utils.utils_chain import Account, WrapperAddress, get_bytecode_codehash, decode_merged_attributes, base64_to_hex, string_to_hex
from utils.decoding_structures import XMEX_ATTRIBUTES


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
                context.network_provider.proxy.do_post(f"{context.network_provider.proxy.url}/simulator/generate-blocks/{10}", {})      # TODO: remove this; only for local testing
            print(f"Current nonce: {current_nonce}, waiting for nonce: {expected_nonce}")
            sleep(6)
            current_nonce = context.network_provider.proxy.get_account(context.deployer_account.address).nonce
        

def generate_unlock_tokens_transactions(args: Any):
    """Generate unlock tokens transactions"""

    context = Context()

    exported_accounts_path = args.accounts_export
    function_name = "unlockEarly"

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

    current_epoch = network_providers.proxy.get_network_status(1).epoch_number

    exported_accounts = read_accounts_from_json(exported_accounts_path)

    fund_shadowfork_accounts(exported_accounts)
    sleep(30)

    # used only when wanting to sync on-chain, but it takes an eternity
    # with ThreadPoolExecutor(max_workers=500) as executor:
    #     exported_accounts = list(executor.map(sync_account_nonce, exported_accounts))

    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]
    accounts_with_token = get_acounts_with_token(exported_accounts, energy_contract.locked_token)

    print(f"Found {len(accounts_with_token)} accounts with token {energy_contract.locked_token}")

    transactions = []
    accounts_index = 1
    for account_with_token in accounts_with_token:
        print(f"Processing account {accounts_index} / {len(accounts_with_token)}")

        account = Account(pem_file=config.DEFAULT_OWNER)
        account.address = WrapperAddress.from_bech32(account_with_token.address)
        account.nonce = account_with_token.nonce

        tokens = [
            token for token in account_with_token.account_tokens_supply
            if token.token_name == energy_contract.locked_token
        ]

        print(f"Found {len(tokens)} tokens to unstake for account {account_with_token.address}")

        for token in tokens:

            decoded_attributes = decode_merged_attributes(base64_to_hex(token.attributes), XMEX_ATTRIBUTES)
            if int(decoded_attributes.get("unlock_epoch")) <= current_epoch:
                function_name = "unlockTokens"

            payment_tokens = [ESDTToken(token.token_name, int(token.token_nonce_hex, 16), int(token.supply)).to_token_transfer()]
            if not account.address.is_smart_contract():
                factory = SmartContractTransactionsFactory(config_tx)
                tx = factory.create_transaction_for_execute(
                    account.address,
                    Address.new_from_bech32(energy_contract.address),
                    function_name,
                    60000000,
                    [],
                    0,
                    payment_tokens
                )
                tx.nonce = account.nonce
                tx.signature = signature

                transactions.append(tx)
                account.nonce += 1
            else:
                factory = SmartContractTransactionsFactory(config_tx)
                tx = factory.create_transaction_for_execute(
                    default_account.address,
                    account.address,
                    "callInternalTransferEndpoint",
                    50000000,
                    [
                        token.token_name,
                        int(token.token_nonce_hex, 16),
                        int(token.supply),
                        Address.new_from_bech32(energy_contract.address),
                        function_name,
                    ]
                )
                tx.nonce = default_account.nonce
                tx.signature = signature
                transactions.append(tx)
                default_account.nonce += 1

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

    if get_user_continue(f"Writing accounts to json file? {exported_accounts_path}"):
        print(f"Writing accounts to json file")
        write_accounts_to_json(exported_accounts, exported_accounts_path)
