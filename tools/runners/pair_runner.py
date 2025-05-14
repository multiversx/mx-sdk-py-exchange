from argparse import ArgumentParser
from typing import Any
from multiversx_sdk import Address
from context import Context
from contracts.contract_identities import PairContractVersion, RouterContractVersion
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.pair_contract import PairContract
from contracts.router_contract import RouterContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, \
    get_user_continue, run_graphql_query, fetch_and_save_contracts, get_saved_contract_addresses
from tools.runners.common_runner import add_upgrade_all_command
from utils.contract_data_fetchers import PairContractDataFetcher, RouterContractDataFetcher
from utils.utils_tx import NetworkProviders

import config
import json
import os


PAIRS_LABEL = "pairs"
OUTPUT_PAIR_CONTRACTS_FILE = OUTPUT_FOLDER / "pairs_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for pair commands"""
    group_parser = subparsers.add_parser('pairs', help='pairs group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='pairs contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_all_command(contract_group, upgrade_pair_contracts)

    command_parser = contract_group.add_parser('fetch-all', help='fetch all contracts command')
    command_parser.set_defaults(func=fetch_and_save_pairs_from_chain)

    command_parser = contract_group.add_parser('pause-all', help='pause all contracts command')
    command_parser.set_defaults(func=pause_pair_contracts)

    command_parser = contract_group.add_parser('resume-all', help='resume all contracts command')
    command_parser.set_defaults(func=resume_pair_contracts)

    command_parser = contract_group.add_parser('set-fees-collector', help='set fees collector in all contracts command')
    command_parser.set_defaults(func=set_fees_collector_in_pairs)

    command_parser = contract_group.add_parser('remove-from-fees-collector', help='remove fees collector from all contracts command')
    command_parser.set_defaults(func=remove_pairs_from_fees_collector)

    command_parser = contract_group.add_parser('update-fees', help='update fees percentage in all contracts command')
    command_parser.set_defaults(func=update_fees_percentage)

    return group_parser


def fetch_and_save_pairs_from_chain(_):
    """Fetch and save pairs from chain"""

    print('fetch_and_save_pairs_from_chain')

    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address
    print(f"Router address: {router_address}")
    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), PROXY)
    registered_pairs = router_data_fetcher.get_data("getAllPairsManagedAddresses")
    fetch_and_save_contracts(registered_pairs, PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE)


def pause_pair_contracts(_):
    """Pause pair contracts"""

    print("Pausing pair contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    pair_addresses = get_all_pair_addresses()
    router_contract = RouterContract.load_contract_by_address(router_address)

    # pause all the pairs
    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        if contract_state != 0:
            tx_hash = router_contract.pair_contract_pause(dex_owner, network_providers.proxy, pair_address)
            print(tx_hash)
            # if not network_providers.check_simple_tx_status(tx_hash, f"pause pair contract: {pair_address}"):
            #     if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            #         return
        else:
            print(f"Contract {pair_address} already inactive. Current state: {contract_state}")

        count += 1


def resume_pair_contracts(_):
    """Resume pair contracts"""

    print("Resuming pair contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              "Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    pair_addresses = get_all_pair_addresses()
    router_contract = RouterContract.load_contract_by_address(router_address)

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
            print(f"Contract {pair_address} wasn't touched" \
                  " because of initial state: {contract_states[pair_address]}")

        count += 1


def upgrade_pair_contracts(args: Any):
    """Upgrade pair contracts"""

    compare_states = args.compare_states

    print(f"Upgrading pair contracts with compare states: {compare_states}")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    router_contract = RouterContract.load_contract_by_address(router_contract)
    router_contract.version = RouterContractVersion.V2
    pair_addresses = get_all_pair_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = PairContract.load_contract_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address),
                                                    network_providers.proxy.url)
        total_fee_percentage = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percentage = pair_data_fetcher.get_data("getSpecialFee")
        existent_initial_liquidity_adder = pair_data_fetcher.get_data("getInitialLiquidtyAdder")
        initial_liquidity_adder = \
            Address.new_from_bech32(existent_initial_liquidity_adder[2:]).to_bech32() \
            if existent_initial_liquidity_adder else config.ZERO_CONTRACT_ADDRESS
        print(f"Initial liquidity adder: {initial_liquidity_adder}")

        if compare_states:
            print("Fetching contract state before upgrade...")
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


