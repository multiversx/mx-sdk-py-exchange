import binascii
import json
import sys, os
import time

import requests
from argparse import ArgumentParser
from typing import List

from context import Context
from contracts.pair_contract import PairContract
from ported_arrows.AutomaticTests.ElasticIndexer import ElasticIndexer
from ported_arrows.AutomaticTests.ProxyExtension import ProxyExtension
from contracts.contract_identities import RouterContractVersion, PairContractVersion, \
    StakingContractVersion, ProxyContractVersion, FarmContractVersion, MetaStakingContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from contracts.farm_contract import FarmContract
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.locked_asset_contract import LockedAssetContract
from contracts.metastaking_contract import MetaStakingContract
from contracts.staking_contract import StakingContract
from tools.account_state import get_account_keys_online, report_key_files_compare
from utils.contract_retrievers import retrieve_router_by_address, retrieve_pair_by_address, \
    retrieve_staking_by_address, retrieve_proxy_staking_by_address, retrieve_farm_by_address, \
    retrieve_simple_lock_energy_by_address, retrieve_locked_asset_factory_by_address
from utils.contract_data_fetchers import RouterContractDataFetcher, PairContractDataFetcher, \
    StakingContractDataFetcher, FarmContractDataFetcher
from utils.utils_tx import NetworkProviders
from utils.utils_chain import base64_to_hex, Account
from utils.utils_generic import log_step_fail
import config
from multiversx_sdk_cli.accounts import Address
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider
from pathlib import Path

PROXY = config.DEFAULT_PROXY
API = config.DEFAULT_API
GRAPHQL = config.GRAPHQL

CONTEXT = Context()

PROXY_DEX_CONTRACT = CONTEXT.get_contracts(config.PROXIES_V2)[0].address
LOCKED_ASSET_FACTORY_CONTRACT = CONTEXT.get_contracts(config.LOCKED_ASSETS)[0].address
ROUTER_CONTRACT = CONTEXT.get_contracts(config.ROUTER_V2)[0].address
FEES_COLLECTOR_CONTRACT = CONTEXT.get_contracts(config.FEES_COLLECTORS)[0].address
ENERGY_CONTRACT = CONTEXT.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
DEX_OWNER = config.DEX_OWNER_ADDRESS  # only needed for shadowfork

OUTPUT_FOLDER = config.UPGRADER_OUTPUT_FOLDER


LOCKED_ASSET_LABEL = "locked_asset"
PROXY_DEX_LABEL = "proxy_dex"
ROUTER_LABEL = "router"
TEMPLATE_PAIR_LABEL = "template_pair"
PAIRS_LABEL = "pairs"
STAKINGS_LABEL = "stakings"
METASTAKINGS_LABEL = "metastakings"
FARMSV13_LABEL = "farmsv13"
FARMSV12_LABEL = "farmsv12"
FARMSV2_LABEL = "farmsv2"

OUTPUT_PAIR_CONTRACTS_FILE = OUTPUT_FOLDER / "pairs_data.json"
OUTPUT_STAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "staking_data.json"
OUTPUT_METASTAKING_CONTRACTS_FILE = OUTPUT_FOLDER / "metastaking_data.json"
OUTPUT_FARMV13_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13_data.json"
OUTPUT_FARMV13LOCKED_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv13locked_data.json"
OUTPUT_FARMV12_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv12_data.json"
OUTPUT_FARMV2_CONTRACTS_FILE = OUTPUT_FOLDER / "farmv2_data.json"

