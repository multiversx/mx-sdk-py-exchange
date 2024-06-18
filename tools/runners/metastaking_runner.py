from argparse import ArgumentParser
from typing import Any
from contracts.contract_identities import MetaStakingContractVersion
from contracts.metastaking_contract import MetaStakingContract
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, run_graphql_query
from tools.runners.common_runner import add_generate_transaction_command, \
    add_upgrade_all_command, \
    add_upgrade_command, \
    get_acounts_with_token, \
    read_accounts_from_json
from utils.contract_retrievers import retrieve_proxy_staking_by_address
from utils.utils_chain import Account, WrapperAddress
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
    add_upgrade_command(contract_group, upgrade_metastaking_contract)
    add_upgrade_all_command(contract_group, upgrade_metastaking_contracts)

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

    metastaking_addresses = get_all_metastaking_addresses('56468a6ae726693a71edcf96cf44673466dd980412388e1e4b073a0b4ee592d7')
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return

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

        metastaking_contract = retrieve_proxy_staking_by_address(metastaking_address, MetaStakingContractVersion.V2)

        metastaking_contract.version = MetaStakingContractVersion.V3Boosted
        tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                        config.STAKING_PROXY_BYTECODE_PATH, [])

        if not network_providers.check_complex_tx_status(tx_hash,
                                                         f"upgrade metastaking contract: {metastaking_address}"):
            if not get_user_continue():
                return

        if compare_states:
            fetch_new_and_compare_contract_states(METASTAKINGS_LABEL, metastaking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_metastaking_contract(args: Any):
    """Upgrade metastaking contract by address"""

    compare_states = args.compare_states
    metastaking_address = args.address

    if not metastaking_address:
        print("Missing required arguments!")
        return

    print(f"Upgrade metastaking contract {metastaking_address} with compare states: {compare_states}")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, [metastaking_address], METASTAKINGS_LABEL)

    if not get_user_continue():
        return

    metastaking_contract = retrieve_proxy_staking_by_address(metastaking_address, MetaStakingContractVersion.V2)

    metastaking_contract.version = MetaStakingContractVersion.V3Boosted
    tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                    config.STAKING_PROXY_V3_BYTECODE_PATH, [], True)

    if not network_providers.check_complex_tx_status(tx_hash,
                                                     f"upgrade metastaking contract: {metastaking_address}"):
        if not get_user_continue():
            return

    if compare_states:
        fetch_new_and_compare_contract_states(METASTAKINGS_LABEL, metastaking_address, network_providers)

    if not get_user_continue():
        return


def generate_unstake_farm_tokens_transaction(args: Any):
    """Generate unstake farm tokens transaction"""

    metastaking_address = args.address
    exported_accounts_path = args.accounts_export

    if not metastaking_address or not exported_accounts_path:
        print("Missing required arguments!")
        return

    print(f"Generate unstake farm tokens transaction for metastaking contract {metastaking_address}")

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
            metastaking_contract.exit_metastake(
                network_providers.proxy,
                account,
                [
                    [ESDTToken(token.token_name, int(token.token_nonce_hex, 16), int(token.supply))],
                    1,
                    1
                ],
            )


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
