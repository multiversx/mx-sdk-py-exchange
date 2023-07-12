from argparse import ArgumentParser
from context import Context
from contracts.contract_identities import ProxyContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from tools.common import API, PROXY, get_owner, get_user_continue
from utils.utils_tx import NetworkProviders
import config


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--upgrade', action='store_true', help='upgrade prxoy dex')


def handle_command(args):
    """Handle proxy dex commands"""

    if args.upgrade:
        upgrade_proxy_dex_contracts()
    else:
        print('invalid arguments')


def upgrade_proxy_dex_contracts():
    """Upgrade proxy dex contracts"""

    print("Upgrade proxy dex contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    proxy_dex_address = context.get_contracts(config.PROXIES_V2)[0].address

    print(f"Processing contract {proxy_dex_address}")
    proxy_dex_contract = DexProxyContract([], "", ProxyContractVersion.V1, address=proxy_dex_address)

    tx_hash = proxy_dex_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                  config.PROXY_BYTECODE_PATH, [],
                                                  no_init=True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade proxy-dex contract: "
                                                              f"{proxy_dex_address}"):
        if not get_user_continue():
            return

    # fetch_new_and_compare_contract_states(PROXY_DEX_LABEL, proxy_dex_address, network_providers)

    if not get_user_continue():
        return