OUTPUT_PAUSE_STATES = OUTPUT_FOLDER / "contract_pause_states.json"
SHADOWFORK = False if "shadowfork" not in PROXY else True


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--fetch-pairs", action="store_true", default=False)
    parser.add_argument("--fetch-stakings", action="store_true", default=False)
    parser.add_argument("--fetch-metastakings", action="store_true", default=False)
    parser.add_argument("--fetch-farms", action="store_true", default=False)
    parser.add_argument("--fetch-pause-state", action="store_true", default=False)
    parser.add_argument("--pause-pairs", action="store_true", default=False)
    parser.add_argument("--resume-pairs", action="store_true", default=False)
    parser.add_argument("--pause-farms", action="store_true", default=False)
    parser.add_argument("--resume-farms", action="store_true", default=False)
    parser.add_argument("--stop-produce-rewards-farms", action="store_true", default=False)
    parser.add_argument("--remove-penalty-farms", action="store_true", default=False)
    parser.add_argument("--pause-energy-factory", action="store_true", default=False)
    parser.add_argument("--resume-energy-factory", action="store_true", default=False)
    parser.add_argument("--pause-stakings", action="store_true", default=False)
    parser.add_argument("--resume-stakings", action="store_true", default=False)
    parser.add_argument("--upgrade-energy-factory", action="store_true", default=False)
    parser.add_argument("--upgrade-locked-asset", action="store_true", default=False)
    parser.add_argument("--upgrade-proxy-dex", action="store_true", default=False)
    parser.add_argument("--upgrade-template", action="store_true", default=False)
    parser.add_argument("--upgrade-router", action="store_true", default=False)
    parser.add_argument("--upgrade-pairs", action="store_true", default=False)
    parser.add_argument("--upgrade-farmsv12", action="store_true", default=False)
    parser.add_argument("--upgrade-farmsv13", action="store_true", default=False)
    parser.add_argument("--transfer-role-farmsv13", action="store_true", default=False)
    parser.add_argument("--upgrade-farmsv2", action="store_true", default=False)
    parser.add_argument("--clean-farmsv2-ownership", action="store_true", default=False)
    parser.add_argument("--upgrade-stakings", action="store_true", default=False)
    parser.add_argument("--upgrade-stakings-fix", action="store_true", default=False)
    parser.add_argument("--upgrade-metastakings", action="store_true", default=False)
    parser.add_argument("--deploy-pair-view", action="store_true", default=False)
    parser.add_argument("--set-pairs-in-fees-collector", action="store_true", default=False)
    parser.add_argument("--remove-pairs-from-fees-collector", action="store_true", default=False)
    parser.add_argument("--set-fees-collector-in-pairs", action="store_true", default=False)
    parser.add_argument("--update-fees-in-pairs", action="store_true", default=False)
    parser.add_argument("--enable-pair-creation", action="store_true", default=False)
    parser.add_argument("--disable-pair-creation", action="store_true", default=False)
    parser.add_argument("--fetch-state", required=False, default="")
    parser.add_argument("--compare-state", action="store_true", default=False)
    parser.add_argument("--clear-output-dir", action="store_true", default=False)
    args = parser.parse_args(cli_args)

    network_providers = NetworkProviders(API, PROXY)

    owner = CONTEXT.deployer_account
    owner.sync_nonce(network_providers.proxy)

    if args.fetch_pairs:
        fetch_and_save_pairs_from_chain(network_providers.proxy)
    if args.fetch_stakings:
        fetch_and_save_stakings_from_chain(network_providers.proxy)
    if args.fetch_metastakings:
        fetch_and_save_metastakings_from_chain(network_providers.proxy)
    if args.fetch_farms:
        fetch_and_save_farms_from_chain(network_providers.proxy)

    if args.fetch_pause_state:
        fetch_and_save_pause_state(network_providers)

    elif args.pause_energy_factory:
        pause_energy_factory(owner, network_providers)

    elif args.resume_energy_factory:
        resume_energy_factory(owner, network_providers)

    elif args.pause_pairs:
        pause_pair_contracts(owner, network_providers)

    elif args.pause_farms:
        pause_farm_contracts(owner, network_providers)

    elif args.pause_stakings:
        pause_staking_contracts(owner, network_providers)

    elif args.stop_produce_rewards_farms:
        stop_produce_rewards_farms(owner, network_providers)

    elif args.remove_penalty_farms:
        remove_penalty_farms(owner, network_providers)

    elif args.upgrade_energy_factory:
        upgrade_energy_factory(owner, network_providers)

    elif args.upgrade_locked_asset:
        upgrade_locked_asset_contracts(owner, network_providers)

    elif args.upgrade_proxy_dex:
        upgrade_proxy_dex_contracts(owner, network_providers)

    elif args.upgrade_router:
        upgrade_router_contract(owner, network_providers)

    elif args.upgrade_template:
        upgrade_template_pair_contract(owner, network_providers, args.compare_state)

    elif args.upgrade_pairs:
        upgrade_pair_contracts(owner, network_providers, args.compare_state)

    elif args.upgrade_farmsv12:
        upgrade_farmv12_contracts(owner, network_providers)

    elif args.upgrade_farmsv13:
        upgrade_farmv13_contracts(owner, network_providers)

    elif args.upgrade_farmsv2:
        upgrade_farmv2_contracts(owner, network_providers, args.compare_state)

    elif args.clean_farmsv2_ownership:
        clean_farmv2_ownership(owner, network_providers, args.compare_state)

    elif args.transfer_role_farmsv13:
        set_transfer_role_farmv13_contracts(owner, network_providers)

    elif args.upgrade_stakings:
        upgrade_staking_contracts(owner, network_providers, args.compare_state)

    elif args.upgrade_stakings_fix:
        upgrade_fix_staking_contracts(owner, network_providers)

    elif args.upgrade_metastakings:
        upgrade_metastaking_contracts(owner, network_providers, args.compare_state)

    elif args.deploy_pair_view:
        deploy_pair_view(owner, network_providers)

    elif args.set_pairs_in_fees_collector:
        set_pairs_in_fees_collector(owner, network_providers)

    elif args.remove_pairs_from_fees_collector:
        remove_pairs_from_fees_collector(owner, network_providers)

    elif args.set_fees_collector_in_pairs:
        set_fees_collector_in_pairs(owner, network_providers)

    elif args.resume_pairs:
        resume_pair_contracts(owner, network_providers)

    elif args.resume_farms:
        resume_farm_contracts(owner, network_providers)

    elif args.resume_stakings:
        resume_staking_contracts(owner, network_providers)

    elif args.enable_pair_creation:
        enable_pair_creation(owner, network_providers, True)

    elif args.disable_pair_creation:
        enable_pair_creation(owner, network_providers, False)

    elif args.update_fees_in_pairs:
        update_fees_percentage(owner, network_providers)

    if args.fetch_state:
        fetch_all_contracts_states(args.fetch_state, network_providers)

    if args.clear_output_dir:
        clear_output_dir()


