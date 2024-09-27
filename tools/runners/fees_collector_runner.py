import config
from argparse import ArgumentParser
from context import Context
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.pair_contract import PairContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command, add_verify_command, verify_contracts
from tools.runners.pair_runner import get_all_pair_addresses
from typing import Any

from utils.utils_tx import NetworkProviders
from utils.utils_generic import get_file_from_url_or_path
from utils.utils_chain import get_bytecode_codehash


FEES_COLLECTOR_LABEL = 'fees_collector'


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for fees collector commands"""
    group_parser = subparsers.add_parser('fees-collector', help='fees collector group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='fees collector contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_fees_collector_contract)
    add_verify_command(contract_group, verify_fees_collector)

    command_parser = contract_group.add_parser('set-pairs', help='set pairs contracts command')
    command_parser.set_defaults(func=set_pairs_in_fees_collector)

    return group_parser


def set_pairs_in_fees_collector(_):
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
        pair_contract = PairContract.load_contract_by_address(pair_address)

        # add pair address in fees collector
        _ = fees_collector.add_known_contracts(dex_owner, network_providers.proxy,
                                               [pair_address])
        _ = fees_collector.add_known_tokens(dex_owner, network_providers.proxy,
                                            [f"str:{pair_contract.firstToken}",
                                             f"str:{pair_contract.secondToken}"])

        if not get_user_continue():
            return

        count += 1


def upgrade_fees_collector_contract(args: Any):
    compare_states = args.compare_states

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    context = Context()
    fees_collector_contract: FeesCollectorContract
    fees_collector_contract = context.get_contracts(config.FEES_COLLECTORS)[0]

    print(f"Upgrading fees collector contract: {fees_collector_contract.address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = get_file_from_url_or_path(config.FEES_COLLECTOR_BYTECODE_PATH)
        
    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [fees_collector_contract.address], FEES_COLLECTOR_LABEL)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = fees_collector_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                        bytecode_path,
                                        [], True)

    if not network_providers.check_simple_tx_status(tx_hash, f"upgrade fees collector: {fees_collector_contract.address}"):
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    if compare_states:
        fetch_new_and_compare_contract_states(FEES_COLLECTOR_LABEL, fees_collector_contract.address, network_providers)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return


def verify_fees_collector(args: Any):
    print("Verifying fees collector contract...")

    context = Context()
    fees_collector_address = context.get_contracts(config.FEES_COLLECTORS)[0].address
    verify_contracts(args, [fees_collector_address])
    
    print("All contracts have been verified.")