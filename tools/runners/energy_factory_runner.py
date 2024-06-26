from argparse import ArgumentParser

import config
from context import Context
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from tools.common import get_user_continue, fetch_contracts_states, fetch_new_and_compare_contract_states
from tools.runners.common_runner import add_upgrade_command
from utils.contract_retrievers import retrieve_simple_lock_energy_by_address, retrieve_locked_asset_factory_by_address

from utils.utils_tx import NetworkProviders


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for energy factory commands"""
    group_parser = subparsers.add_parser('energy-factory', help='energy factory group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='energy factory contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_energy_factory)

    command_parser = contract_group.add_parser('pause', help='pause contract command')
    command_parser.set_defaults(func=pause_energy_factory)
    command_parser = contract_group.add_parser('resume', help='resume contract command')
    command_parser.set_defaults(func=resume_energy_factory)

    return group_parser


def pause_energy_factory():
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.pause(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"pause energy contract: {energy_contract}")


def resume_energy_factory():
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.resume(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"resume energy contract: {energy_contract}")


def upgrade_energy_factory(compare_states: bool = False):
    context = Context()
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    energy_contract = retrieve_simple_lock_energy_by_address(energy_factory_address)

    locked_asset_address = context.get_contracts(config.LOCKED_ASSETS)[0].address
    locked_asset_contract = retrieve_locked_asset_factory_by_address(locked_asset_address)

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", context.network_provider, [energy_contract.address], "energy")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = energy_contract.contract_upgrade(context.deployer_account, context.network_provider.proxy,
                                               config.SIMPLE_LOCK_ENERGY_BYTECODE_PATH,
                                               [locked_asset_contract.locked_asset, locked_asset_contract.address,
                                                0, [], []])

    if not context.network_provider.check_complex_tx_status(tx_hash, f"upgrade energy contract: {energy_contract}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("energy", energy_contract.address, context.network_provider)