def clear_output_dir():
    if os.path.exists(OUTPUT_FOLDER):
        for file in os.listdir(OUTPUT_FOLDER):
            os.remove(os.path.join(OUTPUT_FOLDER, file))


def save_wasm(code_data_hex: str, code_hash: str):
    binary_string = binascii.unhexlify(code_data_hex)

    if not os.path.exists(OUTPUT_FOLDER):
        os.mkdir(OUTPUT_FOLDER)

    output_file = os.path.join(OUTPUT_FOLDER, f"{code_hash}.wasm")
    with open(f"{output_file}", 'wb') as b:
        b.write(binary_string)

    print(f"Created wasm binary in: {output_file}")


def fetch_and_save_contracts(contract_addresses: list, contract_label: str, save_path: Path, proxy: ProxyNetworkProvider):
    pairs_data = {}
    for address in contract_addresses:
        contract_addr = Address(address)
        account_data = proxy.get_account(contract_addr)
        code_hash = base64_to_hex(account_data.code_hash)

        if code_hash not in pairs_data:
            pairs_data[code_hash] = {
                contract_label: [],
                "code": account_data.code.hex()
            }
            save_wasm(account_data.code.hex(), code_hash)
        pairs_data[code_hash][contract_label].append(contract_addr.bech32())

    with open(save_path, "w") as writer:
        json.dump(pairs_data, writer, indent=4)
        print(f"Dumped {contract_label} data in {save_path}")


def fetch_and_save_pairs_from_chain(proxy: ProxyNetworkProvider):
    router_data_fetcher = RouterContractDataFetcher(Address(ROUTER_CONTRACT), PROXY)
    registered_pairs = router_data_fetcher.get_data("getAllPairsManagedAddresses")
    fetch_and_save_contracts(registered_pairs, PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE, proxy)


def fetch_and_save_farms_from_chain(proxy: ProxyNetworkProvider):
    farmsv13 = get_farm_addresses_from_chain("v1.3")
    farmsv13locked = get_farm_addresses_locked_from_chain()
    farmsv12 = get_farm_addresses_from_chain("v1.2")
    farmsv2 = get_farm_addresses_from_chain("v2")
    fetch_and_save_contracts(farmsv13, FARMSV13_LABEL, OUTPUT_FARMV13_CONTRACTS_FILE, proxy)
    fetch_and_save_contracts(farmsv13locked, FARMSV13_LABEL, OUTPUT_FARMV13LOCKED_CONTRACTS_FILE, proxy)
    fetch_and_save_contracts(farmsv12, FARMSV12_LABEL, OUTPUT_FARMV12_CONTRACTS_FILE, proxy)
    fetch_and_save_contracts(farmsv2, FARMSV2_LABEL, OUTPUT_FARMV2_CONTRACTS_FILE, proxy)


def fetch_and_save_stakings_from_chain(proxy: ProxyNetworkProvider):
    stakings = get_staking_addresses_from_chain()
    fetch_and_save_contracts(stakings, STAKINGS_LABEL, OUTPUT_STAKING_CONTRACTS_FILE, proxy)


def fetch_and_save_metastakings_from_chain(proxy: ProxyNetworkProvider):
    metastakings = get_metastaking_addresses_from_chain()
    fetch_and_save_contracts(metastakings, METASTAKINGS_LABEL, OUTPUT_METASTAKING_CONTRACTS_FILE, proxy)


def run_graphql_query(uri, query):
    headers = {}
    statusCode = 200
    request = requests.post(uri, json={'query': query}, headers=headers)
    if request.status_code == statusCode:
        return request.json()
    else:
        raise Exception(f"Unexpected status code returned: {request.status_code}")


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


