from argparse import ArgumentParser
import json
import os
from multiversx_sdk_cli.accounts import Address
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


STAKINGS_LABEL = "stakings"
OUTPUT_STAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "staking_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--fetch-all', action='store_true',
        help='fetch stakings from blockchain')
    mutex.add_argument('--upgrade-all', action='store_true', help='upgrade all stakings')
    mutex.add_argument('--pause-all', action='store_true', help='pause all stakings')
    mutex.add_argument('--resume-all', action='store_true', help='resume all stakings')


def handle_command(args):
    """Handle staking commands"""

    if args.fetch_all:
        fetch_and_save_stakings_from_chain()
    elif args.pause_all:
        pause_staking_contracts()
    elif args.resume_all:
        resume_staking_contracts()
    elif args.upgrade_all:
        upgrade_staking_contracts(args.compare_states)
    else:
        print('invalid arguments')


def fetch_and_save_stakings_from_chain():
    """Fetch staking contracts from chain"""

    print("Fetch staking contracts from chain")
    return

    network_providers = NetworkProviders(API, PROXY)

    stakings = get_staking_addresses_from_chain()
    fetch_and_save_contracts(stakings, STAKINGS_LABEL, OUTPUT_STAKING_CONTRACTS_FILE, network_providers.proxy)


def pause_staking_contracts():
    """Pause staking contracts"""

    print("Pause staking contracts")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    staking_addresses = get_all_staking_addresses()

    # pause all the stakings
    count = 1
    for staking_address in staking_addresses:
        print(f"Processing contract {count} / {len(staking_addresses)}: {staking_address}")
        data_fetcher = StakingContractDataFetcher(Address(staking_address), network_providers.proxy.url)
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


def resume_staking_contracts():
    """Resume staking contracts"""

    print("Resume staking contracts")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!" \
              "Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES, encoding="URF-8") as reader:
        contract_states = json.load(reader)

    staking_addresses = get_all_staking_addresses()

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


def upgrade_staking_contracts(compare_states: bool = False):
    """Upgrade staking contracts"""

    print("Upgrade staking contracts")
    return

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
                                                    [dex_owner.address.bech32()])

        if not network_providers.check_complex_tx_status(tx_hash, f"upgrade staking contract: {staking_address}"):
            if not get_user_continue():
                return

        if compare_states:
            fetch_new_and_compare_contract_states(STAKINGS_LABEL, staking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


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
