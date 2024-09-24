from argparse import ArgumentParser
from typing import Any

import config
from context import Context
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from tools.common import get_user_continue, fetch_contracts_states, fetch_new_and_compare_contract_states
from tools.runners.common_runner import add_upgrade_command, add_verify_command, verify_contracts

from utils.utils_tx import NetworkProviders
from utils.utils_generic import get_file_from_url_or_path
from utils.utils_chain import get_bytecode_codehash


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for energy factory commands"""
    group_parser = subparsers.add_parser('energy-factory', help='energy factory group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='energy factory contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_energy_factory)
    add_verify_command(contract_group, verify_energy_factory)

    command_parser = contract_group.add_parser('pause', help='pause contract command')
    command_parser.set_defaults(func=pause_energy_factory)
    command_parser = contract_group.add_parser('resume', help='resume contract command')
    command_parser.set_defaults(func=resume_energy_factory)

    return group_parser


def pause_energy_factory(_):
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.pause(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"pause energy contract: {energy_contract}")


def resume_energy_factory(_):
    context = Context()
    energy_contract: SimpleLockEnergyContract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    tx_hash = energy_contract.resume(context.deployer_account, context.network_provider.proxy)
    context.network_provider.check_simple_tx_status(tx_hash, f"resume energy contract: {energy_contract}")


def upgrade_energy_factory(args: Any):
    compare_states = args.compare_states
    context = Context()
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    energy_contract = SimpleLockEnergyContract.load_contract_by_address(energy_factory_address)
    print(f"Upgrade energy factory contract: {energy_factory_address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = get_file_from_url_or_path(config.SIMPLE_LOCK_ENERGY_BYTECODE_PATH)
    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", context.network_provider, [energy_contract.address], "energy")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = energy_contract.contract_upgrade(context.deployer_account, context.network_provider.proxy,
                                               bytecode_path,
                                               [], True)

    if not context.network_provider.check_complex_tx_status(tx_hash, f"upgrade energy contract: {energy_contract}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("energy", energy_contract.address, context.network_provider)


def verify_energy_factory(args: Any):
    print("Verifying energy contract...")

    context = Context()
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    verify_contracts(args, [energy_factory_address])
    
    print("All contracts have been verified.")
    