from argparse import ArgumentParser
from typing import Any
from multiversx_sdk import Address
import config
from context import Context
from contracts.contract_identities import PairContractVersion, RouterContractVersion
from tools.common import API, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, \
    get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command
from utils.contract_data_fetchers import RouterContractDataFetcher
from utils.contract_retrievers import retrieve_pair_by_address, retrieve_router_by_address

from utils.utils_tx import NetworkProviders
from utils.utils_generic import get_file_from_url_or_path
from utils.utils_chain import get_bytecode_codehash


TEMPLATE_PAIR_LABEL = "template_pair"


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for router commands"""
    group_parser = subparsers.add_parser('router', help='router group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='router contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_router_contract)

    command_parser = contract_group.add_parser('upgrade-template', help='upgrade template contract command')
    command_parser.set_defaults(func=upgrade_template_pair_contract)

    command_parser = contract_group.add_parser('pair-creation', help='toggle pair creation command')
    command_parser.add_argument('--state', action='store_true', help='pair creation state')
    command_parser.set_defaults(func=enable_pair_creation)

    return group_parser


def upgrade_router_contract(args: Any):
    """Upgrade router contract"""

    router_address = args.address
    compare_states = args.compare_states

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    print(f"Upgrade router contract: {router_address}")

    router_contract = retrieve_router_by_address(router_address)

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = config.ROUTER_V2_BYTECODE_PATH

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [router_address], config.ROUTER_V2)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    # change router version & upgrade router contract
    router_contract.version = RouterContractVersion.V2
    tx_hash = router_contract.contract_upgrade(dex_owner, network_providers.proxy, bytecode_path)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade router contract {router_address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states(config.ROUTER_V2, router_address, network_providers)


def upgrade_template_pair_contract(args: Any):
    """Upgrade template pair contract"""
    
    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), network_providers.proxy.url)
    template_pair_address = Address.new_from_hex(router_data_fetcher.get_data("getPairTemplateAddress"), "erd").to_bech32()
    template_pair = retrieve_pair_by_address(template_pair_address)
    print(f"Upgrade template pair contract: {template_pair_address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = config.PAIR_V2_BYTECODE_PATH

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print("Fetching contract states before upgrade...")
        fetch_contracts_states("pre", network_providers, [template_pair_address], TEMPLATE_PAIR_LABEL)

        if not get_user_continue():
            return

    template_pair.version = PairContractVersion.V2
    args = [config.ZERO_CONTRACT_ADDRESS, config.ZERO_CONTRACT_ADDRESS,
            config.ZERO_CONTRACT_ADDRESS, 0, 0, config.ZERO_CONTRACT_ADDRESS]
    tx_hash = template_pair.contract_upgrade(dex_owner, network_providers.proxy, bytecode_path, args)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade template pair contract: {template_pair_address}"):
        if not get_user_continue():
            return

    if compare_states:
        print("Fetching contract states before upgrade...")
        fetch_new_and_compare_contract_states(TEMPLATE_PAIR_LABEL, template_pair_address, network_providers)


def enable_pair_creation(args: Any):
    """Enable pair creation"""

    if not args.state:
        print("Invalid arguments")
        return

    action = "enable" if args.state else "disable"
    print(f"{action} pair creation...")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    router_contract = retrieve_router_by_address(context.get_contracts(config.ROUTER_V2)[0].address)

    tx_hash = router_contract.set_pair_creation_enabled(dex_owner, network_providers.proxy, [args.state])

    if not network_providers.check_simple_tx_status(tx_hash, f"{action} pair creation"):
        if not get_user_continue():
            return
