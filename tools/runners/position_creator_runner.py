from argparse import ArgumentParser
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, \
    get_user_continue
from context import Context
from tools.runners.common_runner import add_upgrade_command
from utils.contract_retrievers import retrieve_position_creator_by_address
from utils.utils_tx import NetworkProviders
from deploy import populate_deploy_lists
import config

POSITION_CREATOR_LABEL = "position_creator"
OUTPUT_POSITION_CREATOR_FILE = OUTPUT_FOLDER / "position_creator_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for position creator commands"""
    group_parser = subparsers.add_parser('position-creator', help='position creator group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='position creator contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_position_creator_contract)

    command_parser = contract_group.add_parser('pause', help='pause contract command')
    command_parser.set_defaults(func=pause_position_creator_contract)
    command_parser = contract_group.add_parser('resume', help='resume contract command')
    command_parser.set_defaults(func=resume_position_creator_contract)

    return group_parser


def pause_position_creator_contract():
    """Pause position creator contract"""

    print("Pausing position creator contract")


def resume_position_creator_contract():
    """Resume position creator contract"""

    print("Resuming position creator contract")


def upgrade_position_creator_contract(compare_states: bool = False):
    """Upgrade position creator contract"""

    print("Upgrading position creator contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    position_creator_address = context.get_contracts(config.POSITION_CREATOR)[0].address
    position_creator_contract = retrieve_position_creator_by_address(position_creator_address)

    deploy_structure_list = populate_deploy_lists.populate_list(config.DEPLOY_STRUCTURE_JSON, POSITION_CREATOR_LABEL)
    position_creator_contract.egld_wrapper_address = deploy_structure_list[0]["egld_wrapped_address"]
    position_creator_contract.router_address = deploy_structure_list[0]["router_address"]

    if compare_states:
        print("Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [position_creator_address], POSITION_CREATOR_LABEL)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = position_creator_contract.contract_upgrade(dex_owner, network_providers.proxy, config.POSITION_CREATOR_BYTECODE_PATH)

    if not network_providers.check_simple_tx_status(tx_hash, f"upgrade position creator contract: {position_creator_address}"):
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    if compare_states:
        fetch_new_and_compare_contract_states(POSITION_CREATOR_LABEL, position_creator_address, network_providers)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return