def set_fees_collector_in_pairs(_):
    """Set fees collector in pairs"""

    print("Setting fees collector in all pairs")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    fees_collector = FeesCollectorContract(context.get_contracts(config.FEES_COLLECTORS)[0].address)
    whitelist = get_depositing_addresses()

    if not whitelist:
        return

    count = 1
    for pair_address in whitelist:
        print(f"Processing contract {count} / {len(whitelist)}: {pair_address}")
        pair_contract = PairContract.load_contract_by_address(pair_address)
        fees_cut = 50000

        # setup fees collector in pair
        tx_hash = pair_contract.add_fees_collector(dex_owner, network_providers.proxy,
                                                   [fees_collector.address, fees_cut])
        _ = network_providers.check_simple_tx_status(tx_hash, "set fees collector in pair")

        if not get_user_continue():
            return

        count += 1


def remove_pairs_from_fees_collector(_):
    """Remove pairs from fees collector"""

    print("Removing pairs from fees collector")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    fees_collector = FeesCollectorContract(context.get_contracts(config.FEES_COLLECTORS)[0].address)
    pair_addresses = get_all_pair_addresses()
    depositing_addresses = get_depositing_addresses()

    whitelisted_tokens = []

    print("Aligning planets...")
    for address in depositing_addresses:
        if address in pair_addresses:
            pair_addresses.remove(address)

        pair_contract = PairContract.load_contract_by_address(address)
        whitelisted_tokens.append(pair_contract.firstToken)
        whitelisted_tokens.append(pair_contract.secondToken)

    removable_addresses = []
    removable_tokens = []
    for pair_address in pair_addresses:
        pair_contract = PairContract.load_contract_by_address(pair_address)

        removable_addresses.append(pair_address)
        if pair_contract.firstToken not in whitelisted_tokens and \
           pair_contract.firstToken not in removable_tokens:
            removable_tokens.append(pair_contract.firstToken)
        if pair_contract.secondToken not in whitelisted_tokens and \
           pair_contract.secondToken not in removable_tokens:
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
        tx_hash = fees_collector.remove_known_contracts(dex_owner,
                                                        network_providers.proxy, [address])
        if not network_providers.check_simple_tx_status(tx_hash, "remove pair addresses"):
            if not get_user_continue():
                return
        count += 1

    count = 1
    # remove token in fees collector
    for token in removable_tokens:
        print(f"Processing token {count} / {len(removable_tokens)}")
        tx_hash = fees_collector.remove_known_tokens(dex_owner,
                                                     network_providers.proxy, [f"str:{token}"])
        if not network_providers.check_simple_tx_status(tx_hash, "remove token"):
            if not get_user_continue():
                return
        count += 1

    if not get_user_continue():
        return


def update_fees_percentage(_):
    """Update fees percentage"""

    print("Updating fees percentage")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    pair_addresses = get_depositing_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = PairContract.load_contract_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address),
                                                    network_providers.proxy.url)
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


def deploy_pair_view():
    """Deploy pair view contract"""

    print("Deploying pair view contract...")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    pair_view_contract = PairContract("", "", PairContractVersion.V1)

    tx_hash, address = pair_view_contract.view_contract_deploy(dex_owner, network_providers.proxy,
                                                               config.PAIR_VIEW_BYTECODE_PATH,
                                                               [config.ZERO_CONTRACT_ADDRESS])

    if not network_providers.check_complex_tx_status(tx_hash, f"deploy view contract: {address}"):
        if not get_user_continue():
            return


def get_depositing_addresses() -> list:
    """Get depositing addresses"""

    pair_addresses = get_pairs_for_fees_addresses()

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              "Cannot proceed due to risk of whitelisting inactive pairs.")
        return []

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    whitelist = []
    print("Whitelisted pairs:")
    # filter whitelistable contracts
    for pair_address in pair_addresses:
        if pair_address not in contract_states:
            print(f"Contract {pair_address} will be skipped. No available initial pause state!")
            continue
        # whitelist only if pool was active
        if contract_states[pair_address] == 1:
            whitelist.append(pair_address)
            pair_contract = PairContract.load_contract_by_address(pair_address)
            print(f"{pair_contract.firstToken} / {pair_contract.secondToken}")

    print(f"Number of contracts: {len(whitelist)}")

    if not get_user_continue():
        return []

    return whitelist


def get_pairs_for_fees_addresses() -> list:
    """Get pairs for fees addresses"""

    query = """
            { pairs (limit:100) {
             address
             lockedValueUSD
             type
             } }
            """

    result = run_graphql_query(config.GRAPHQL, query)
    pairs = result['data']['pairs']
    sorted_pairs = []

    for entry in pairs:
        if entry['type'] == 'Core' or entry['type'] == 'Ecosystem':
            sorted_pairs.append(entry['address'])

    return sorted_pairs


def get_all_pair_addresses() -> list:
    """Get all pair addresses"""

    return get_saved_contract_addresses(PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE)
