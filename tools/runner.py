import json
import sys
from typing import Any, List
from argparse import ArgumentParser
from multiversx_sdk import Address
from context import Context
from tools.runners.account_state_runner import get_account_keys_online
from tools.common import API, OUTPUT_FOLDER, PROXY, fetch_contracts_states, get_contract_save_name
from tools.runners import pair_runner, farm_runner, \
    staking_runner, metastaking_runner, router_runner, \
    proxy_runner, locked_asset_runner, fees_collector_runner, \
    account_state_runner, energy_factory_runner, position_creator_runner
from utils.contract_data_fetchers import FarmContractDataFetcher, PairContractDataFetcher, RouterContractDataFetcher, StakingContractDataFetcher
from utils.utils_generic import log_step_fail
from utils.utils_tx import NetworkProviders


def main(cli_args: List[str]):
    parser = setup_parser()
    args = parser.parse_args(cli_args)

    if not hasattr(args, 'func'):
        parser.print_help()
        return

    args.func(args)


def setup_parser():
    parser = ArgumentParser()

    parser.add_argument('--fetch-pause-state', action='store_true', help='fetch pause state')
    parser.set_defaults(func=fetch_and_save_pause_state)
    parser.add_argument('--fetch-all-states', type=ascii, default='pre',
                        help='fetch all contracts states; specify prefix; default is pre')
    parser.set_defaults(func=fetch_all_contracts_states)

    subparsers = parser.add_subparsers()
    commands: List[Any] = []

    commands.append(pair_runner.setup_parser(subparsers))
    commands.append(farm_runner.setup_parser(subparsers))
    commands.append(staking_runner.setup_parser(subparsers))
    commands.append(metastaking_runner.setup_parser(subparsers))
    commands.append(router_runner.setup_parser(subparsers))
    commands.append(proxy_runner.setup_parser(subparsers))
    commands.append(locked_asset_runner.setup_parser(subparsers))
    commands.append(fees_collector_runner.setup_parser(subparsers))
    commands.append(energy_factory_runner.setup_parser(subparsers))
    commands.append(position_creator_runner.setup_parser(subparsers))

    return parser


def fetch_and_save_pause_state():
    """Fetch and save pause state of all contracts"""

    pair_addresses = pair_runner.get_all_pair_addresses()
    staking_addresses = staking_runner.get_all_staking_addresses()
    farm_addresses = farm_runner.get_all_farm_v2_addresses()
    output_pause_states = OUTPUT_FOLDER / "contract_pause_states.json"
    network_providers = NetworkProviders(API, PROXY)

    contract_states = {}
    for pair_address in pair_addresses:
        data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[pair_address] = contract_state

    for staking_address in staking_addresses:
        data_fetcher = StakingContractDataFetcher(Address.new_from_bech32(staking_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[staking_address] = contract_state

    for farm_address in farm_addresses:
        data_fetcher = FarmContractDataFetcher(Address.new_from_bech32(farm_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[farm_address] = contract_state

    with open(output_pause_states, 'w', encoding="UTF-8") as writer:
        json.dump(contract_states, writer, indent=4)
        print(f"Dumped contract pause states in {output_pause_states}")


def fetch_all_contracts_states(prefix: str):
    """Fetch all contracts states"""

    network_providers = NetworkProviders(API, PROXY)
    context = Context()
    locked_asset_address = context.get_contracts("locked_assets")[0].address
    router_address = context.get_contracts("router_v2")[0].address

    # get locked asset state
    if locked_asset_address:
        filename = get_contract_save_name(locked_asset_runner.LOCKED_ASSET_LABEL, locked_asset_address, prefix)
        get_account_keys_online(locked_asset_address, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))
    else:
        log_step_fail("Locked asset factory address not available. No state saved for this!")

    # get proxy dex state
    # filename = get_contract_save_name(PROXY_DEX_LABEL, PROXY_DEX_CONTRACT, prefix)
    # get_account_keys_online(PROXY_DEX_CONTRACT, network_providers.proxy.url,
    #                         with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))

    # get router state
    if router_address:
        filename = get_contract_save_name(router_runner.ROUTER_LABEL, router_address, prefix)
        get_account_keys_online(router_address, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))
    else:
        log_step_fail("Router address not available. No state saved for this!")

    # get template state
    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), network_providers.proxy.url)
    template_pair_address = Address.from_hex(router_data_fetcher.get_data("getPairTemplateAddress"), "erd").bech32()
    filename = get_contract_save_name(router_runner.TEMPLATE_PAIR_LABEL, template_pair_address, prefix)
    get_account_keys_online(template_pair_address, network_providers.proxy.url,
                            with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))

    # get pairs contract states
    pair_addresses = pair_runner.get_all_pair_addresses()
    fetch_contracts_states(prefix, network_providers, pair_addresses, pair_runner.PAIRS_LABEL)

    # get staking states
    staking_addresses = staking_runner.get_all_staking_addresses()
    fetch_contracts_states(prefix, network_providers, staking_addresses, staking_runner.STAKINGS_LABEL)

    # get metastaking states
    metastaking_addresses = metastaking_runner.get_all_metastaking_addresses()
    fetch_contracts_states(prefix, network_providers, metastaking_addresses, metastaking_runner.METASTAKINGS_LABEL)

    # get farm v12 states
    farm_v12_addresses = farm_runner.get_all_farm_v12_addresses()
    fetch_contracts_states(prefix, network_providers, farm_v12_addresses, farm_runner.FARMSV12_LABEL)

    # get farm v13 states
    farm_v13_addresses = farm_runner.get_all_farm_v13_addresses()
    fetch_contracts_states(prefix, network_providers, farm_v13_addresses, farm_runner.FARMSV13_LABEL)

    # get farm v2 states
    farm_v2_addresses = farm_runner.get_all_farm_v2_addresses()
    fetch_contracts_states(prefix, network_providers, farm_v2_addresses, farm_runner.FARMSV2_LABEL)    
    
if __name__ == '__main__':
    main(sys.argv[1:])
