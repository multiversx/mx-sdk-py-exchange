from argparse import ArgumentParser
from typing import Any
from context import Context
from contracts.contract_identities import FarmContractVersion, ProxyContractVersion
from contracts.dex_proxy_contract import DexProxyContract, DexProxyExitFarmEvent
from contracts.farm_contract import FarmContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from tools.runners.common_runner import add_generate_transaction_command, add_upgrade_command, get_acounts_with_token, read_accounts_from_json
from utils.utils_chain import Account, WrapperAddress, get_token_details_for_address
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

    transaction_parser = subgroup_parser.add_parser('generate-transactions', help='proxy dex transaction commands')
    transactions_group = transaction_parser.add_subparsers()
    add_generate_transaction_command(transactions_group, exit_proxy, 'exitFarmProxy', 'exit farm proxy command')

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

def exit_proxy(args: any):
    farm_address = args.address
    exported_accounts_path = args.accounts_export
    
    context = Context()
    farm_contract = DexProxyContract.load_contract_by_address(farm_address)
    network_providers = NetworkProviders(API, PROXY)

    farm_contract: FarmContract
    farm_contract = context.get_contracts(config.FARMS_V2)[0]
    proxy_contract: DexProxyContract
    proxy_contract = context.get_contracts(config.PROXIES_V2)[0]
    
    exported_accounts = read_accounts_from_json(exported_accounts_path)
    accounts_with_token = get_acounts_with_token(exported_accounts, proxy_contract.proxy_farm_token)
    
    for account_with_token in accounts_with_token:
        account = Account(account_with_token.address, config.DEFAULT_OWNER)
        account.address = WrapperAddress.from_bech32(account_with_token.address)
        account.sync_nonce(network_providers.proxy)
        tokens = [token for token in account_with_token.account_tokens_supply if token.token_name == proxy_contract.proxy_farm_token ]
        for token in tokens:
                event = DexProxyExitFarmEvent(farm_contract, proxy_contract.proxy_farm_token, int(token.token_nonce_hex,16), int(token.supply) )
                proxy_contract.exit_farm_proxy(account, context.network_provider.proxy, event)