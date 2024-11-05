from argparse import ArgumentParser
from typing import Any
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command
from utils.utils_tx import NetworkProviders, upgrade_call
from utils.utils_chain import WrapperAddress as Address, get_bytecode_codehash
from utils.utils_generic import get_file_from_url_or_path
from multiversx_sdk.core import CodeMetadata
import config


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for generic contract commands"""
    group_parser = subparsers.add_parser('generic', help='generic contract group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='generic contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_generic_contract)

    return group_parser


def upgrade_generic_contract(args: Any):
    """Upgrade any generic contract"""

    if not args.address:
        raise Exception("Address is required for generic contract upgrade")

    address = args.address
    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    print(f"Upgrading generic contract: {address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        raise Exception("Bytecode path is required for generic contract upgrade")

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [address], "generic")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return
        
    metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
    gas_limit = 200000000

    tx_hash = upgrade_call("generic", network_providers.proxy, gas_limit, dex_owner, Address(address), 
                           bytecode_path, metadata, [])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade generic contract: "
                                                              f"{address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("generic", address, network_providers)
