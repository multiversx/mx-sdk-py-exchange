from argparse import ArgumentParser
import json
import os
from typing import Any

from multiversx_sdk import Address
from config import GRAPHQL
from contracts.contract_identities import FarmContractVersion
from contracts.farm_contract import FarmContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, \
    PROXY, fetch_and_save_contracts, fetch_new_and_compare_contract_states, \
    get_owner, get_saved_contract_addresses, get_user_continue, run_graphql_query, fetch_contracts_states
from tools.runners.common_runner import add_upgrade_all_command, add_upgrade_command
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.contract_retrievers import retrieve_farm_by_address
from utils.utils_tx import NetworkProviders
from utils.utils_chain import get_bytecode_codehash
from utils.utils_generic import get_file_from_url_or_path
import config


FARMSV13_LABEL = "farmsv13"
FARMSV12_LABEL = "farmsv12"
FARMSV2_LABEL = "farmsv2"
OUTPUT_FARMV13_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13_data.json"
OUTPUT_FARMV13LOCKED_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13locked_data.json"
OUTPUT_FARMV12_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv12_data.json"
OUTPUT_FARMV2_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv2_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for farms commands"""
    group_parser = subparsers.add_parser('farms', help='farms group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='farms contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_farmv2_contract)
    add_upgrade_all_command(contract_group, upgrade_farmv2_contracts)

    command_parser = contract_group.add_parser('fetch-all', help='fetch all contracts command')
    command_parser.set_defaults(func=fetch_and_save_farms_from_chain)

    command_parser = contract_group.add_parser('pause-all', help='pause all contracts command')
    command_parser.set_defaults(func=pause_farm_contracts)

    command_parser = contract_group.add_parser('resume-all', help='resume all contracts command')
    command_parser.set_defaults(func=resume_farm_contracts)

    command_parser = contract_group.add_parser('replace-v2-ownership', help='overwrite ownership address for all contracts command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after change')
    command_parser.add_argument('--old-owner', type=str, help='old owner address to replace')
    command_parser.set_defaults(func=replace_v2_ownership)

    command_parser = contract_group.add_parser('update-boosted-factors-all', help='update boosted factors for all contracts command')
    command_parser.set_defaults(func=update_boosted_factors)
    

    return group_parser


def fetch_and_save_farms_from_chain(_):
    """Fetch and save farms from chain"""

    print("Fetching farms from chain...")

    farmsv13 = get_farm_addresses_from_chain("v1.3")
    farmsv13locked = get_farm_addresses_locked_from_chain()
    farmsv12 = get_farm_addresses_from_chain("v1.2")
    farmsv2 = get_farm_addresses_from_chain("v2")
    fetch_and_save_contracts(farmsv13, FARMSV13_LABEL, OUTPUT_FARMV13_CONTRACTS_FILE)
    fetch_and_save_contracts(farmsv13locked, FARMSV13_LABEL, OUTPUT_FARMV13LOCKED_CONTRACTS_FILE)
    fetch_and_save_contracts(farmsv12, FARMSV12_LABEL, OUTPUT_FARMV12_CONTRACTS_FILE)
    fetch_and_save_contracts(farmsv2, FARMSV2_LABEL, OUTPUT_FARMV2_CONTRACTS_FILE)


def pause_farm_contracts(_):
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
        data_fetcher = FarmContractDataFetcher(Address.from_bech32(farm_address), network_providers.proxy.url)
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


def pause_farm_contract(args: Any):
    """Pause farm contract"""

    farm_address = args.address
    if not farm_address:
        print("Missing required arguments!")
        return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    print(f"Pausing farm contract {farm_address} ...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    data_fetcher = FarmContractDataFetcher(Address.new_from_bech32(farm_address), network_providers.proxy.url)
    contract_state = data_fetcher.get_data("getState")
    contract = FarmContract("", "", "", farm_address, FarmContractVersion.V2Boosted)
    if contract_state != 0:
        tx_hash = contract.pause(dex_owner, network_providers.proxy)
        if not network_providers.check_simple_tx_status(tx_hash, f"pause farm contract: {farm_address}"):
            if not get_user_continue():
                return
    else:
        print(f"Contract {farm_address} already inactive. Current state: {contract_state}")


def resume_farm_contracts(_):
    """Resume all farms"""

    print("Resuming farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
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


def resume_farm_contract(args: Any):
    """Resume farm contract"""

    farm_address = args.address

    if not farm_address:
        print("Missing required arguments!")
        return

    print(f"Resuming farm {farm_address} ...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              " Cannot proceed safely without altering initial state.")
        return

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if farm_address not in contract_states:
        print(f"Contract {farm_address} wasn't touched for no available initial state!")
        return
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


def upgrade_farmv2_contracts(args: Any):
    """Upgrade all v2 farms"""

    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v2_addresses()

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = config.FARM_V3_BYTECODE_PATH

    print(f"Upgrading {len(all_addresses)} boosted farm contracts...")
    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract: FarmContract
        contract = retrieve_farm_by_address(address)

        if compare_states:
            print("Fetching contract state before upgrade...")
            fetch_contracts_states("pre", network_providers, [address], FARMSV2_LABEL)

            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy,
                                            bytecode_path,
                                            [], True)

        if not network_providers.check_simple_tx_status(tx_hash, f"upgrade farm v2 contract: {address}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        if compare_states:
            fetch_new_and_compare_contract_states(FARMSV2_LABEL, address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

        count += 1


def upgrade_farmv2_contract(args: Any):
    """Upgrade farm v2 contract by address"""

    compare_states = args.compare_states
    farm_address = args.address

    if not farm_address:
        print("Missing required arguments!")
        return

    print(f"Upgrading farm contract: {farm_address}")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    contract = retrieve_farm_by_address(farm_address)

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = config.FARM_V3_BYTECODE_PATH

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print("Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [farm_address], FARMSV2_LABEL)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy,
                                        bytecode_path,
                                        [], True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade farm v2 contract: {farm_address}"):
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    if compare_states:
        fetch_new_and_compare_contract_states(FARMSV2_LABEL, farm_address, network_providers)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return


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


def replace_v2_ownership(args: Any):
    old_owner = args.old_owner
    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    all_addresses = get_all_farm_v2_addresses()
    cleaned_address = Address.new_from_bech32(old_owner).to_bech32()   # pass it through the Address class to check if it's valid

    print(f"Searching farm ownership for {cleaned_address}...")

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V2Boosted)
        data_fetcher = FarmContractDataFetcher(Address.new_from_bech32(address), network_providers.proxy.url)

        permissions = data_fetcher.get_data("getPermissions", [Address.new_from_bech32(cleaned_address).get_public_key()])
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


def update_boosted_factors(_):
    """Update boosted factors for all farms"""

    print("Updating boosted factors for all farms...")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    farm_addresses = get_all_farm_v2_addresses()

    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        contract = FarmContract("", "", "", farm_address, FarmContractVersion.V2Boosted)
        tx_hash = contract.set_boosted_yields_factors(dex_owner, network_providers.proxy,
                                                      [2, 1, 0, 1, 1000])
        if not network_providers.check_simple_tx_status(tx_hash, f"set boosted yields for farm contract: {farm_address}"):
            if not get_user_continue():
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
