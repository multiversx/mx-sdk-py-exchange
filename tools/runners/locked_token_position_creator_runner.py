from argparse import ArgumentParser
from typing import Any
from tools.common import API, OUTPUT_FOLDER, PROXY, get_owner, \
    get_user_continue
from context import Context
from contracts.locked_token_position_creator_contract import LockedTokenPositionCreatorContract
from contracts.dex_proxy_contract import DexProxyContract
from utils.utils_chain import WrapperAddress as Address
from utils.utils_tx import NetworkProviders
from context import Context
import config

POSITION_CREATOR_LABEL = "position_creator"
OUTPUT_POSITION_CREATOR_FILE = OUTPUT_FOLDER / "position_creator_data.json"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for locked token position creator commands"""
    group_parser = subparsers.add_parser('locked-token-position-creator', help='locked token position creator group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='locked token position creator contract commands')

    contract_group = contract_parser.add_subparsers()

    command_parser = contract_group.add_parser('deploy', help='deploy contract command')
    command_parser.set_defaults(func=deploy_position_creator_contract)
    command_parser = contract_group.add_parser('setup-whitelist', help='whitelist contract where needed command')
    command_parser.add_argument('--address', type=str, help='contract address')
    command_parser.set_defaults(func=setup_whitelist)

    return group_parser


def deploy_position_creator_contract():
    """Deploy locked token position creator contract"""

    print("Deploying locked token position creator contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    egld_wrapped_address = context.get_contracts(config.EGLD_WRAPS)[1].address
    router_address = context.get_contracts(config.ROUTER_V2)[0].address
    energy_factory_address = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0].address
    mex_wegld_pair_address = context.get_contracts(config.PAIRS_V2)[0].address
    mex_wegld_farm_address = context.get_contracts(config.FARMS_V2)[0].address
    proxy_dex_address = context.get_contracts(config.PROXIES_V2)[0].address

    position_creator_contract = LockedTokenPositionCreatorContract()
    tx_hash, address = position_creator_contract.contract_deploy(dex_owner, network_providers.proxy, 
                                                                 config.LOCKED_TOKEN_POSITION_CREATOR_BYTECODE_PATH,
                                                                 [energy_factory_address,
                                                                  egld_wrapped_address,
                                                                  mex_wegld_pair_address,
                                                                  mex_wegld_farm_address,
                                                                  proxy_dex_address,
                                                                  router_address])

    if not network_providers.check_simple_tx_status(tx_hash, f"deploy locked token position creator contract"):
        return
    
    print(f"Deployed locked token position creator contract at address: {address}")
    

def setup_whitelist(args: Any):
    """Setup whitelist for locked token position creator contract"""

    print("Setting up whitelist for locked token position creator contract")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    address = args.address
    _ = Address(address)    # check if address is valid

    context = Context()

    proxy_dex_contract: DexProxyContract
    proxy_dex_contract = context.get_contracts(config.PROXIES_V2)[0]

    print("Whitelisting locked token position creator in proxy dex...")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    proxy_dex_contract.add_contract_to_whitelist(dex_owner, network_providers.proxy, address)
    