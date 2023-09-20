from argparse import ArgumentParser
import json
import os
from config import GRAPHQL
from contracts.contract_identities import FarmContractVersion
from contracts.farm_contract import FarmContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, \
    PROXY, fetch_and_save_contracts, fetch_new_and_compare_contract_states, \
    get_owner, get_saved_contract_addresses, get_user_continue, run_graphql_query, fetch_contracts_states
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.contract_retrievers import retrieve_farm_by_address
from utils.utils_tx import NetworkProviders
import config


FARMSV13_LABEL = "farmsv13"
FARMSV12_LABEL = "farmsv12"
FARMSV2_LABEL = "farmsv2"
OUTPUT_FARMV13_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13_data.json"
OUTPUT_FARMV13LOCKED_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13locked_data.json"
OUTPUT_FARMV12_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv12_data.json"
OUTPUT_FARMV2_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv2_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--fetch-all', action='store_true',
        help='fetch farms from blockchain')
    mutex.add_argument('--pause-all', action='store_true', help='pause all farms')
    mutex.add_argument('--resume-all', action='store_true', help='resume all farms')
    mutex.add_argument('--upgrade-all-v1_2', action='store_true', help='upgrade all v1.2 farms')
    mutex.add_argument('--upgrade-all-v1_3', action='store_true',
                       help='upgrade all v1.3 farms')
    mutex.add_argument('--upgrade-all-v2', action='store_true',
                       help='upgrade all v2 farms')
    mutex.add_argument('--set-transfer-role', action='store_true',
                       help='set transfer role for v1.3 farms')
    mutex.add_argument('--stop-produce-rewards', action='store_true',
                       help='stop producing rewards for farms')
    mutex.add_argument('--replace-v2-ownership',
                       help='replace v2 soft ownership; specify old owner address to be replaced')
    mutex.add_argument('--remove-penalty', action='store_true', help='remove penalty from farms')


def handle_command(args):
    """Handle the command passed to the runner"""

    if args.fetch_all:
        fetch_and_save_farms_from_chain()
    elif args.pause_all:
        pause_farm_contracts()
    elif args.resume_all:
        resume_farm_contracts()
    elif args.upgrade_all_v1_2:
        upgrade_farmv12_contracts()
    elif args.upgrade_all_v1_3:
        upgrade_farmv13_contracts()
    elif args.upgrade_all_v2:
        upgrade_farmv2_contracts(args.compare_states)
    elif args.set_transfer_role:
        set_transfer_role_farmv13_contracts()
    elif args.stop_produce_rewards:
        stop_produce_rewards_farms()
    elif args.replace_v2_ownership:
        replace_v2_ownership(args.replace_v2_ownership, args.compare_states)
    elif args.remove_penalty:
        remove_penalty_farms()
    else:
        print('invalid arguments')


def fetch_and_save_farms_from_chain():
    """Fetch and save farms from chain"""

    print("Fetching farms from chain...")

    network_providers = NetworkProviders(API, PROXY)

    farmsv13 = get_farm_addresses_from_chain("v1.3")
    farmsv13locked = get_farm_addresses_locked_from_chain()
    farmsv12 = get_farm_addresses_from_chain("v1.2")
    farmsv2 = get_farm_addresses_from_chain("v2")
    fetch_and_save_contracts(farmsv13, FARMSV13_LABEL, OUTPUT_FARMV13_CONTRACTS_FILE, network_providers.proxy)
    fetch_and_save_contracts(farmsv13locked, FARMSV13_LABEL, OUTPUT_FARMV13LOCKED_CONTRACTS_FILE, network_providers.proxy)
    fetch_and_save_contracts(farmsv12, FARMSV12_LABEL, OUTPUT_FARMV12_CONTRACTS_FILE, network_providers.proxy)
    fetch_and_save_contracts(farmsv2, FARMSV2_LABEL, OUTPUT_FARMV2_CONTRACTS_FILE, network_providers.proxy)


