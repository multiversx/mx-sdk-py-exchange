import json
import sys
from typing import List
from argparse import ArgumentParser
from multiversx_sdk_cli.accounts import Address
from context import Context
from tools.runners.account_state_runner import get_account_keys_online
from tools.common import API, OUTPUT_FOLDER, PROXY, fetch_contracts_states, get_contract_save_name
from tools.runners import pair_runner, farm_runner, \
    staking_runner, metastaking_runner, router_runner, \
    proxy_runner, locked_asset_runner, fees_collector_runner, \
    account_state_runner
from utils.contract_data_fetchers import FarmContractDataFetcher, PairContractDataFetcher, RouterContractDataFetcher, StakingContractDataFetcher
from utils.utils_generic import log_step_fail
from utils.utils_tx import NetworkProviders


def main(cli_args: List[str]):
    parser = ArgumentParser()
    subparser = parser.add_subparsers(dest='command')
    pair = subparser.add_parser('pair', help='handle pairs')
    farms = subparser.add_parser('farms', help='handle farms')
    stakings = subparser.add_parser('stakings', help='handle stakings')
    metastakings = subparser.add_parser('metastakings', help='handle metastakings')
    router = subparser.add_parser('router', help='handle router')
    proxy = subparser.add_parser('proxy', help='handle proxy')
    locked_asset = subparser.add_parser('locked-asset', help='handle locked asset')
    fees_collector = subparser.add_parser('fees-collector', help='handle fees collector')
    account_state = subparser.add_parser('account-state', help='handle account state')

    pair_runner.add_parsed_arguments(pair)
    farm_runner.add_parsed_arguments(farms)
    staking_runner.add_parsed_arguments(stakings)
    metastaking_runner.add_parsed_arguments(metastakings)
    router_runner.add_parsed_arguments(router)
    proxy_runner.add_parsed_arguments(proxy)
    locked_asset_runner.add_parsed_arguments(locked_asset)
    fees_collector_runner.add_parsed_arguments(fees_collector)
    account_state_runner.add_parsed_arguments(account_state)

    parser.add_argument('--fetch-pause-state', action='store_true', help='fetch pause state')
    parser.add_argument('--fetch-all-states', type=ascii, default='pre',
                        help='fetch all contracts states; specify prefix; default is pre')
    parser.add_help = True
    args = parser.parse_args(cli_args)

    if args.command == 'pair':
        pair_runner.handle_command(args)
    elif args.command == 'farms':
        farm_runner.handle_command(args)
    elif args.command == 'stakings':
        staking_runner.handle_command(args)
    elif args.command == 'metastakings':
        metastaking_runner.handle_command(args)
    elif args.command == 'router':
        router_runner.handle_command(args)
    elif args.command == 'proxy':
        proxy_runner.handle_command(args)
    elif args.command == 'locked_asset':
        locked_asset_runner.handle_command(args)
    elif args.command == 'fees_collector':
        fees_collector_runner.handle_command(args)
    elif args.command == 'account_state':
        account_state_runner.get_account_keys_online(args.address, args.proxy_url, args.block_number, args.with_save_in)
    elif args.fetch_pause_state:
        fetch_and_save_pause_state()
    elif args.fetch_all_states:
        fetch_all_contracts_states(args.fetch_all_states)
    elif args.command == 'help':
        parser.print_help()


def fetch_and_save_pause_state():
    """Fetch and save pause state of all contracts"""

    pair_addresses = pair_runner.get_all_pair_addresses()
    staking_addresses = staking_runner.get_all_staking_addresses()
    farm_addresses = farm_runner.get_all_farm_v13_addresses()
    output_pause_states = OUTPUT_FOLDER / "contract_pause_states.json"
    network_providers = NetworkProviders(API, PROXY)

    contract_states = {}
    for pair_address in pair_addresses:
        data_fetcher = PairContractDataFetcher(Address(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[pair_address] = contract_state

    for staking_address in staking_addresses:
        data_fetcher = StakingContractDataFetcher(Address(staking_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        contract_states[staking_address] = contract_state

    for farm_address in farm_addresses:
        data_fetcher = FarmContractDataFetcher(Address(farm_address), network_providers.proxy.url)
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
    router_data_fetcher = RouterContractDataFetcher(Address(router_address), network_providers.proxy.url)
    template_pair_address = Address(router_data_fetcher.get_data("getPairTemplateAddress")).bech32()
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


if __name__ == '__main__':
    main(sys.argv[1:])
