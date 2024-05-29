from argparse import ArgumentParser
from multiversx_sdk import Address
import config
from context import Context
from contracts.contract_identities import PairContractVersion, RouterContractVersion
from tools.common import API, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, \
    get_owner, get_user_continue
from utils.contract_data_fetchers import RouterContractDataFetcher
from utils.contract_retrievers import retrieve_pair_by_address, retrieve_router_by_address

from utils.utils_tx import NetworkProviders


TEMPLATE_PAIR_LABEL = "template_pair"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_true', help='compare states before and after upgrade')
    parser.add_argument('--address', type=str, help='router / pair template contract address')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--upgrade', action='store_true', help='upgrade router')
    mutex.add_argument('--upgrade-template', action='store_true', help='upgrade template pair')
    mutex.add_argument('--enable-pair-creation', action='store_true', help='enable pair creation')
    mutex.add_argument('--disable-pair-creation', action='store_true', help='disable pair creation')


def handle_command(args):
    """Handle router commands"""

    if args.upgrade:
        upgrade_router_contract(args.address, args.compare_states)
    elif args.upgrade_template:
        upgrade_template_pair_contract(args.compare_states)
    elif args.enable_pair_creation:
        enable_pair_creation(True)
    elif args.disable_pair_creation:
        enable_pair_creation(False)
    else:
        print('invalid arguments')


def upgrade_router_contract(router_address: str, compare_states: bool = False):
    """Upgrade router contract"""

    print("Upgrade router contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    print(f"Router address: {router_address}")

    router_contract = retrieve_router_by_address(router_address)

    if compare_states:
        print(f"Fetching contract state before upgrade...")
        fetch_contracts_states("pre", network_providers, [router_address], config.ROUTER_V2)

        if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
            return

    # change router version & upgrade router contract
    router_contract.version = RouterContractVersion.V2
    tx_hash = router_contract.contract_upgrade(dex_owner, network_providers.proxy, config.ROUTER_V2_BYTECODE_PATH)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade router contract {router_address}"):
        return

    if compare_states:
        fetch_new_and_compare_contract_states(config.ROUTER_V2, router_address, network_providers)


def upgrade_template_pair_contract(compare_states: bool = False):
    """Upgrade template pair contract"""

    print("Upgrade template pair contract")
    
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address


    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), network_providers.proxy.url)
    template_pair_address = Address.new_from_hex(router_data_fetcher.get_data("getPairTemplateAddress"), "erd").to_bech32()
    template_pair = retrieve_pair_by_address(template_pair_address)

    if compare_states:
        print("Fetching contract states before upgrade...")
        fetch_contracts_states("pre", network_providers, [template_pair_address], TEMPLATE_PAIR_LABEL)

        if not get_user_continue():
            return

    template_pair.version = PairContractVersion.V2
    args = [config.ZERO_CONTRACT_ADDRESS, config.ZERO_CONTRACT_ADDRESS,
            config.ZERO_CONTRACT_ADDRESS, 0, 0, config.ZERO_CONTRACT_ADDRESS]
    tx_hash = template_pair.contract_upgrade(dex_owner, network_providers.proxy, config.PAIR_V2_BYTECODE_PATH, args)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade template pair contract: {template_pair_address}"):
        if not get_user_continue():
            return

    if compare_states:
        print("Fetching contract states before upgrade...")
        fetch_new_and_compare_contract_states(TEMPLATE_PAIR_LABEL, template_pair_address, network_providers)


def enable_pair_creation(enable: bool):
    """Enable pair creation"""

    action = "enable" if enable else "disable"
    print(f"{action} pair creation...")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    router_contract = retrieve_router_by_address(context.get_contracts(config.ROUTER_V2)[0].address)

    tx_hash = router_contract.set_pair_creation_enabled(dex_owner, network_providers.proxy, [enable])

    if not network_providers.check_simple_tx_status(tx_hash, f"{action} pair creation"):
        if not get_user_continue():
            return
