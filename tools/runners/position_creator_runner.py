from argparse import ArgumentParser
from typing import Any
from tools.common import API, OUTPUT_FOLDER, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, \
    get_user_continue
from context import Context
from tools.runners.common_runner import add_upgrade_all_command
from contracts.position_creator_contract import PositionCreatorContract
from contracts.farm_contract import FarmContract, FarmContractVersion
from contracts.staking_contract import StakingContract, StakingContractVersion
from contracts.metastaking_contract import MetaStakingContract, MetaStakingContractVersion
from utils.utils_chain import WrapperAddress as Address, get_bytecode_codehash
from utils.contract_retrievers import retrieve_position_creator_by_address
from utils.utils_tx import NetworkProviders
from runners.farm_runner import get_farm_addresses_from_chain
from runners.staking_runner import get_staking_addresses_from_chain
from runners.metastaking_runner import get_metastaking_addresses_from_chain_by_farms
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
    add_upgrade_all_command(contract_group, upgrade_position_creator_contract)

    command_parser = contract_group.add_parser('deploy', help='deploy contract command')
    command_parser.set_defaults(func=deploy_position_creator_contract)
    command_parser = contract_group.add_parser('setup-whitelist', help='whitelist contract where needed command')
    command_parser.set_defaults(func=setup_whitelist)

    return group_parser


def upgrade_position_creator_contract(args: Any):
    """Upgrade position creator contract"""

    print("Upgrading position creator contract")

    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    position_creator_address = context.get_contracts(config.POSITION_CREATOR)[0].address
    position_creator_contract = retrieve_position_creator_by_address(position_creator_address)

    deploy_structure_list = populate_deploy_lists.populate_list(config.DEPLOY_STRUCTURE_JSON, POSITION_CREATOR_LABEL)
    position_creator_contract.egld_wrapper_address = deploy_structure_list[0]["egld_wrapped_address"]
    position_creator_contract.router_address = deploy_structure_list[0]["router_address"]

    bytecode_path = config.POSITION_CREATOR_BYTECODE_PATH

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print("Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [position_creator_address], POSITION_CREATOR_LABEL)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    tx_hash = position_creator_contract.contract_upgrade(dex_owner, network_providers.proxy, bytecode_path)

    if not network_providers.check_simple_tx_status(tx_hash, f"upgrade position creator contract: {position_creator_address}"):
        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    if compare_states:
        fetch_new_and_compare_contract_states(POSITION_CREATOR_LABEL, position_creator_address, network_providers)

    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return


def deploy_position_creator_contract(_):
    """Deploy position creator contract"""

    print("Deploying position creator contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    egld_wrapped_address = context.get_contracts(config.EGLD_WRAPS)[1].address
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    position_creator_contract = PositionCreatorContract()
    tx_hash, address = position_creator_contract.contract_deploy(dex_owner, network_providers.proxy, config.POSITION_CREATOR_BYTECODE_PATH,
                                              [egld_wrapped_address, router_address])

    if not network_providers.check_simple_tx_status(tx_hash, f"deploy position creator contract"):
        return
    
    print(f"Deployed position creator contract at address: {address}")
    

def setup_whitelist(_):
    """Setup whitelist for position creator contract"""

    print("Setting up whitelist for position creator contract")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    context = Context()
    position_creator_address = context.get_contracts(config.POSITION_CREATOR)[0].address
    position_creator_contract = retrieve_position_creator_by_address(position_creator_address)

    farm_addresses = get_farm_addresses_from_chain("v2")
    staking_addresses = get_staking_addresses_from_chain()
    staking_proxy_addresses = get_metastaking_addresses_from_chain_by_farms(farm_addresses)

    print("Whitelisting position creator in farms...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    for address in farm_addresses:
        farm_contract = FarmContract("", "", "", address, FarmContractVersion.V2Boosted)
        if farm_contract.is_contract_whitelisted(position_creator_contract.address, network_providers.proxy):
            print(f"Position creator already whitelisted in farm: {address}")
            continue
        farm_contract.add_contract_to_whitelist(dex_owner, network_providers.proxy, position_creator_contract.address)

    print("Whitelisting position creator in staking contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return
    
    for address in staking_addresses:
        if staking_contract.is_contract_whitelisted(position_creator_contract.address, network_providers.proxy):
            print(f"Position creator already whitelisted in staking contract: {address}")
            continue
        staking_contract = StakingContract("", 0, 0, 0, StakingContractVersion.V3Boosted, "", address)
        staking_contract.whitelist_contract(dex_owner, network_providers.proxy, position_creator_contract.address)

    print("Whitelisting position creator in metastaking contracts...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return
    
    for address in staking_proxy_addresses:
        if metastaking_contract.is_contract_whitelisted(position_creator_contract.address, network_providers.proxy):
            print(f"Position creator already whitelisted in metastaking contract: {address}")
            continue
        metastaking_contract = MetaStakingContract("", "", "", "", "", "", "", MetaStakingContractVersion.V3Boosted, "", address)
        metastaking_contract.whitelist_contract(dex_owner, network_providers.proxy, position_creator_contract.address)
    