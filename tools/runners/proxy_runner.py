from argparse import ArgumentParser
from context import Context
from contracts.contract_identities import ProxyContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from tools.common import API, PROXY, fetch_contracts_states, fetch_new_and_compare_contract_states, get_owner, get_user_continue
from utils.utils_tx import NetworkProviders
from utils.utils_chain import WrapperAddress as Address
import config

from utils.contract_data_fetchers import ProxyContractDataFetcher

from utils.utils_chain import hex_to_string


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--upgrade', action='store_true', help='upgrade proxy dex')


def handle_command(args):
    """Handle proxy dex commands"""

    if args.upgrade:
        upgrade_proxy_dex_contracts(args.compare_states)
    else:
        print('invalid arguments')


def upgrade_proxy_dex_contracts(compare_states: bool = False):
    """Upgrade proxy dex contracts"""

    print("Upgrade proxy dex contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    proxy_dex_contract: DexProxyContract
    proxy_dex_contract = context.get_contracts(config.PROXIES_V2)[0]

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
                                                  config.PROXY_V2_BYTECODE_PATH, 
                                                  [old_locked_token, old_factory_address])

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade proxy-dex contract: "
                                                              f"{proxy_dex_contract.address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states("proxy_dex", proxy_dex_contract.address, context.network_provider)
