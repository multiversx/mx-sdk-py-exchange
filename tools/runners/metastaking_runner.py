from argparse import ArgumentParser
from contracts.contract_identities import MetaStakingContractVersion
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, run_graphql_query
import config
from utils.contract_retrievers import retrieve_proxy_staking_by_address
from utils.utils_tx import NetworkProviders


METASTAKINGS_LABEL = "metastakings"
OUTPUT_METASTAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "metastaking_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    parser.add_argument('--address', type=str, help='metastaking contract address')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--fetch-all', action='store_true',
                       help='fetch metastakings from blockchain')
    mutex.add_argument('--upgrade-all', action='store_true', help='upgrade all metastakings')
    mutex.add_argument('--upgrade', action='store_true', help='upgrade metastaking contract by address')


def handle_command(args):
    """Handle metastaking commands"""

    if args.fetch_all:
        fetch_and_save_metastakings_from_chain()
    elif args.upgrade_all:
        upgrade_metastaking_contracts(args.compare_states)
    elif args.upgrade:
        upgrade_metastaking_contract(args.address, args.compare_states)
    else:
        print('invalid arguments')


def fetch_and_save_metastakings_from_chain():
    """Fetch metastaking contracts from chain"""

    print("Fetch metastaking contracts from chain")

    network_providers = NetworkProviders(API, PROXY)

    metastakings = get_metastaking_addresses_from_chain()
    fetch_and_save_contracts(metastakings, METASTAKINGS_LABEL, OUTPUT_METASTAKING_CONTRACTS_FILE, network_providers.proxy)


def upgrade_metastaking_contracts(compare_states: bool = False):
    """Upgrade metastaking contracts"""

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


def upgrade_metastaking_contract(metastaking_address: str, compare_states: bool = False):
    """Upgrade metastaking contract by address"""

    print(f"Upgrade metastaking contract {metastaking_address}")

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
