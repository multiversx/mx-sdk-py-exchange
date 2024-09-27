from argparse import ArgumentParser
from typing import Any
from context import Context
from contracts.contract_identities import ProxyContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_upgrade_command
from utils.utils_tx import NetworkProviders
from utils.utils_chain import WrapperAddress as Address, get_bytecode_codehash
from utils.utils_generic import get_file_from_url_or_path
import config

from utils.contract_data_fetchers import ProxyContractDataFetcher

from utils.utils_chain import hex_to_string


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for proxy dex commands"""
    group_parser = subparsers.add_parser('proxy-dex', help='proxy dex group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='proxy dex contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_command(contract_group, upgrade_proxy_dex_contracts)

    return group_parser


def upgrade_proxy_dex_contracts(args: Any):
    """Upgrade proxy dex contracts"""

    compare_states = args.compare_states
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    proxy_dex_contract: DexProxyContract
    proxy_dex_contract = context.get_contracts(config.PROXIES_V2)[0]
    print(f"Upgrade proxy dex contract: {proxy_dex_contract.address}")

    if args.bytecode:
        bytecode_path = get_file_from_url_or_path(args.bytecode)
    else:
        bytecode_path = get_file_from_url_or_path(config.PROXY_V2_BYTECODE_PATH)

    print(f"New bytecode codehash: {get_bytecode_codehash(bytecode_path)}")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", context.network_provider, [proxy_dex_contract.address], "proxy_dex")

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    print(f"Processing contract {proxy_dex_contract.address}")
    

    data_fetcher = ProxyContractDataFetcher(Address(proxy_dex_contract.address), context.network_provider.proxy.url)
    old_locked_token = hex_to_string(data_fetcher.get_data("getLockedTokenIds")[0])
    old_factory_address = context.get_contracts(config.LOCKED_ASSETS)[0].address

    tx_hash = proxy_dex_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                  bytecode_path, 
                                                  [old_locked_token, old_factory_address])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade proxy-dex contract: "
                                                              f"{proxy_dex_contract.address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("proxy_dex", proxy_dex_contract.address, context.network_provider)
