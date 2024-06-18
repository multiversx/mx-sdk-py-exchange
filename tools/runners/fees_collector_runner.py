from argparse import ArgumentParser
from context import Context
from contracts.fees_collector_contract import FeesCollectorContract
from tools.common import API, PROXY, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command
from tools.runners.pair_runner import get_all_pair_addresses
from utils.contract_retrievers import retrieve_pair_by_address

from utils.utils_tx import NetworkProviders


FEES_COLLECTOR_LABEL = 'fees_collector'


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for fees collector commands"""
    group_parser = subparsers.add_parser('fees-collector', help='fees collector group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='fees collector contract commands')

    contract_group = contract_parser.add_subparsers()

    command_parser = contract_group.add_parser('set-pairs', help='set pairs contracts command')
    command_parser.set_defaults(func=set_pairs_in_fees_collector)

    return group_parser


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
