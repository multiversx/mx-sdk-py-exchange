from argparse import ArgumentParser
from typing import Any
from contracts.contract_identities import MetaStakingContractVersion
from contracts.metastaking_contract import MetaStakingContract
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, run_graphql_query
from tools.runners.common_runner import add_generate_transaction_command, \
    add_upgrade_all_command, add_upgrade_command, \
    get_acounts_with_token, read_accounts_from_json, verify_contracts, \
    add_verify_command, verify_contracts
from tools.runners.farm_runner import get_farm_addresses_from_chain
from utils.utils_chain import Account, WrapperAddress, get_bytecode_codehash
from utils.utils_tx import ESDTToken, NetworkProviders
from utils.utils_generic import get_file_from_url_or_path

import config

from context import Context

from contracts.metastaking_contract import MetaStakingContract


METASTAKINGS_V1_LABEL = "metastakingsv1"
METASTAKINGS_V2_LABEL = "metastakingsv2"
OUTPUT_METASTAKING_V1_CONTRACTS_FILE = OUTPUT_FOLDER / "metastakingv1_data.json"
OUTPUT_METASTAKING_V2_CONTRACTS_FILE = OUTPUT_FOLDER / "metastakingv2_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for metastaking commands"""
    group_parser = subparsers.add_parser('metastakings', help='metastaking group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='metastaking contract commands')

    contract_group = contract_parser.add_subparsers()
    
    command_parser = contract_group.add_parser('fetch-all', help='fetch all contracts command')
    command_parser.set_defaults(func=fetch_and_save_metastakings_from_chain)

    command_parser = contract_group.add_parser('upgrade-all-v1', help='upgrade all v1 contracts command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    command_parser.add_argument('--bytecode', type=str, help='optional: contract bytecode path/url; defaults to config path')
    command_parser.set_defaults(func=upgrade_metastaking_v1_contracts)
    command_parser = contract_group.add_parser('upgrade-all-v2', help='upgrade all v2 contracts command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    command_parser.add_argument('--bytecode', type=str, help='optional: contract bytecode path/url; defaults to config path')
    command_parser.set_defaults(func=upgrade_metastaking_v2_contracts)

    command_parser = contract_group.add_parser('upgrade-by-codehash', help='upgrade contract command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    command_parser.add_argument('--codehash', type=str, help='contract codehash')
    command_parser.add_argument('--bytecode', type=str, help='optional: contract bytecode path/url; defaults to config path')
    command_parser.set_defaults(func=upgrade_metastaking_contracts_by_codehash)

    add_upgrade_command(contract_group, upgrade_metastaking_contract)

    add_verify_command(contract_group, verify_metastaking_v1_contracts, "verify-v1")
    add_verify_command(contract_group, verify_metastaking_v2_contracts, "verify-v2")

    command_parser = contract_group.add_parser('set-energy-factory-all', help='set energy factory for all v2 contracts command')
    command_parser.set_defaults(func=set_energy_factory)

    transactions_parser = subgroup_parser.add_parser('generate-transactions', help='metastaking transactions commands')

    transactions_group = transactions_parser.add_subparsers()
    add_generate_transaction_command(transactions_group, generate_unstake_farm_tokens_transaction, 'unstakeFarmTokens', 'unstake farm tokens command')
    add_generate_transaction_command(transactions_group, generate_stake_farm_tokens_transaction, 'stakeFarmTokens', 'stake farm tokens command')


def fetch_and_save_metastakings_from_chain(_):
    """Fetch metastaking contracts from chain.
    Will separate metastaking contracts by version.
    v2 determined based on contracts linked to boosted farms. The rest are v1.
    """

    print("Fetch metastaking contracts from chain")

    boosted_farm_addresses = get_farm_addresses_from_chain("v2")
    print(f"Retrieved {len(boosted_farm_addresses)} boosted farms.")
    metastakings_v2 = get_metastaking_addresses_from_chain_by_farms(boosted_farm_addresses)

    metastakings_v1 = get_metastaking_addresses_from_chain()
    for address in metastakings_v2:
        metastakings_v1.remove(address)
    
    print(f"Retrieved {len(metastakings_v1)} metastaking v1 contracts.")
    print(f"Retrieved {len(metastakings_v2)} metastaking v2 contracts.")

    fetch_and_save_contracts(metastakings_v1, METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE)
    fetch_and_save_contracts(metastakings_v2, METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE)


def upgrade_metastaking_contracts(label: str, file: str, bytecode_path: str = '', compare_states: bool = False, codehash: str = ''):
    """Upgrade metastaking contracts"""

    print(f"Upgrade {label} contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    metastaking_addresses = get_metastaking_addresses(label, file, codehash)
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return
    print(f"Processing {len(metastaking_addresses)} metastaking contracts.")
    
    version = MetaStakingContractVersion.V1 if label == METASTAKINGS_V1_LABEL else MetaStakingContractVersion.V2

    if bytecode_path:
        bytecode = get_file_from_url_or_path(bytecode_path)
    else:
        config_bytecode = config.STAKING_PROXY_V3_BYTECODE_PATH if version == MetaStakingContractVersion.V2 else config.STAKING_PROXY_V2_BYTECODE_PATH
        bytecode = get_file_from_url_or_path(config_bytecode)

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, metastaking_addresses, label)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    count = 1
    for metastaking_address in metastaking_addresses:
        print(f"Processing contract {count} / {len(metastaking_addresses)}: {metastaking_address}")

        metastaking_contract = MetaStakingContract.load_contract_by_address(metastaking_address, version)

        tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy, bytecode, [])

        if not network_providers.check_simple_tx_status(tx_hash,
                                                         f"upgrade metastaking contract: {metastaking_address}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        if compare_states:
            fetch_new_and_compare_contract_states(label, metastaking_address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

        count += 1


def upgrade_metastaking_v1_contracts(args: Any):
    """Upgrade all metastaking v1 contracts"""
    compare_states = args.compare_states
    bytecode = args.bytecode
    upgrade_metastaking_contracts(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE, bytecode, compare_states)


def upgrade_metastaking_v2_contracts(args: Any):
    """Upgrade all metastaking v2 contracts"""
    compare_states = args.compare_states
    bytecode = args.bytecode
    upgrade_metastaking_contracts(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE, bytecode, compare_states)


def upgrade_metastaking_contracts_by_codehash(args: Any):
    """Upgrade all metastaking contracts by codehash"""
    compare_states = args.compare_states
    codehash = args.codehash
    bytecode = args.bytecode
    if not codehash:
        print("Missing coehash argument!")
        return
    upgrade_metastaking_contracts(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE, bytecode, compare_states, codehash)
    upgrade_metastaking_contracts(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE, bytecode, compare_states, codehash)


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

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = get_file_from_url_or_path(config.STAKING_PROXY_V3_BYTECODE_PATH)

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue():
        return

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, [metastaking_address], "metastaking_single")

    if not get_user_continue():
        return

    metastaking_contract = MetaStakingContract.load_contract_by_address(metastaking_address, MetaStakingContractVersion.V3Boosted)

    tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                    bytecode_path, [], True)

    if not network_providers.check_simple_tx_status(tx_hash,
                                                     f"upgrade metastaking contract: {metastaking_address}"):
        if not get_user_continue():
            return

    if compare_states:
        fetch_new_and_compare_contract_states("metastaking_single", metastaking_address, network_providers)

    if not get_user_continue():
        return
    

def verify_metastaking_v1_contracts(args: Any):
    print("Verifying metastaking v1 contracts...")

    all_addresses = get_metastaking_addresses(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE)
    verify_contracts(args, all_addresses)
    
    print("All contracts have been verified.")


def verify_metastaking_v2_contracts(args: Any):
    print("Verifying metastaking v2 contracts...")

    all_addresses = get_metastaking_addresses(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE)
    verify_contracts(args, all_addresses)
    
    print("All contracts have been verified.")


def set_energy_factory(_):
    """Set energy factory for v2 metastaking contracts"""

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    metastaking_addresses = get_metastaking_addresses(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE)
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return
    
    settable_addresses = []
    for metastaking_address in metastaking_addresses:
        metastaking_contract = MetaStakingContract("", "", "", "", "", "", "", MetaStakingContractVersion.V2, "", metastaking_address)
        if metastaking_contract.get_energy_factory_address(network_providers.proxy) != energy_factory_address:
            settable_addresses.append(metastaking_address)
    
    print(f"Set energy factory for {len(settable_addresses)} metastaking v2 contracts.")

    if not get_user_continue():
        return

    count = 1
    for metastaking_address in settable_addresses:
        print(f"Processing contract {count} / {len(settable_addresses)}: {metastaking_address}")

        metastaking_contract = MetaStakingContract("", "", "", "", "", "", "", MetaStakingContractVersion.V2, "", metastaking_address)

        tx_hash = metastaking_contract.set_energy_factory_address(dex_owner, network_providers.proxy, energy_factory_address)

        if not network_providers.check_simple_tx_status(tx_hash,
                                                            f"set energy factory for metastaking contract: {metastaking_address}"):
            if not get_user_continue():
                return

        count += 1


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


def get_metastaking_addresses_from_chain() -> list[str]:
    """Get metastaking addresses from chain"""

    query = """
        { stakingProxies { address } }
        """

    result = run_graphql_query(config.GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingProxies']:
        address_list.append(entry['address'])

    return address_list


def get_metastaking_addresses_from_chain_by_farms(farm_addresses: list) -> list[str]:
    """Get metastaking addresses from chain by farms"""

    query = """
        { stakingProxies { address lpFarmAddress } }
        """

    result = run_graphql_query(config.GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingProxies']:
        if entry['lpFarmAddress'] in farm_addresses:
            address_list.append(entry['address'])

    return address_list


def get_all_metastaking_addresses() -> list[str]:
    """Get all saved metastaking addresses"""

    metastaking_addresses = get_metastaking_addresses(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE)
    metastaking_addresses.extend(get_metastaking_addresses(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE))

    return metastaking_addresses


def get_metastaking_v1_addresses() -> list[str]:
    """Get all saved metastaking v1 addresses"""
    return get_metastaking_addresses(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE)


def get_metastaking_v2_addresses() -> list[str]:
    """Get all saved metastaking v2 addresses"""
    return get_metastaking_addresses(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE)


def get_metastaking_addresses(label: str, file: str, searched_bytecode_hash: str = '') -> list[str]:
    """Get saved metastaking addresses"""
    return get_saved_contract_addresses(label, file, searched_bytecode_hash)
