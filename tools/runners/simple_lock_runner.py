from argparse import ArgumentParser
from typing import Any
from contracts.simple_lock_contract import SimpleLockContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_only_group_parser, resolve_upgrade_bytecode
from utils.utils_tx import NetworkProviders
import config


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for proxy dex commands"""
    return add_upgrade_only_group_parser(
        subparsers, 'simple-lock', 'simple lock group commands', 'simple lock commands',
        upgrade_simple_lock_contract)


def upgrade_simple_lock_contract(args: Any):
    """Upgrade simple lock contracts"""

    address = args.address
    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    print(f"Upgrading simple lock contract: {address}")

    bytecode_path = resolve_upgrade_bytecode(args.bytecode, config.SIMPLE_LOCK_BYTECODE_PATH,
                                             config.FORCE_CONTINUE_PROMPT)
    if bytecode_path is None:
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [address], "simple_lock")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    contract = SimpleLockContract("", "", "", address)
    tx_hash = contract.contract_upgrade(dex_owner, network_providers.proxy, 
                                        bytecode_path)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade simple lock contract: "
                                                              f"{address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("simple_lock", address, network_providers)
