from argparse import ArgumentParser
from context import Context
from contracts.locked_asset_contract import LockedAssetContract
from tools.common import API, PROXY, \
    fetch_new_and_compare_contract_states, get_owner, get_user_continue
import config
from utils.utils_tx import NetworkProviders


LOCKED_ASSET_LABEL = "locked_asset"


def add_parsed_arguments(parser: ArgumentParser):
    """Add arguments to the parser"""

    parser.add_argument('--compare-states', action='store_false', default=False,
                        help='compare states before and after upgrade')
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument('--upgrade', action='store_true', help='upgrade locked asset factory')


def handle_command(args):
    """Handle locked asset commands"""

    if args.upgrade:
        upgrade_locked_asset_contracts()
    else:
        print('invalid arguments')


def upgrade_locked_asset_contracts():
    """Upgrade locked asset contracts"""

    print("Upgrade locked asset factory contract")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    locked_asset_factory_address = context.get_contracts(config.LOCKED_ASSETS)[0].address

    print(f"Processing contract {locked_asset_factory_address}")
    locked_asset_contract = LockedAssetContract("", "", locked_asset_factory_address)

    tx_hash = locked_asset_contract.contract_upgrade(dex_owner, network_providers.proxy,
                                                     config.LOCKED_ASSET_FACTORY_BYTECODE_PATH, [],
                                                     no_init=True)

    if not network_providers.check_complex_tx_status(tx_hash, f"upgrade locked asset factory contract: "
                                                              f"{locked_asset_factory_address}"):
        if not get_user_continue():
            return

    fetch_new_and_compare_contract_states(LOCKED_ASSET_LABEL, locked_asset_factory_address, network_providers)

    if not get_user_continue():
        return