def pause_farm_contracts():
    """Pause all farms"""

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    farm_addresses = get_all_farm_v2_addresses()

    print(f"Pausing {len(farm_addresses)} farm contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    # pause all the farms
    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        data_fetcher = FarmContractDataFetcher(Address(farm_address, "erd"), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract = FarmContract("", "", "", farm_address, FarmContractVersion.V2Boosted)
        if contract_state != 0:
            tx_hash = contract.pause(dex_owner, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"pause farm contract: {farm_address}"):
                if not get_user_continue():
                    return
        else:
            print(f"Contract {farm_address} already inactive. Current state: {contract_state}")

        count += 1


def resume_farm_contracts():
    """Resume all farms"""

    print("Resuming farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!" \
              " Cannot proceed safely without altering initial state.")
        return

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    farm_addresses = get_all_farm_v2_addresses()

    print(f"Processing resume for {len(farm_addresses)} farm contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    # pause all the farm contracts
    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        if farm_address not in contract_states:
            print(f"Contract {farm_address} wasn't touched for no available initial state!")
            continue
        # resume only if the farm contract was active
        if contract_states[farm_address] == 1:
            contract = FarmContract("", "", "", farm_address, FarmContractVersion.V2Boosted)
            tx_hash = contract.resume(dex_owner, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"resume farm contract: {farm_address}"):
                if not get_user_continue():
                    return
        else:
            print(f"Contract {farm_address} wasn't touched because of initial state: "
                  f"{contract_states[farm_address]}")

        count += 1


def upgrade_farmv12_contracts():
    """Upgrade all v1.2 farms"""

    print("Upgrading v1.2 farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v12_addresses()

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V12)

        tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy,
                                            config.FARM_V12_BYTECODE_PATH, [],
                                            no_init=True)

        if not network_providers.check_complex_tx_status(tx_hash, f"upgrade farm v12 contract: {address}"):
            if not get_user_continue():
                return

        fetch_new_and_compare_contract_states(FARMSV12_LABEL, address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_farmv13_contracts():
    """Upgrade all v1.3 farms"""

    print("Upgrading v1.3 farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v13locked_addresses()

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V14Locked)

        tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy,
                                            config.FARM_V13_BYTECODE_PATH, [],
                                            no_init=True)

        if not network_providers.check_complex_tx_status(tx_hash, f"upgrade farm v13 contract: {address}"):
            if not get_user_continue():
                return

        fetch_new_and_compare_contract_states(FARMSV13_LABEL, address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_farmv2_contracts(compare_states: bool):
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v2_addresses()

    print(f"Upgrading {len(all_addresses)} boosted farm contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract: FarmContract
        contract = retrieve_farm_by_address(address)
        lp_address = contract.get_lp_address(network_providers.proxy)

        if compare_states:
            print(f"Fetching contract state before upgrade...")
            fetch_contracts_states("pre", network_providers, [address], FARMSV2_LABEL)

            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy,
                                            config.FARM_V2_BYTECODE_PATH,
                                            [lp_address, dex_owner.address.bech32()])

        if not network_providers.check_simple_tx_status(tx_hash, f"upgrade farm v2 contract: {address}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        if compare_states:
            fetch_new_and_compare_contract_states(FARMSV2_LABEL, address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

        count += 1


def set_transfer_role_farmv13_contracts():
    """Set transfer role for all v1.3 farms"""

    print("Setting transfer role for v1.3 farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v13locked_addresses()

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V14Locked)

        tx_hash = contract.set_transfer_role_farm_token(dex_owner, network_providers.proxy, "")

        _ = network_providers.check_complex_tx_status(tx_hash, f"set transfer role farm v13 locked contract: {address}")

        if not get_user_continue():
            return

        count += 1


def replace_v2_ownership(old_owner: str, compare_states: bool = False):
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v2_addresses()
    cleaned_address = Address(old_owner).bech32()   # pass it through the Address class to check if it's valid

    print(f"Searching farm ownership for {cleaned_address}...")

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V2Boosted)
        data_fetcher = FarmContractDataFetcher(Address(address), network_providers.proxy.url)

        permissions = data_fetcher.get_data("getPermissions", [Address(cleaned_address).pubkey()])
        if not permissions:
            continue
        print(f"Found permissions {permissions} for {cleaned_address} in contract {address}. Replace it?")
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            continue

        if compare_states:
            print(f"Fetching contract state before change...")
            fetch_contracts_states("pre", network_providers, [address], FARMSV2_LABEL)

            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        tx_hash = contract.update_owner_or_admin(dex_owner, network_providers.proxy, cleaned_address)

        if not network_providers.check_simple_tx_status(tx_hash, f"change farm v2 ownership: {address}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        if compare_states:
            fetch_new_and_compare_contract_states(FARMSV2_LABEL, address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

        count += 1


def stop_produce_rewards_farms():
    """Stop produce rewards for all farms"""

    print("Stopping produce rewards for farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    farm_addresses = get_all_farm_v13_addresses()

    # stop rewards in all the farms
    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        contract = FarmContract("", "", "", farm_address, FarmContractVersion.V14Locked)
        tx_hash = contract.end_produce_rewards(dex_owner, network_providers.proxy)
        if not network_providers.check_simple_tx_status(tx_hash, f"stop produce rewards farm contract: {farm_address}"):
            if not get_user_continue():
                return

        count += 1


def remove_penalty_farms():
    """Remove penalty from all farms"""

    print("Removing penalty from farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    farm_addresses = get_all_farm_v13_addresses()

    # remove penalty in all the farms
    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        contract = FarmContract("", "", "", farm_address, FarmContractVersion.V14Locked)
        tx_hash = contract.set_penalty_percent(dex_owner, network_providers.proxy, 0)
        if not network_providers.check_simple_tx_status(tx_hash, f"remove penalty farm contract: {farm_address}"):
            if not get_user_continue():
                return

        count += 1


def get_farm_addresses_from_chain(version: str) -> list:
    """
    version: v1.3 | v1.2 | v2
    """
    if version == "v2":
        model = "FarmModelV2"
    elif version == "v1.3":
        model = "FarmModelV1_3"
    elif version == "v1.2":
        model = "FarmModelV1_2"
    else:
        raise Exception(f"Unknown farm version: {version}")

    query = """
        { farms {
        ... on """ + model + """ {
         address
         version
         } } }
        """

    result = run_graphql_query(GRAPHQL, query)

    address_list = []
    for entry in result['data']['farms']:
        if entry.get('version') == version:
            address_list.append(entry['address'])

    return address_list


def get_farm_addresses_locked_from_chain() -> list:
    """Get farms with locked rewards"""

    query = """
            { farms {
             ... on FarmModelV1_3 { 
             address
             version
             rewardType
             } } }
            """

    result = run_graphql_query(GRAPHQL, query)

    address_list = []
    for entry in result['data']['farms']:
        if entry.get('version') == 'v1.3' and entry.get('rewardType') == 'lockedRewards':
            address_list.append(entry['address'])

    return address_list


def get_all_farm_v13_addresses() -> list:
    """Get all v1.3 farms addresses"""

    return get_saved_contract_addresses(FARMSV13_LABEL, OUTPUT_FARMV13_CONTRACTS_FILE)


def get_all_farm_v13locked_addresses() -> list:
    """Get all v1.3 farms addresses with locked rewards"""

    return get_saved_contract_addresses(FARMSV13_LABEL, OUTPUT_FARMV13LOCKED_CONTRACTS_FILE)


def get_all_farm_v2_addresses() -> list:
    """Get all v2 farms addresses with locked rewards"""

    return get_saved_contract_addresses(FARMSV2_LABEL, OUTPUT_FARMV2_CONTRACTS_FILE)


def get_all_farm_v12_addresses() -> list:
    """Get all v1.2 farms addresses"""

    return get_saved_contract_addresses(FARMSV12_LABEL, OUTPUT_FARMV12_CONTRACTS_FILE)
