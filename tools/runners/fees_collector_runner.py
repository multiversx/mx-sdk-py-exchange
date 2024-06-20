import config
from argparse import ArgumentParser
from context import Context
from contracts.fees_collector_contract import FeesCollectorContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.pair_runner import get_all_pair_addresses
from utils.contract_retrievers import retrieve_pair_by_address

from utils.utils_tx import NetworkProviders


FEES_COLLECTOR_LABEL = 'fees_collector'

def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--upgrade', action='store_true', help='upgrade fees collector')
    mutex.add_argument('--set-pairs', action='store_true', help='set pairs in fees collector')


def handle_command(args):
    """Handle the command passed to the runner"""

    if args.upgrade:
        upgrade_fees_collector_contract(args.compare_states)
    elif args.set_pairs:
        set_pairs_in_fees_collector()
    else:
        print('invalid arguments')


def set_pairs_in_fees_collector():
    """Set pairs in fees collector"""

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    fees_collector_address = context.get_contracts(FEES_COLLECTOR_LABEL)[0].address

    pair_addresses = get_all_pair_addresses()
    fees_collector = FeesCollectorContract(fees_collector_address)

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


def upgrade_fees_collector_contract(compare_states: bool):
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    context = Context()
    fees_collector_contract: FeesCollectorContract
    fees_collector_contract = context.get_contracts(FEES_COLLECTOR_LABEL)[0]

    print(f"Upgrading fees collector contract...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [fees_collector_contract.address], FEES_COLLECTOR_LABEL)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = fees_collector_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                        config.FEES_COLLECTOR_BYTECODE_PATH,
                                        [], True)

    if not network_providers.check_simple_tx_status(tx_hash, f"upgrade fees collector: {fees_collector_contract.address}"):
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    if compare_states:
        fetch_new_and_compare_contract_states(FEES_COLLECTOR_LABEL, fees_collector_contract.address, network_providers)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return