def get_staking_addresses_from_chain() -> list:
    query = """
        { stakingFarms { address } }
        """

    result = run_graphql_query(GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingFarms']:
        address_list.append(entry['address'])

    return address_list


def get_metastaking_addresses_from_chain() -> list:
    query = """
        { stakingProxies { address } }
        """

    result = run_graphql_query(GRAPHQL, query)

    address_list = []
    for entry in result['data']['stakingProxies']:
        address_list.append(entry['address'])

    return address_list


def get_saved_contracts_data(saved_file: Path) -> dict:
    if not os.path.exists(saved_file):
        raise FileNotFoundError("Saved contract data from mainnet not available!")

    print("Reading data...")
    with open(saved_file) as reader:
        contracts_data = json.load(reader)
    return contracts_data


def get_saved_contract_addresses(contract_label: str, saved_file: Path, searched_bytecode_hash: str = '') -> list:
    contracts_data = {}

    try:
        contracts_data = get_saved_contracts_data(saved_file)
    except FileNotFoundError as e:
        print(f"Error encountered for {contract_label}: {e}")

    contracts_addresses = []
    for bytecode_hash, contracts in contracts_data.items():
        if searched_bytecode_hash and bytecode_hash != searched_bytecode_hash:
            continue
        contracts_addresses.extend(contracts[contract_label])
    return contracts_addresses


def get_all_pair_addresses() -> list:
    return get_saved_contract_addresses(PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE)


def get_pairs_for_fees_addresses() -> list:
    query = """
            { pairs (limit:100) { 
             address
             lockedValueUSD
             type
             } }
            """

    result = run_graphql_query(GRAPHQL, query)
    pairs = result['data']['pairs']
    sorted_pairs = []

    for entry in pairs:
        if entry['type'] == 'Core' or entry['type'] == 'Ecosystem':
            sorted_pairs.append(entry['address'])

    return sorted_pairs


def get_all_farm_v13_addresses() -> list:
    return get_saved_contract_addresses(FARMSV13_LABEL, OUTPUT_FARMV13_CONTRACTS_FILE)


def get_all_farm_v13locked_addresses() -> list:
    return get_saved_contract_addresses(FARMSV13_LABEL, OUTPUT_FARMV13LOCKED_CONTRACTS_FILE)


def get_all_farm_v12_addresses() -> list:
    return get_saved_contract_addresses(FARMSV12_LABEL, OUTPUT_FARMV12_CONTRACTS_FILE)


def get_all_farm_v2_addresses() -> list:
    return get_saved_contract_addresses(FARMSV2_LABEL, OUTPUT_FARMV2_CONTRACTS_FILE)


def get_all_staking_addresses() -> list:
    return get_saved_contract_addresses(STAKINGS_LABEL, OUTPUT_STAKING_CONTRACTS_FILE)


def get_all_metastaking_addresses(searched_bytecode_hash: str = '') -> list:
    return get_saved_contract_addresses(METASTAKINGS_LABEL, OUTPUT_METASTAKING_CONTRACTS_FILE,
                                        searched_bytecode_hash)


def fetch_and_save_pause_state(network_providers: NetworkProviders):
    pair_addresses = get_all_pair_addresses()
    staking_addresses = get_all_staking_addresses()
    farm_addresses = get_all_farm_v2_addresses()

    contract_states = {}
    for pair_address in pair_addresses:
        data_fetcher = PairContractDataFetcher(Address(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[pair_address] = contract_state

    for staking_address in staking_addresses:
        data_fetcher = StakingContractDataFetcher(Address(staking_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[staking_address] = contract_state

    for farm_address in farm_addresses:
        data_fetcher = FarmContractDataFetcher(Address(farm_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[farm_address] = contract_state

    with open(OUTPUT_PAUSE_STATES, 'w') as writer:
        json.dump(contract_states, writer, indent=4)
        print(f"Dumped contract pause states in {OUTPUT_PAUSE_STATES}")


def pause_pair_contracts(dex_owner: Account, network_providers: NetworkProviders):
    pair_addresses = get_all_pair_addresses()
    router_contract = retrieve_router_by_address(ROUTER_CONTRACT)

    # pause all the pairs
    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        data_fetcher = PairContractDataFetcher(Address(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        if contract_state != 0:
            tx_hash = router_contract.pair_contract_pause(dex_owner, network_providers.proxy, pair_address)
            if not network_providers.check_simple_tx_status(tx_hash, f"pause pair contract: {pair_address}"):
                if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                    return
        else:
            print(f"Contract {pair_address} already inactive. Current state: {contract_state}")

        count += 1


def resume_pair_contracts(dex_owner: Account, network_providers: NetworkProviders):
    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found! Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES) as reader:
        contract_states = json.load(reader)

    pair_addresses = get_all_pair_addresses()
    router_contract = retrieve_router_by_address(ROUTER_CONTRACT)

    # pause all the pairs
    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        if pair_address not in contract_states:
            print(f"Contract {pair_address} wasn't touched for no available initial state!")
            continue
        # resume only if the pool was active
        if contract_states[pair_address] == 1:
            tx_hash = router_contract.pair_contract_resume(dex_owner, network_providers.proxy, pair_address)
            if not network_providers.check_simple_tx_status(tx_hash, f"resume pair contract: {pair_address}"):
                if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                    return
        elif contract_states[pair_address] == 2:
            pair_contract = PairContract("", "", PairContractVersion.V2, address=pair_address)
            tx_hash = pair_contract.set_active_no_swaps(dex_owner, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"set active no swaps on pair contract: {pair_address}"):
                if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                    return
        else:
            print(f"Contract {pair_address} wasn't touched because of initial state: {contract_states[pair_address]}")

        count += 1


def pause_staking_contracts(dex_owner: Account, network_providers: NetworkProviders):
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


def resume_staking_contracts(dex_owner: Account, network_providers: NetworkProviders):
    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found! Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES) as reader:
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


def pause_energy_factory(dex_owner: Account, network_providers: NetworkProviders):
    energy_contract = retrieve_simple_lock_energy_by_address(ENERGY_CONTRACT)

    tx_hash = energy_contract.pause(dex_owner, network_providers.proxy)
    network_providers.check_simple_tx_status(tx_hash, f"pause energy contract: {energy_contract}")


def resume_energy_factory(dex_owner: Account, network_providers: NetworkProviders):
    energy_contract = retrieve_simple_lock_energy_by_address(ENERGY_CONTRACT)

    tx_hash = energy_contract.resume(dex_owner, network_providers.proxy)
    network_providers.check_simple_tx_status(tx_hash, f"resume energy contract: {energy_contract}")


def pause_farm_contracts(dex_owner: Account, network_providers: NetworkProviders):
    farm_addresses = get_all_farm_v2_addresses()
    old_owner = CONTEXT.admin_account.address.bech32()

    print(f"Pausing {len(farm_addresses)} farm contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    # pause all the farms
    count = 1
    for farm_address in farm_addresses:
        print(f"Processing contract {count} / {len(farm_addresses)}: {farm_address}")
        data_fetcher = FarmContractDataFetcher(Address(farm_address), network_providers.proxy.url)

        # temporary solution for farms with old owner
        permissions = data_fetcher.get_data("getPermissions", [Address(old_owner).pubkey()])
        if permissions:
            owner_account = CONTEXT.admin_account
        else:
            owner_account = dex_owner

        contract_state = data_fetcher.get_data("getState")
        contract = FarmContract("", "", "", farm_address, FarmContractVersion.V2Boosted)
        if contract_state != 0:
            tx_hash = contract.pause(owner_account, network_providers.proxy)
            if not network_providers.check_simple_tx_status(tx_hash, f"pause farm contract: {farm_address}"):
                if not get_user_continue():
                    return
        else:
            print(f"Contract {farm_address} already inactive. Current state: {contract_state}")

        count += 1


def resume_farm_contracts(dex_owner: Account, network_providers: NetworkProviders):
    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found! Cannot proceed safely without altering initial state.")
        return

    with open(OUTPUT_PAUSE_STATES) as reader:
        contract_states = json.load(reader)

    farm_addresses = get_all_farm_v2_addresses()

    print(f"Resuming {len(farm_addresses)} farm contracts...")
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


def stop_produce_rewards_farms(dex_owner: Account, network_providers: NetworkProviders):
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


def remove_penalty_farms(dex_owner: Account, network_providers: NetworkProviders):
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


def upgrade_template_pair_contract(owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    router_data_fetcher = RouterContractDataFetcher(Address(ROUTER_CONTRACT), network_providers.proxy.url)
    template_pair_address = Address(router_data_fetcher.get_data("getPairTemplateAddress")).bech32()
    template_pair = retrieve_pair_by_address(template_pair_address)

    if compare_states:
        print(f"Fetching contract states before upgrade...")
        fetch_contracts_states("pre", network_providers, [template_pair_address], TEMPLATE_PAIR_LABEL)

        if not get_user_continue():
            return

    template_pair.version = PairContractVersion.V2
    args = [config.ZERO_CONTRACT_ADDRESS, config.ZERO_CONTRACT_ADDRESS,
            config.ZERO_CONTRACT_ADDRESS, 0, 0, config.ZERO_CONTRACT_ADDRESS]
    tx_hash = template_pair.contract_upgrade(owner, network_providers.proxy, config.PAIR_V2_BYTECODE_PATH, args)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade template pair contract: {template_pair_address}"):
        if not get_user_continue():
            return

    if compare_states:
        print(f"Fetching contract states before upgrade...")
        fetch_new_and_compare_contract_states(TEMPLATE_PAIR_LABEL, template_pair_address, network_providers)


def upgrade_router_contract(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    router_contract = retrieve_router_by_address(ROUTER_CONTRACT)
    router_data_fetcher = RouterContractDataFetcher(Address(ROUTER_CONTRACT), network_providers.proxy.url)
    template_pair_address = Address(router_data_fetcher.get_data("getPairTemplateAddress")).bech32()

    # change router version & upgrade router contract
    router_contract.version = RouterContractVersion.V2
    tx_hash = router_contract.contract_upgrade(dex_owner, network_providers.proxy, config.ROUTER_V2_BYTECODE_PATH,
                                               [template_pair_address])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade router contract {ROUTER_CONTRACT}"):
        return

    fetch_new_and_compare_contract_states(ROUTER_LABEL, ROUTER_CONTRACT, network_providers)


def upgrade_pair_contracts(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    router_contract = retrieve_router_by_address(ROUTER_CONTRACT)
    router_contract.version = RouterContractVersion.V2
    pair_addresses = get_all_pair_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address(pair_address), network_providers.proxy.url)
        total_fee_percentage = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percentage = pair_data_fetcher.get_data("getSpecialFee")
        existent_initial_liquidity_adder = pair_data_fetcher.get_data("getInitialLiquidtyAdder")
        initial_liquidity_adder = Address(existent_initial_liquidity_adder[2:]).bech32() if existent_initial_liquidity_adder else config.ZERO_CONTRACT_ADDRESS
        print(f"Initial liquidity adder: {initial_liquidity_adder}")

        if compare_states:
            print(f"Fetching contract state before upgrade...")
            fetch_contracts_states("pre", network_providers, [pair_address], PAIRS_LABEL)

            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        pair_contract.version = PairContractVersion.V2
        tx_hash = pair_contract.contract_upgrade_via_router(dex_owner, network_providers.proxy, router_contract,
                                                            [total_fee_percentage, special_fee_percentage,
                                                             initial_liquidity_adder])

        if not network_providers.check_simple_tx_status(tx_hash, f"upgrade pair contract: {pair_address}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return

        if compare_states:
            fetch_new_and_compare_contract_states(PAIRS_LABEL, pair_address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

        count += 1


def update_fees_percentage(dex_owner: Account, network_providers: NetworkProviders):
    pair_addresses = get_depositing_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address(pair_address), network_providers.proxy.url)
        total_fee_percentage = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percentage = 100

        pair_contract.version = PairContractVersion.V2
        tx_hash = pair_contract.set_fees_percents(dex_owner, network_providers.proxy,
                                                  [total_fee_percentage, special_fee_percentage])

        if not network_providers.check_complex_tx_status(tx_hash, f"set fees percentages: {pair_address}"):
            if not get_user_continue():
                return

        fetch_new_and_compare_contract_states(PAIRS_LABEL, pair_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_energy_factory(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    energy_contract = retrieve_simple_lock_energy_by_address(ENERGY_CONTRACT)
    locked_asset_contract = retrieve_locked_asset_factory_by_address(LOCKED_ASSET_FACTORY_CONTRACT)

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [energy_contract.address], "energy")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = energy_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                               config.SIMPLE_LOCK_ENERGY_BYTECODE_PATH,
                                               [locked_asset_contract.locked_asset, locked_asset_contract.address,
                                                0, [], []])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade energy contract: {energy_contract}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("energy", energy_contract.address, network_providers)


def upgrade_staking_contracts(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    staking_addresses = get_all_staking_addresses()
    if not staking_addresses:
        print("No staking contracts available!")
        return

    if compare_states:
        print(f"Fetching contracts states before upgrade...")
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


def upgrade_fix_staking_contracts(dex_owner: Account, network_providers: NetworkProviders):
    staking_addresses = get_all_staking_addresses()

    count = 1
    for staking_address in staking_addresses:
        print(f"Processing contract {count} / {len(staking_addresses)}: {staking_address}")
        staking_contract = retrieve_staking_by_address(staking_address, StakingContractVersion.V2)

        print(f"Processing contract for: {staking_contract.farming_token}")
        block_number = input(f"Previous upgrade block number:\n")
        new_supply = input(f"New farm token supply:\n")

        tx_hash = staking_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                    config.STAKING_V2_BYTECODE_PATH,
                                                    [block_number, new_supply, dex_owner.address.bech32()],
                                                    False)

        if not network_providers.check_complex_tx_status(tx_hash, f"upgrade staking contract: {staking_address}"):
            if not get_user_continue():
                return

        fetch_new_and_compare_contract_states(STAKINGS_LABEL, staking_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def upgrade_metastaking_contracts(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    metastaking_addresses = get_all_metastaking_addresses('56468a6ae726693a71edcf96cf44673466dd980412388e1e4b073a0b4ee592d7')
    if not metastaking_addresses:
        print("No metastaking contracts available!")
        return

    if compare_states:
        print(f"Fetching contracts states before upgrade...")
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


def upgrade_farmv12_contracts(dex_owner: Account, network_providers: NetworkProviders):
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


def upgrade_farmv13_contracts(dex_owner: Account, network_providers: NetworkProviders):
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


def upgrade_farmv2_contracts(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
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


def clean_farmv2_ownership(dex_owner: Account, network_providers: NetworkProviders, compare_states: bool = False):
    all_addresses = get_all_farm_v2_addresses()
    cleaned_address = CONTEXT.admin_account.address.bech32()

    print(f"Searching farm ownership for {cleaned_address}...")

    count = 1
    for address in all_addresses:
        print(f"Processing contract {count} / {len(all_addresses)}: {address}")
        contract = FarmContract("", "", "", address, FarmContractVersion.V2Boosted)
        data_fetcher = FarmContractDataFetcher(Address(address), network_providers.proxy.url)

        permissions = data_fetcher.get_data("getPermissions", [Address(cleaned_address).pubkey()])
        if not permissions:
            continue
        print(f"Found permissions {permissions} for {cleaned_address} in contract {address}. Remove them?")
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


def deploy_pair_view(dex_owner: Account, network_providers: NetworkProviders):
    print(f"Deploying pair view contract...")
    pair_view_contract = PairContract("", "", PairContractVersion.V1)

    tx_hash, address = pair_view_contract.view_contract_deploy(dex_owner, network_providers.proxy,
                                                               config.PAIR_VIEW_BYTECODE_PATH,
                                                               [config.ZERO_CONTRACT_ADDRESS])

    if not network_providers.check_complex_tx_status(tx_hash, f"deploy view contract: {address}"):
        if not get_user_continue():
            return


def enable_pair_creation(dex_owner: Account, network_providers: NetworkProviders, enable: bool):
    action = "enable" if enable else "disable"
    print(f"{action} pair creation...")
    router_contract = retrieve_router_by_address(ROUTER_CONTRACT)

    tx_hash = router_contract.set_pair_creation_enabled(dex_owner, network_providers.proxy, [enable])

    if not network_providers.check_simple_tx_status(tx_hash, f"{action} pair creation"):
        if not get_user_continue():
            return


def set_transfer_role_farmv13_contracts(dex_owner: Account, network_providers: NetworkProviders):
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


def upgrade_locked_asset_contracts(dex_owner: Account, network_providers: NetworkProviders):
    print(f"Processing contract {LOCKED_ASSET_FACTORY_CONTRACT}")
    locked_asset_contract = LockedAssetContract("", "", LOCKED_ASSET_FACTORY_CONTRACT)

    tx_hash = locked_asset_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                     config.LOCKED_ASSET_FACTORY_BYTECODE_PATH, [],
                                                     no_init=True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade locked asset factory contract: "
                                                              f"{LOCKED_ASSET_FACTORY_CONTRACT}"):
        if not get_user_continue():
            return

    fetch_new_and_compare_contract_states(LOCKED_ASSET_LABEL, LOCKED_ASSET_FACTORY_CONTRACT, network_providers)

    if not get_user_continue():
        return


def upgrade_proxy_dex_contracts(dex_owner: Account, network_providers: NetworkProviders):
    print(f"Processing contract {PROXY_DEX_CONTRACT}")
    proxy_dex_contract = DexProxyContract([], "", ProxyContractVersion.V1, address=PROXY_DEX_CONTRACT)

    tx_hash = proxy_dex_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                  config.PROXY_BYTECODE_PATH, [],
                                                  no_init=True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade proxy-dex contract: "
                                                              f"{PROXY_DEX_CONTRACT}"):
        if not get_user_continue():
            return

    # fetch_new_and_compare_contract_states(PROXY_DEX_LABEL, PROXY_DEX_CONTRACT, network_providers)

    if not get_user_continue():
        return


def set_pairs_in_fees_collector(dex_owner: Account, network_providers: NetworkProviders):
    pair_addresses = get_all_pair_addresses()
    fees_collector = FeesCollectorContract(FEES_COLLECTOR_CONTRACT)

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)

        # add pair address in fees collector
        _ = fees_collector.add_known_contracts(dex_owner, network_providers.proxy,
                                               [pair_address])
        _ = fees_collector.add_known_tokens(dex_owner, network_providers.proxy,
                                            [f"str:{pair_contract.firstToken}",
                                             f"str:{pair_contract.secondToken}"])

        if not get_user_continue():
            return

        count += 1


def remove_pairs_from_fees_collector(dex_owner: Account, network_providers: NetworkProviders):
    fees_collector = FeesCollectorContract(FEES_COLLECTOR_CONTRACT)
    pair_addresses = get_all_pair_addresses()
    depositing_addresses = get_depositing_addresses()

    whitelisted_tokens = []

    print("Aligning planets...")
    for address in depositing_addresses:
        if address in pair_addresses:
            pair_addresses.remove(address)

        pair_contract = retrieve_pair_by_address(address)
        whitelisted_tokens.append(pair_contract.firstToken)
        whitelisted_tokens.append(pair_contract.secondToken)

    removable_addresses = []
    removable_tokens = []
    for pair_address in pair_addresses:
        pair_contract = retrieve_pair_by_address(pair_address)

        removable_addresses.append(pair_address)
        if pair_contract.firstToken not in whitelisted_tokens and pair_contract.firstToken not in removable_tokens:
            removable_tokens.append(pair_contract.firstToken)
        if pair_contract.secondToken not in whitelisted_tokens and pair_contract.secondToken not in removable_tokens:
            removable_tokens.append(pair_contract.secondToken)

    print(f"Will remove {len(removable_addresses)} pairs from fees collector.")
    print(f"Will remove {len(removable_tokens)} tokens from fees collector.")
    print(removable_tokens)
    if not get_user_continue():
        return

    count = 1
    # remove pair address in fees collector
    for address in removable_addresses:
        print(f"Processing contract {count} / {len(removable_addresses)}")
        tx_hash = fees_collector.remove_known_contracts(dex_owner, network_providers.proxy, [address])
        if not network_providers.check_simple_tx_status(tx_hash, f"remove pair addresses"):
            if not get_user_continue():
                return
        count += 1

    count = 1
    # remove token in fees collector
    for token in removable_tokens:
        print(f"Processing token {count} / {len(removable_tokens)}")
        tx_hash = fees_collector.remove_known_tokens(dex_owner, network_providers.proxy, [f"str:{token}"])
        if not network_providers.check_simple_tx_status(tx_hash, f"remove token"):
            if not get_user_continue():
                return
        count += 1

    if not get_user_continue():
        return


def get_depositing_addresses() -> list:
    pair_addresses = get_pairs_for_fees_addresses()

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found! Cannot proceed due to risk of whitelisting inactive pairs.")
        return []

    with open(OUTPUT_PAUSE_STATES) as reader:
        contract_states = json.load(reader)

    whitelist = []
    print(f"Whitelisted pairs:")
    # filter whitelistable contracts
    for pair_address in pair_addresses:
        if pair_address not in contract_states:
            print(f"Contract {pair_address} will be skipped. No available initial pause state!")
            continue
        # whitelist only if pool was active
        if contract_states[pair_address] == 1:
            whitelist.append(pair_address)
            pair_contract = retrieve_pair_by_address(pair_address)
            print(f"{pair_contract.firstToken} / {pair_contract.secondToken}")

    print(f"Number of contracts: {len(whitelist)}")

    if not get_user_continue():
        return []

    return whitelist


def set_fees_collector_in_pairs(dex_owner: Account, network_providers: NetworkProviders):
    fees_collector = FeesCollectorContract(FEES_COLLECTOR_CONTRACT)
    whitelist = get_depositing_addresses()

    if not whitelist:
        return

    count = 1
    for pair_address in whitelist:
        print(f"Processing contract {count} / {len(whitelist)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)
        fees_cut = 50000

        # setup fees collector in pair
        tx_hash = pair_contract.add_fees_collector(dex_owner, network_providers.proxy,
                                                   [fees_collector.address, fees_cut])
        _ = network_providers.check_simple_tx_status(tx_hash, "set fees collector in pair")

        if not get_user_continue():
            return

        count += 1


def fetch_contracts_states(prefix: str, network_providers: NetworkProviders, contract_addresses: List[str], label: str):
    for contract_address in contract_addresses:
        filename = get_contract_save_name(label, contract_address, prefix)
        get_account_keys_online(contract_address, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))


def fetch_contract_state(contract_address: str, save_name: str, network_providers: NetworkProviders):
    get_account_keys_online(contract_address, network_providers.proxy.url,
                            with_save_in=str(OUTPUT_FOLDER / f"{save_name}.json"))


def fetch_all_contracts_states(prefix: str, network_providers: NetworkProviders):
    # get locked asset state
    if LOCKED_ASSET_FACTORY_CONTRACT:
        filename = get_contract_save_name(LOCKED_ASSET_LABEL, LOCKED_ASSET_FACTORY_CONTRACT, prefix)
        get_account_keys_online(LOCKED_ASSET_FACTORY_CONTRACT, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))
    else:
        log_step_fail(f"Locked asset factory address not available. No state saved for this!")

    # get proxy dex state
    # filename = get_contract_save_name(PROXY_DEX_LABEL, PROXY_DEX_CONTRACT, prefix)
    # get_account_keys_online(PROXY_DEX_CONTRACT, network_providers.proxy.url,
    #                         with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))

    # get router state
    if ROUTER_CONTRACT:
        filename = get_contract_save_name(ROUTER_LABEL, ROUTER_CONTRACT, prefix)
        get_account_keys_online(ROUTER_CONTRACT, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))
    else:
        log_step_fail(f"Router address not available. No state saved for this!")

    # get template state
    router_data_fetcher = RouterContractDataFetcher(Address(ROUTER_CONTRACT), network_providers.proxy.url)
    template_pair_address = Address(router_data_fetcher.get_data("getPairTemplateAddress")).bech32()
    filename = get_contract_save_name(TEMPLATE_PAIR_LABEL, template_pair_address, prefix)
    get_account_keys_online(template_pair_address, network_providers.proxy.url,
                            with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))

    # get pairs contract states
    pair_addresses = get_all_pair_addresses()
    fetch_contracts_states(prefix, network_providers, pair_addresses, PAIRS_LABEL)

    # get staking states
    staking_addresses = get_all_staking_addresses()
    fetch_contracts_states(prefix, network_providers, staking_addresses, STAKINGS_LABEL)

    # get metastaking states
    metastaking_addresses = get_all_metastaking_addresses()
    fetch_contracts_states(prefix, network_providers, metastaking_addresses, METASTAKINGS_LABEL)

    # get farm v12 states
    farm_v12_addresses = get_all_farm_v12_addresses()
    fetch_contracts_states(prefix, network_providers, farm_v12_addresses, FARMSV12_LABEL)

    # get farm v13 states
    farm_v13_addresses = get_all_farm_v13_addresses()
    fetch_contracts_states(prefix, network_providers, farm_v13_addresses, FARMSV13_LABEL)


def get_contract_save_name(contract_type: str, address: str, prefix: str):
    return f"{prefix}_{contract_type}_{address}"


def fetch_new_and_compare_contract_states(contract_type: str, contract_address, network_providers: NetworkProviders):
    old_state_filename = get_contract_save_name(contract_type, contract_address, "pre")
    new_state_filename = get_contract_save_name(contract_type, contract_address, "mid")
    fetch_contract_state(contract_address, new_state_filename, network_providers)
    report_key_files_compare(str(OUTPUT_FOLDER), old_state_filename, new_state_filename, True)


def get_user_continue(force_yes: bool = False) -> bool:
    if force_yes:
        return True

    typed = input(f"Continue? y/n\n")
    while typed != "y" and typed != "n":
        typed = input(f"Wrong choice. Continue? y/n\n")
    if typed == "n":
        return False
    return True


if __name__ == "__main__":
    main(sys.argv[1:])
