from argparse import ArgumentParser
from typing import Any
from contracts.simple_lock_contract import SimpleLockContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command
from utils.utils_tx import NetworkProviders
from utils.utils_chain import WrapperAddress as Address
import config

from utils.contract_data_fetchers import ProxyContractDataFetcher

from utils.utils_chain import hex_to_string


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for proxy dex commands"""
    group_parser = subparsers.add_parser('simple-lock', help='simple lock group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='simple lock commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_simple_lock_contract)

    return group_parser


def upgrade_simple_lock_contract(args: Any):
    """Upgrade simple lock contracts"""

    print("Upgrade simple lock contract")

    address = args.address
    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [address], "simple_lock")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    print(f"Processing contract {address}")

    contract = SimpleLockContract("", "", "", address)
    tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy, 
                                        config.SIMPLE_LOCK_BYTECODE_PATH, 
                                        [])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade simple lock contract: "
                                                              f"{address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("simple_lock", address, network_providers)
