from argparse import ArgumentParser
from context import Context
from contracts.locked_asset_contract import LockedAssetContract
from tools.common import API, PROXY, \
    fetch_new_and_compare_contract_states, get_owner, get_user_continue
import config
from tools.runners.common_runner import add_upgrade_command
from utils.utils_tx import NetworkProviders

from utils.utils_chain import get_bytecode_codehash


LOCKED_ASSET_LABEL = "locked_asset"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for locked asset commands"""
    group_parser = subparsers.add_parser('locked-assets', help='locked assets group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='locked assets contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_locked_asset_contracts)

    return group_parser


def upgrade_locked_asset_contracts(_):
    """Upgrade locked asset contracts"""

    print("Upgrade locked asset factory contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    locked_asset_factory_address = context.get_contracts(config.LOCKED_ASSETS)[0].address

    print(f"Processing contract {locked_asset_factory_address}")
    locked_asset_contract = LockedAssetContract("", "", locked_asset_factory_address)

    bytecode_path = config.LOCKED_ASSET_FACTORY_BYTECODE_PATH

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    tx_hash = locked_asset_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                     bytecode_path, [],
                                                     no_init=True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade locked asset factory contract: "
                                                              f"{locked_asset_factory_address}"):
        if not get_user_continue():
            return

    fetch_new_and_compare_contract_states(LOCKED_ASSET_LABEL, locked_asset_factory_address, network_providers)

    if not get_user_continue():
        return
