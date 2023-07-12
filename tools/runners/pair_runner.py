from argparse import ArgumentParser
import json
import os
from common import fetch_and_save_contracts, get_saved_contract_addresses
from multiversx_sdk_cli.accounts import Address
from context import Context
from contracts.contract_identities import PairContractVersion, RouterContractVersion
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.pair_contract import PairContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, \
    get_user_continue, run_graphql_query
from utils.contract_data_fetchers import PairContractDataFetcher, RouterContractDataFetcher
from utils.contract_retrievers import retrieve_router_by_address, retrieve_pair_by_address, \
    retrieve_staking_by_address, retrieve_proxy_staking_by_address
from utils.utils_chain import Account
from utils.utils_tx import NetworkProviders
import config


PAIRS_LABEL = "pairs"
OUTPUT_PAIR_CONTRACTS_FILE = OUTPUT_FOLDER / "pairs_data.json"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')

    mutex = parser.add_mutually_exclusive_group()

    mutex.add_argument('--fetch-all', action='store_true',
                        help='fetch pairs from blockchain')
    mutex.add_argument('--pause-all', action='store_true', help='pause all pairs')
    mutex.add_argument('--resume-all', action='store_true', help='resume all pairs')
    mutex.add_argument('--upgrade-all', action='store_true', help='upgrade all pairs')
    mutex.add_argument('--set-fees-collector', action='store_true',
                       help='set fees collector for all pairs')
    mutex.add_argument('--remove-from-fees-collector', action='store_true',
                       help='remove fees collector from all pairs')
    mutex.add_argument('--update fees', action='store_true',
                       help='update fees percentage in all pairs')


def handle_command(args):
    """Handle the command"""

    if args.fetch_all:
        fetch_and_save_pairs_from_chain()
    elif args.pause_all:
        pause_pair_contracts()
    elif args.resume_all:
        resume_pair_contracts()
    elif args.upgrade_all:
        upgrade_pair_contracts(args.compare_states)
    elif args.set_fees_collector:
        set_fees_collector_in_pairs()
    elif args.remove_from_fees_collector:
        remove_pairs_from_fees_collector()
    elif args.update_fees:
        update_fees_percentage()
    else:
        print('invalid arguments')


def fetch_and_save_pairs_from_chain():
    """Fetch and save pairs from chain"""

    print('fetch_and_save_pairs_from_chain')
    return

    network_providers = NetworkProviders(API, PROXY)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    router_data_fetcher = RouterContractDataFetcher(Address(router_address), PROXY)
    registered_pairs = router_data_fetcher.get_data("getAllPairsManagedAddresses")
    fetch_and_save_contracts(registered_pairs, PAIRS_LABEL,
        OUTPUT_PAIR_CONTRACTS_FILE, network_providers.proxy)


def pause_pair_contracts():
    """Pause pair contracts"""

    print("Pausing pair contracts")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    pair_addresses = get_all_pair_addresses()
    router_contract = retrieve_router_by_address(router_address)

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


def resume_pair_contracts():
    """Resume pair contracts"""

    print("Resuming pair contracts")
    return
    
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!" \
              "Cannot proceed safely without altering initial state.")

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    pair_addresses = get_all_pair_addresses()
    router_contract = retrieve_router_by_address(router_address)

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


def upgrade_pair_contracts(compare_states: bool = False):
    """Upgrade pair contracts"""

    print(f"Upgrading pair contracts with compare states: {compare_states}")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    router_contract = retrieve_router_by_address(router_address)
    router_contract.version = RouterContractVersion.V2
    pair_addresses = get_all_pair_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address(pair_address),
                                                    network_providers.proxy.url)
        total_fee_percentage = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percentage = pair_data_fetcher.get_data("getSpecialFee")
        existent_initial_liquidity_adder = pair_data_fetcher.get_data("getInitialLiquidtyAdder")
        initial_liquidity_adder = \
            Address(existent_initial_liquidity_adder[2:]).bech32() \
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


def set_fees_collector_in_pairs():
    """Set fees collector in pairs"""

    print("Setting fees collector in all pairs")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

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
        pair_contract = retrieve_pair_by_address(pair_address)
        fees_cut = 50000

        # setup fees collector in pair
        tx_hash = pair_contract.add_fees_collector(dex_owner, network_providers.proxy,
                                                   [fees_collector.address, fees_cut])
        _ = network_providers.check_simple_tx_status(tx_hash, "set fees collector in pair")

        if not get_user_continue():
            return

        count += 1


def remove_pairs_from_fees_collector():
    """Remove pairs from fees collector"""

    print("Removing pairs from fees collector")
    return

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

        pair_contract = retrieve_pair_by_address(address)
        whitelisted_tokens.append(pair_contract.firstToken)
        whitelisted_tokens.append(pair_contract.secondToken)

    removable_addresses = []
    removable_tokens = []
    for pair_address in pair_addresses:
        pair_contract = retrieve_pair_by_address(pair_address)

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


def update_fees_percentage():
    """Update fees percentage"""

    print("Updating fees percentage")
    return

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    pair_addresses = get_depositing_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = retrieve_pair_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address(pair_address),
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
        print("Contract initial states not found!" \
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
            pair_contract = retrieve_pair_by_address(pair_address)
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
