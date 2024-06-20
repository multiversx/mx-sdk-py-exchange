from argparse import ArgumentParser
from contracts.contract_identities import MetaStakingContractVersion
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, run_graphql_query
from tools.runners.farm_runner import get_farm_addresses_from_chain
import config
from utils.contract_retrievers import retrieve_proxy_staking_by_address
from utils.utils_tx import NetworkProviders

from context import Context

from contracts.metastaking_contract import MetaStakingContract


METASTAKINGS_V1_LABEL = "metastakingsv1"
METASTAKINGS_V2_LABEL = "metastakingsv2"
OUTPUT_METASTAKING_V1_CONTRACTS_FILE = OUTPUT_FOLDER / "metastakingv1_data.json"
OUTPUT_METASTAKING_V2_CONTRACTS_FILE = OUTPUT_FOLDER / "metastakingv2_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    parser.add_argument('--address', type=str, help='metastaking contract address')
    parser.add_argument('--codehash', type=str, help='contract codehash')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--fetch-all', action='store_true',
                       help='fetch metastakings from blockchain')
    mutex.add_argument('--upgrade-all-v1', action='store_true', help='upgrade all metastakings v1')
    mutex.add_argument('--upgrade-all-v2', action='store_true', help='upgrade all metastakings v2')
    mutex.add_argument('--upgrade-all-by-codehash', action='store_true', help='upgrade all metastakings v2')
    mutex.add_argument('--upgrade', action='store_true', help='upgrade metastaking contract by address')
    mutex.add_argument('--set-energy-factory', action='store_true', help='set energy factory for v2 metastaking contracts')


def handle_command(args):
    """Handle metastaking commands"""

    if args.fetch_all:
        fetch_and_save_metastakings_from_chain()
    elif args.upgrade_all_v1:
        upgrade_metastaking_v1_contracts(args.compare_states)
    elif args.upgrade_all_v2:
        upgrade_metastaking_v2_contracts(args.compare_states)
    elif args.upgrade_all_by_codehash:
        upgrade_metastaking_contracts_by_codehash(args.codehash, args.compare_states)
    elif args.upgrade:
        upgrade_metastaking_contract(args.address, args.compare_states)
    elif args.set_energy_factory:
        set_energy_factory()
    else:
        print('invalid arguments')


def fetch_and_save_metastakings_from_chain():
    """Fetch metastaking contracts from chain.
    Will separate metastaking contracts by version.
    v2 determined based on contracts linked to boosted farms. The rest are v1.
    """

    print("Fetch metastaking contracts from chain")

    network_providers = NetworkProviders(API, PROXY)

    boosted_farm_addresses = get_farm_addresses_from_chain("v2")
    print(f"Retrieved {len(boosted_farm_addresses)} boosted farms.")
    metastakings_v2 = get_metastaking_addresses_from_chain_by_farms(boosted_farm_addresses)

    metastakings_v1 = get_metastaking_addresses_from_chain()
    for address in metastakings_v2:
        metastakings_v1.remove(address)
    
    print(f"Retrieved {len(metastakings_v1)} metastaking v1 contracts.")
    print(f"Retrieved {len(metastakings_v2)} metastaking v2 contracts.")

    fetch_and_save_contracts(metastakings_v1, METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE, network_providers.proxy)
    fetch_and_save_contracts(metastakings_v2, METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE, network_providers.proxy)


def upgrade_metastaking_contracts(label: str, file: str, compare_states: bool = False, codehash: str = ''):
    """Upgrade metastaking contracts"""

    print("Upgrade {label} contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    metastaking_addresses = get_metastaking_addresses(label, file, codehash)
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, metastaking_addresses, label)

        if not get_user_continue():
            return

    count = 1
    for metastaking_address in metastaking_addresses:
        print(f"Processing contract {count} / {len(metastaking_addresses)}: {metastaking_address}")
        if not get_user_continue():
            return

        version = MetaStakingContractVersion.V1 if label == METASTAKINGS_V1_LABEL else MetaStakingContractVersion.V2
        metastaking_contract = retrieve_proxy_staking_by_address(metastaking_address, version)

        metastaking_contract.version = MetaStakingContractVersion.V3Boosted
        tx_hash = metastaking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                        config.STAKING_PROXY_BYTECODE_PATH, [])

        if not network_providers.check_complex_tx_status(tx_hash,
                                                         f"upgrade metastaking contract: {metastaking_address}"):
            if not get_user_continue():
                return

        if compare_states:
            fetch_new_and_compare_contract_states(label, metastaking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_metastaking_v1_contracts(compare_states: bool = False):
    """Upgrade all metastaking v1 contracts"""

    upgrade_metastaking_contracts(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE, compare_states)


def upgrade_metastaking_v2_contracts(compare_states: bool = False):
    """Upgrade all metastaking v2 contracts"""

    upgrade_metastaking_contracts(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE, compare_states)


def upgrade_metastaking_contracts_by_codehash(codehash: str, compare_states: bool = False):
    """Upgrade all metastaking contracts by codehash"""

    upgrade_metastaking_contracts(METASTAKINGS_V1_LABEL, OUTPUT_METASTAKING_V1_CONTRACTS_FILE, compare_states, codehash)
    upgrade_metastaking_contracts(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE, compare_states, codehash)


def upgrade_metastaking_contract(metastaking_address: str, compare_states: bool = False):
    """Upgrade metastaking contract by address"""

    print(f"Upgrade metastaking contract {metastaking_address}")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, [metastaking_address], "metastaking_single")

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
        fetch_new_and_compare_contract_states("metastaking_single", metastaking_address, network_providers)

    if not get_user_continue():
        return


def set_energy_factory():
    """Set energy factory for v2 metastaking contracts"""

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    energy_factory_address = context.get_contracts[config.SIMPLE_LOCKS_ENERGY][0].address
    metastaking_addresses = get_metastaking_addresses(METASTAKINGS_V2_LABEL, OUTPUT_METASTAKING_V2_CONTRACTS_FILE)
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return
    
    settable_addresses = []
    for metastaking_address in metastaking_addresses:
        metastaking_contract = MetaStakingContract("", "", "", "", "", "", "", MetaStakingContractVersion.V2, "", metastaking_address)
        if metastaking_contract.get_energy_factory_address() == energy_factory_address:
            settable_addresses.append(metastaking_address)
    
    print(f"Set energy factory for {len(settable_addresses)} metastaking v2 contracts.")

    if not get_user_continue():
        return

    count = 1
    for metastaking_address in settable_addresses:
        print(f"Processing contract {count} / {len(settable_addresses)}: {metastaking_address}")
        if not get_user_continue():
            return

        metastaking_contract = MetaStakingContract("", "", "", "", "", "", "", MetaStakingContractVersion.V2, "", metastaking_address)

        tx_hash = metastaking_contract.set_energy_factory_address(dex_owner, network_providers.proxy, energy_factory_address)

        if not network_providers.check_simple_tx_status(tx_hash,
                                                            f"set energy factory for metastaking contract: {metastaking_address}"):
            if not get_user_continue():
                return

        count += 1


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


def get_metastaking_addresses_from_chain_by_farms(farm_addresses: list) -> list:
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


def get_metastaking_addresses(label: str, file: str, searched_bytecode_hash: str = '') -> list:
    """Get all metastaking addresses"""

    return get_saved_contract_addresses(label, file, searched_bytecode_hash)
