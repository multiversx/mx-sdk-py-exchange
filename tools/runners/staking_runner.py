from argparse import ArgumentParser
import json
import os
import time
from multiversx_sdk import Address
import config
from config import GRAPHQL
from contracts.contract_identities import StakingContractVersion
from contracts.staking_contract import StakingContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, \
    PROXY, fetch_and_save_contracts, fetch_contracts_states, \
    fetch_new_and_compare_contract_states, get_owner, \
    get_saved_contract_addresses, get_user_continue, run_graphql_query
from utils.contract_data_fetchers import StakingContractDataFetcher
from utils.contract_retrievers import retrieve_staking_by_address
from utils.utils_tx import NetworkProviders

from contracts.simple_lock_energy_contract import SimpleLockEnergyContract

from context import Context

from utils.utils_chain import log_explorer_transaction


STAKINGS_LABEL = "stakings"
OUTPUT_STAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "staking_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_true', help='compare states before and after upgrade')
    parser.add_argument('--address', type=str, help='staking contract address')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--fetch-all', action='store_true',
                       help='fetch stakings from blockchain')
    mutex.add_argument('--upgrade-all', action='store_true', help='upgrade all stakings')
    mutex.add_argument('--upgrade', action='store_true', help='upgrade staking contract by address')
    mutex.add_argument('--setup-boost-all', action='store_true', help='setup boosted parameters for all contracts')
    mutex.add_argument('--setup-boost', action='store_true', help='setup boosted parameters for contract by address')
    mutex.add_argument('--pause-all', action='store_true', help='pause all stakings')
    mutex.add_argument('--resume-all', action='store_true', help='resume all stakings')
    mutex.add_argument('--pause', action='store_true', help='pause staking contract by address')
    mutex.add_argument('--resume', action='store_true', help='resume staking contract by address')


def handle_command(args):
    """Handle staking commands"""

    if args.fetch_all:
        fetch_and_save_stakings_from_chain()
    elif args.pause_all:
        pause_all_staking_contracts()
    elif args.resume_all:
        resume_staking_contracts()
    elif args.pause:
        pause_staking_contract(args.address)
    elif args.resume:
        resume_staking_contract(args.address)
    elif args.upgrade_all:
        upgrade_staking_contracts(args.compare_states)
    elif args.upgrade:
        upgrade_staking_contract(args.address, args.compare_states)
    elif args.setup_boost_all:
        setup_boosted_parameters_for_all_stakings(args.compare_states)
    elif args.setup_boost:
        setup_boosted_parameters_for_staking(args.address, args.compare_states)
    else:
        print('invalid arguments')


def fetch_and_save_stakings_from_chain():
    """Fetch staking contracts from chain"""

    print("Fetch staking contracts from chain")

    network_providers = NetworkProviders(API, PROXY)

    stakings = get_staking_addresses_from_chain()
    fetch_and_save_contracts(stakings, STAKINGS_LABEL, OUTPUT_STAKING_CONTRACTS_FILE, network_providers.proxy)


