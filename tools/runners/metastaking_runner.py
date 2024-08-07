from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from typing import Any

from multiversx_sdk import Address
from multiversx_sdk.core.transaction_builders import ContractCallBuilder, \
    DefaultTransactionBuildersConfiguration
from contracts.contract_identities import MetaStakingContractVersion
from contracts.metastaking_contract import MetaStakingContract
from events.event_generators import get_lp_from_metastake_token_attributes
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, rule_of_three, run_graphql_query
from tools.runners.common_runner import add_generate_transaction_command, \
    add_upgrade_command, fund_shadowfork_accounts, \
    get_acounts_with_token, get_default_signature, \
    read_accounts_from_json, sync_account_nonce
from utils.utils_chain import Account, WrapperAddress, base64_to_hex
from utils.utils_generic import split_to_chunks
from utils.utils_tx import ESDTToken, NetworkProviders

import config


METASTAKINGS_LABEL = "metastakings"
OUTPUT_METASTAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "metastaking_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for metastaking commands"""
    group_parser = subparsers.add_parser('metastakings', help='metastaking group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='metastaking contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_metastaking_contracts)

    transactions_parser = subgroup_parser.add_parser('generate-transactions', help='metastaking transactions commands')

    transactions_group = transactions_parser.add_subparsers()
    add_generate_transaction_command(transactions_group, generate_unstake_farm_tokens_transaction, 'unstakeFarmTokens', 'unstake farm tokens command')
    add_generate_transaction_command(transactions_group, generate_stake_farm_tokens_transaction, 'stakeFarmTokens', 'stake farm tokens command')


def fetch_and_save_metastakings_from_chain():
    """Fetch metastaking contracts from chain"""

    print("Fetch metastaking contracts from chain")

    network_providers = NetworkProviders(API, PROXY)

    metastakings = get_metastaking_addresses_from_chain()
    fetch_and_save_contracts(metastakings, METASTAKINGS_LABEL, OUTPUT_METASTAKING_CONTRACTS_FILE, network_providers.proxy)


