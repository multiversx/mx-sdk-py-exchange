from argparse import ArgumentParser
from context import Context
from contracts.fees_collector_contract import FeesCollectorContract
from tools.common import API, PROXY, get_owner, get_user_continue
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
        print('upgrade fees collector')
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