def pause_staking_contracts(staking_addresses: list[str]):
    """Pause staking contracts"""

    print("Pause staking contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    # pause all the stakings
    count = 1
    for staking_address in staking_addresses:
        print(f"Processing contract {count} / {len(staking_addresses)}: {staking_address}")
        data_fetcher = StakingContractDataFetcher(Address(staking_address, "erd"), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract = StakingContract("", 0, 0, 0, StakingContractVersion.V1, "", staking_address)
        if contract_state != 0:
            tx_hash = contract.pause(dex_owner, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"pause staking contract: {staking_address}"):
                if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                    return
        else:
            print(f"Contract {staking_address} already inactive. Current state: {contract_state}")

        count += 1


def pause_all_staking_contracts():
    staking_addresses = get_all_staking_addresses()
    pause_staking_contracts(staking_addresses)


def pause_staking_contract(staking_address: str):
    pause_staking_contracts([staking_address])


def resume_staking_contracts(staking_addresses: list[str]):
    """Resume staking contracts"""

    print("Resume staking contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              "Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES, encoding="URF-8") as reader:
        contract_states = json.load(reader)

    # pause all the staking contracts
    count = 1
    for staking_address in staking_addresses:
        print(f"Processing contract {count} / {len(staking_addresses)}: {staking_address}")
        if staking_address not in contract_states:
            print(f"Contract {staking_address} wasn't touched for no available initial state!")
            continue
        # resume only if the staking contract was active
        if contract_states[staking_address] == 1:
            contract = StakingContract("", 0, 0, 0, StakingContractVersion.V1, "", staking_address)
            tx_hash = contract.resume(dex_owner, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"resume staking contract: {staking_address}"):
                if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                    return
        else:
            print(f"Contract {staking_address} wasn't touched because of initial state: "
                  f"{contract_states[staking_address]}")

        count += 1


def resume_all_staking_contracts():
    staking_addresses = get_all_staking_addresses()
    resume_staking_contracts(staking_addresses)


def resume_staking_contract(staking_address: str):
    resume_staking_contracts([staking_address])


def upgrade_staking_contracts(compare_states: bool = False):
    """Upgrade staking contracts"""

    print("Upgrade staking contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    staking_addresses = get_all_staking_addresses()
    if not staking_addresses:
        print("No staking contracts available!")
        return

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, staking_addresses, STAKINGS_LABEL)

        if not get_user_continue():
            return

    count = 1
    for staking_address in staking_addresses:
        print(f"Processing contract {count} / {len(staking_addresses)}: {staking_address}")
        if not get_user_continue():
            return

        staking_contract = retrieve_staking_by_address(staking_address, StakingContractVersion.V2)

        staking_contract.version = StakingContractVersion.V3Boosted
        tx_hash = staking_contract.contract_upgrade(dex_owner, network_providers.proxy, config.STAKING_V3_BYTECODE_PATH, 
                                                    [], True)

        if not network_providers.check_complex_tx_status(tx_hash, f"upgrade staking contract: {staking_address}"):
            if not get_user_continue():
                return

        if compare_states:
            fetch_new_and_compare_contract_states(STAKINGS_LABEL, staking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_staking_contract(staking_address: str, compare_states: bool = False):
    """Upgrade staking contract"""

    print("Upgrade staking contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if compare_states:
        print("Fetching contracts states before upgrade...")
        fetch_contracts_states("pre", network_providers, [staking_address], STAKINGS_LABEL)

    if not get_user_continue():
        return

    staking_contract = retrieve_staking_by_address(staking_address, StakingContractVersion.V2)

    staking_contract.version = StakingContractVersion.V3Boosted
    tx_hash = staking_contract.contract_upgrade(dex_owner, network_providers.proxy, config.STAKING_V3_BYTECODE_PATH,
                                                [], True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade staking contract: {staking_address}"):
        if not get_user_continue():
            return

    if compare_states:
        fetch_new_and_compare_contract_states(STAKINGS_LABEL, staking_address, network_providers)

    if not get_user_continue():
        return
    

def setup_boosted_parameters_with_energy_address(staking_address: str, energy_address: str, compare_states: bool = False):
    """Setup boosted parameters for staking contract with provided energy address"""

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    energy_contract = SimpleLockEnergyContract("", "", "", "", energy_address)

    if compare_states:
        print("Fetching contracts states before setup...")
        fetch_contracts_states("pre", network_providers, [staking_address], STAKINGS_LABEL)

    if not get_user_continue():
        return

    staking_contract = StakingContract("", 0, 0, 0, StakingContractVersion.V3Boosted, "", staking_address)

    hashes = []
    hashes.append(staking_contract.set_boosted_yields_rewards_percentage(dex_owner, network_providers.proxy, 6000))
    hashes.append(staking_contract.set_boosted_yields_factors(dex_owner, network_providers.proxy, 
                                                  [2, 1, 0, 1, 1]))
    hashes.append(staking_contract.set_energy_factory_address(dex_owner, network_providers.proxy, energy_address))
    hashes.append(energy_contract.add_sc_to_whitelist(dex_owner, network_providers.proxy, staking_address))

    for tx_hash in hashes:
        log_explorer_transaction(tx_hash, network_providers.proxy.url)
        
    time.sleep(6)

    if compare_states:
        fetch_new_and_compare_contract_states(STAKINGS_LABEL, staking_address, network_providers)

    if not get_user_continue():
        return
    

def setup_boosted_parameters_for_staking(staking_address: str, compare_states: bool = False):
    """Setup boosted parameters for staking contract"""
    print("Setup boosted parameters for staking contract")

    context = Context()
    energy_contract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    setup_boosted_parameters_with_energy_address(staking_address, energy_contract.address, compare_states)


def setup_boosted_parameters_for_all_stakings(compare_states: bool = False):
    """Setup boosted parameters for all staking contracts"""
    print("Setup boosted parameters for all staking contracts")

    context = Context()
    energy_contract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]
    staking_addresses = get_all_staking_addresses()

    for staking_address in staking_addresses:
        setup_boosted_parameters_with_energy_address(staking_address, energy_contract.address, compare_states)


def get_staking_addresses_from_chain() -> list:
    """Get staking addresses from chain"""

    query = """
        { stakingFarms { address } }
        """

    result = run_graphql_query(GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingFarms']:
        address_list.append(entry['address'])

    return address_list


def get_all_staking_addresses() -> list:
    """Get all staking addresses"""

    return get_saved_contract_addresses(STAKINGS_LABEL, OUTPUT_STAKING_CONTRACTS_FILE)