def upgrade_metastaking_contracts(args: Any):
    """Upgrade metastaking contracts"""

    compare_states = args.compare_states

    print("Upgrade metastaking contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    metastaking_addresses = get_metastaking_addresses_from_chain()
    if not args.all:
        metastaking_addresses = [args.address]

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, metastaking_addresses, METASTAKINGS_LABEL)

        if not get_user_continue():
            return

    count = 1
    for metastaking_address in metastaking_addresses:
        print(f"Processing contract {count} / {len(metastaking_addresses)}: {metastaking_address}")
        if not get_user_continue():
            return

        metastaking_contract = MetaStakingContract.load_contract_by_address(metastaking_address, MetaStakingContractVersion.V3Boosted)

        tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                        config.STAKING_PROXY_V3_BYTECODE_PATH, [])

        if not network_providers.check_complex_tx_status(tx_hash,
                                                         f"upgrade metastaking contract: {metastaking_address}"):
            if not get_user_continue():
                return

        if compare_states:
            fetch_new_and_compare_contract_states(METASTAKINGS_LABEL, metastaking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def generate_unstake_farm_tokens_transaction(args: Any):
    """Generate unstake farm tokens transaction"""

    metastaking_address = args.address
    exported_accounts_path = args.accounts_export

    if not exported_accounts_path:
        print("Missing required arguments!")
        return

    if not metastaking_address and not args.all:
        print("Missing required arguments!")
        return

    network_providers = NetworkProviders(API, PROXY)
    network_providers.network = network_providers.proxy.get_network_config()
    chain_id = network_providers.proxy.get_network_config().chain_id
    config_tx = DefaultTransactionBuildersConfiguration(chain_id=chain_id)
    signature = get_default_signature()
    default_account = Account(None, config.DEFAULT_OWNER)
    default_account.sync_nonce(network_providers.proxy)

    exported_accounts = read_accounts_from_json(exported_accounts_path)

    fund_shadowfork_accounts(exported_accounts)
    sleep(30)

    with ThreadPoolExecutor(max_workers=500) as executor:
        exported_accounts = list(executor.map(sync_account_nonce, exported_accounts))

    metastaking_addresses = get_metastaking_addresses_from_chain()
    if not args.all:
        metastaking_addresses = [metastaking_address]

    for metastaking_address in metastaking_addresses:
        metastaking_contract = MetaStakingContract.load_contract_by_address(metastaking_address, MetaStakingContractVersion.V3Boosted)
        accounts_with_token = get_acounts_with_token(exported_accounts, metastaking_contract.metastake_token)
        print(f"Found {len(accounts_with_token)} accounts with token {metastaking_contract.metastake_token}")

        with ThreadPoolExecutor(max_workers=500) as executor:
            accounts_with_token = list(executor.map(sync_account_nonce, accounts_with_token))

        transactions = []
        accounts_index = 1
        for account_with_token in accounts_with_token:
            print(f"Processing account {accounts_index} / {len(accounts_with_token)}")

            account = Account(account_with_token.address, config.DEFAULT_OWNER)
            account.address = WrapperAddress.from_bech32(account_with_token.address)
            account.nonce = account_with_token.nonce
            tokens = [
                token for token in account_with_token.account_tokens_supply
                if token.token_name == metastaking_contract.metastake_token
            ]
            for token in tokens:
                attributes_hex = base64_to_hex(token.attributes)
                decoded_metastake_tk_attributes = get_lp_from_metastake_token_attributes(attributes_hex)
                farm_token_amount = rule_of_three(
                    int(decoded_metastake_tk_attributes['staking_farm_token_amount']),
                    int(decoded_metastake_tk_attributes['lp_farm_token_amount']),
                    int(token.supply),
                )

                payment_tokens = [ESDTToken(token.token_name, int(token.token_nonce_hex, 16), int(token.supply)).to_token_payment()]
                if not account.address.is_smart_contract():
                    builder = ContractCallBuilder(
                        config=config_tx,
                        contract=Address.new_from_bech32(metastaking_address),
                        function_name="unstakeFarmTokens",
                        caller=account.address,
                        call_arguments=[1, 1, farm_token_amount],
                        value=0,
                        gas_limit=75000000,
                        nonce=account.nonce,
                        esdt_transfers=payment_tokens
                    )
                    tx = builder.build()
                    tx.signature = signature

                    transactions.append(tx)
                    account.nonce += 1
                else:
                    builder = ContractCallBuilder(
                        config=config_tx,
                        contract=account.address,
                        function_name="callInternalTransferEndpoint",
                        caller=default_account.address,
                        call_arguments=[
                            token.token_name,
                            int(token.token_nonce_hex, 16),
                            int(token.supply),
                            Address.new_from_bech32(metastaking_address),
                            "unstakeFarmTokens",
                            1, 1, farm_token_amount
                        ],
                        value=0,
                        gas_limit=50000000,
                        nonce=default_account.nonce
                    )
                    default_account.nonce += 1
                    tx = builder.build()
                    tx.signature = signature
                    transactions.append(tx)

            index = exported_accounts.index(account_with_token)
            exported_accounts[index].nonce = account.nonce
            accounts_index += 1

        transactions_chunks = split_to_chunks(transactions, 100)
        for chunk in transactions_chunks:
            network_providers.proxy.send_transactions(chunk)


def generate_stake_farm_tokens_transaction(args: Any):
    """Generate unstake farm tokens transaction"""

    metastaking_address = args.address
    exported_accounts_path = args.accounts_export

    metastaking_address = args.address
    exported_accounts_path = args.accounts_export

    if not metastaking_address or not exported_accounts_path:
        print("Missing required arguments!")
        return

    print(f"Generate stake farm tokens transaction for metastaking contract {metastaking_address}")

    network_providers = NetworkProviders(API, PROXY)
    metastaking_contract = MetaStakingContract.load_contract_by_address(metastaking_address, MetaStakingContractVersion.V2)

    exported_accounts = read_accounts_from_json(exported_accounts_path)
    accounts_with_token = get_acounts_with_token(exported_accounts, metastaking_contract.metastake_token)

    for account_with_token in accounts_with_token:
        account = Account(account_with_token.address, config.DEFAULT_OWNER)
        account.address = WrapperAddress.from_bech32(account_with_token.address)
        account.sync_nonce(network_providers.proxy)
        tokens = [token for token in account_with_token.account_tokens_supply if token.token_name == metastaking_contract.metastake_token]
        for token in tokens:
            metastaking_contract.enter_metastake(
                network_providers.proxy,
                Account(account.address, config.DEFAULT_OWNER),
                [
                    [ESDTToken(token.token_name, int(token.token_nonce_hex, 16), int(token.supply))],
                ],
            )


def get_metastaking_addresses_from_chain() -> list:
    """Get metastaking addresses from chain"""

    query = """
        { stakingProxies { address } }
        """

    result = run_graphql_query(config.GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingProxies']:
        address_list.append(entry['address'])

    return address_list


def get_all_metastaking_addresses(searched_bytecode_hash: str = '') -> list:
    """Get all metastaking addresses"""

    return get_saved_contract_addresses(METASTAKINGS_LABEL, OUTPUT_METASTAKING_CONTRACTS_FILE,
                                        searched_bytecode_hash)
