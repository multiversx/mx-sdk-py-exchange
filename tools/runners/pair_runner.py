from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
from typing import Any
from multiversx_sdk import Address
from context import Context
from contracts.contract_identities import PairContractVersion
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.pair_contract import PairContract
from contracts.router_contract import RouterContract
from tools.common import API, OUTPUT_FOLDER, OUTPUT_PAUSE_STATES, PROXY, \
    fetch_contracts_states, fetch_new_and_compare_contract_states, get_contract_save_name, get_owner, \
    get_user_continue, run_graphql_query, fetch_and_save_contracts, get_saved_contract_addresses
from tools.runners.account_state_runner import report_key_files_compare
from tools.runners.common_runner import add_upgrade_all_command
from utils.contract_data_fetchers import PairContractDataFetcher, RouterContractDataFetcher
from utils.utils_tx import NetworkProviders, prepare_contract_call_tx

import config
import json
import os
import sys


PAIRS_LABEL = "pairs"
OUTPUT_PAIR_CONTRACTS_FILE = OUTPUT_FOLDER / "pairs_data.json"

UPGRADE_PAIR_GAS_LIMIT = 30000000
SET_ACTIVE_NO_SWAPS_GAS_LIMIT = 10000000
TX_CHUNK_SIZE = 100
CONTRACT_FETCH_THREADS = 8
STATE_FETCH_PROCESSES = 4


def setup_parser(subparsers: ArgumentParser) -> ArgumentParser:
    """Set up argument parser for pair commands"""
    group_parser = subparsers.add_parser('pairs', help='pairs group commands')
    subgroup_parser = group_parser.add_subparsers()

    contract_parser = subgroup_parser.add_parser('contract', help='pairs contract commands')

    contract_group = contract_parser.add_subparsers()
    add_upgrade_all_command(contract_group, upgrade_pair_contracts)

    command_parser = contract_group.add_parser('fetch-all', help='fetch all contracts command')
    command_parser.set_defaults(func=fetch_and_save_pairs_from_chain)

    command_parser = contract_group.add_parser('pause-all', help='pause all contracts command')
    command_parser.set_defaults(func=pause_pair_contracts)

    command_parser = contract_group.add_parser('resume-all', help='resume all contracts command')
    command_parser.set_defaults(func=resume_pair_contracts)

    command_parser = contract_group.add_parser('set-fees-collector', help='set fees collector in all contracts command')
    command_parser.set_defaults(func=set_fees_collector_in_pairs)

    command_parser = contract_group.add_parser('remove-from-fees-collector', help='remove fees collector from all contracts command')
    command_parser.set_defaults(func=remove_pairs_from_fees_collector)

    command_parser = contract_group.add_parser('update-fees', help='update fees percentage in all contracts command')
    command_parser.set_defaults(func=update_fees_percentage)

    return group_parser


def fetch_and_save_pairs_from_chain(_):
    """Fetch and save pairs from chain"""

    print('fetch_and_save_pairs_from_chain')

    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address
    print(f"Router address: {router_address}")
    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), PROXY)
    registered_pairs = router_data_fetcher.get_data("getAllPairsManagedAddresses")
    registered_pairs = [Address.new_from_hex(address, "erd").to_bech32() for address in registered_pairs]
    fetch_and_save_contracts(registered_pairs, PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE)


def pause_pair_contracts(_):
    """Pause pair contracts"""

    print("Pausing pair contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    pair_addresses = get_all_pair_addresses()
    router_contract = RouterContract.load_contract_by_address(router_address)

    # pause all the pairs
    count = 1
    pause_addresses = []

    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address), network_providers.proxy.url)
        contract_state = data_fetcher.get_data("getState")
        if contract_state != 0:
            pause_addresses.append(Address.new_from_bech32(pair_address))
        else:
            print(f"Contract {pair_address} already inactive. Current state: {contract_state}")

        count += 1

    chunk_size = 100
    chunks = [pause_addresses[i:i + chunk_size] for i in range(0, len(pause_addresses), chunk_size)]
    for chunk in chunks:
        tx_hash = router_contract.pair_contract_pause(dex_owner, network_providers.proxy, chunk)
        if not network_providers.check_simple_tx_status(tx_hash, f"pause pair contracts: {len(chunk)}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return


def resume_pair_contracts(_):
    """Resume pair contracts"""

    print("Resuming pair contracts")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              "Cannot proceed safely without altering initial state.")
        return

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    network_config = network_providers.proxy.get_network_config()
    pair_addresses = get_all_pair_addresses()
    router_contract = RouterContract.load_contract_by_address(router_address)

    # sort the pairs by the state they have to be restored to, before sending anything
    resume_addresses = []
    no_swaps_addresses = []
    for count, pair_address in enumerate(pair_addresses, 1):
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        if pair_address not in contract_states:
            print(f"Contract {pair_address} wasn't touched or no available initial state!")
            continue

        if contract_states[pair_address] == 1:
            resume_addresses.append(Address.new_from_bech32(pair_address))
        elif contract_states[pair_address] == 2:
            no_swaps_addresses.append(pair_address)
        else:
            print(f"Contract {pair_address} wasn't touched" \
                  f" because of initial state: {contract_states[pair_address]}")

    if not set_pairs_active_no_swaps(network_providers, network_config, dex_owner, no_swaps_addresses):
        return

    # the batch above assigned nonces locally, so resync before the router calls take over
    dex_owner.sync_nonce(network_providers.proxy)

    chunk_size = 90
    chunks = [resume_addresses[i:i + chunk_size] for i in range(0, len(resume_addresses), chunk_size)]
    for count, chunk in enumerate(chunks, 1):
        print(f"Resuming chunk {count} / {len(chunks)}: {len(chunk)} pairs")
        tx_hash = router_contract.pair_contract_resume(dex_owner, network_providers.proxy, chunk)
        if not network_providers.check_simple_tx_status(tx_hash, f"resume pair contracts: {len(chunk)}"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return


def set_pairs_active_no_swaps(network_providers: NetworkProviders, network_config,
                              dex_owner, pair_addresses: list) -> bool:
    """Set every given pair to active-no-swaps. Returns False if the caller should stop.

    No router endpoint takes a list for this state, so each pair needs its own transaction.
    They are broadcast together and verified afterwards instead of being confirmed one by one.
    """

    if not pair_addresses:
        return True

    print(f"Setting {len(pair_addresses)} pair contracts to active no swaps")

    transactions = []
    for pair_address in pair_addresses:
        tx = prepare_contract_call_tx(Address.new_from_bech32(pair_address), dex_owner, network_config,
                                      SET_ACTIVE_NO_SWAPS_GAS_LIMIT, 'setStateActiveNoSwaps', [])
        dex_owner.nonce += 1
        transactions.append(tx)

    chunks = [transactions[i:i + TX_CHUNK_SIZE] for i in range(0, len(transactions), TX_CHUNK_SIZE)]

    updated = 0
    for count, chunk in enumerate(chunks, 1):
        print(f"Sending chunk {count} / {len(chunks)}: {len(chunk)} txs")
        sent_txs, tx_hashes = network_providers.proxy.send_transactions(chunk)

        if sent_txs != len(chunk):
            print(f"Only {sent_txs}/{len(chunk)} transactions were accepted in chunk {count}. "
                  f"Aborting to avoid a nonce gap.")
            return False

        if not network_providers.check_complex_tx_status(tx_hashes[-1].hex(), "set active no swaps"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                return False

        updated += count_successful_transactions(network_providers, tx_hashes, "setStateActiveNoSwaps")

    print(f"Set {updated}/{len(pair_addresses)} pair contracts to active no swaps")

    if updated != len(pair_addresses):
        print(f"WARNING: {len(pair_addresses) - updated} pair contracts were NOT set to active no swaps.")
        return get_user_continue(config.FORCE_CONTINUE_PROMPT)

    return True


def upgrade_pair_contracts(args: Any):
    """Upgrade pair contracts"""

    if getattr(args, 'bytecode', None):
        raise ValueError(
            "--bytecode is not supported for pair upgrades. Pairs are owned by the router and are "
            "upgraded through its upgradePair endpoint, which clones the router's stored pair "
            "template - the bytecode is never taken from the caller. To roll out new pair code, "
            "upgrade the template contract (router getPairTemplateAddress) with the new bytecode "
            "first via 'router contract upgrade-template', then run this command."
        )

    compare_states = args.compare_states

    print(f"Upgrading pair contracts with compare states: {compare_states}")

    network_providers = NetworkProviders(API, PROXY)
    network_config = network_providers.proxy.get_network_config()
    dex_owner = get_owner(network_providers.proxy)
    context = Context()
    router_address = context.get_contracts(config.ROUTER_V2)[0].address

    pair_addresses = get_all_pair_addresses()

    chunk_size = TX_CHUNK_SIZE
    pairs_chunks = [pair_addresses[i:i + chunk_size] for i in range(0, len(pair_addresses), chunk_size)]

    if compare_states:
        print("Fetching contract state before upgrade...")
        with multiprocessing.Pool(STATE_FETCH_PROCESSES) as pool:
            pool.map(batch_fetch_pre_pairs_states, pairs_chunks)

    pair_contracts = []
    failed_addresses = []

    with ThreadPoolExecutor(max_workers=CONTRACT_FETCH_THREADS) as executor:
        futures = {
            executor.submit(PairContract.load_contract_by_address, addr): addr
            for addr in pair_addresses
        }
        for i, future in enumerate(as_completed(futures)):
            addr = futures[future]
            try:
                pair_contract = future.result()

                if pair_contract is not None:
                    pair_contracts.append(pair_contract)
                    print(f"Fetched {i} / {len(pair_addresses)}: {addr}")
                else:
                    failed_addresses.append(addr)
                    print(f"Failed {i} / {len(pair_addresses)}: {addr}")
            except Exception as e:
                failed_addresses.append(addr)
                print(f"Failed {i} / {len(pair_addresses)}: {addr} - {e}")

    for addr in failed_addresses:
        try:
            contract = PairContract.load_contract_by_address(addr)
            if contract is not None:
                pair_contracts.append(contract)
        except Exception as e:
            print(f"Retry failed: {addr} - {e}")

    if len(pair_contracts) != len(pair_addresses):
        print(f"Failed to fetch all pairs: {len(pair_contracts)}/{len(pair_addresses)}")
        sys.exit(1)

    count = 1
    upgrade_transactions = []
    for pair_contract in pair_contracts:
        print(f"Processing contract {count} / {len(pair_contracts)}")
        endpoint_args = [pair_contract.firstToken, pair_contract.secondToken]
        tx = prepare_contract_call_tx(Address.new_from_bech32(router_address), dex_owner, network_config, UPGRADE_PAIR_GAS_LIMIT, 'upgradePair', endpoint_args)
        dex_owner.nonce += 1
        upgrade_transactions.append(tx)
        count += 1

    transactions_chunks = [upgrade_transactions[i:i + chunk_size] for i in range(0, len(upgrade_transactions), chunk_size)]

    print(f"Prepared {len(upgrade_transactions)} upgrade transactions for {len(pair_addresses)} pairs, "
          f"in {len(transactions_chunks)} chunk(s) of up to {chunk_size}.")
    if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
        return

    count = 1
    upgraded_pairs = 0
    aborted = False
    for chunk in transactions_chunks:
        print(f"Sending chunk {count} / {len(transactions_chunks)}: {len(chunk)} txs")
        sent_txs, tx_hashes = network_providers.proxy.send_transactions(chunk)

        if sent_txs != len(chunk):
            print(f"Only {sent_txs}/{len(chunk)} transactions were accepted in chunk {count}. "
                  f"Aborting to avoid a nonce gap.")
            aborted = True
            break

        if not network_providers.check_complex_tx_status(tx_hashes[-1].hex(), "upgrade pair contracts"):
            if not get_user_continue(config.FORCE_CONTINUE_PROMPT):
                aborted = True
                break

        upgraded_pairs += count_successful_transactions(network_providers, tx_hashes, "upgradePair")
        count += 1

    print(f"Upgraded {upgraded_pairs}/{len(pair_addresses)} pair contracts")

    if compare_states and aborted:
        print("Skipping state comparison: the upgrade was aborted, so the post state would not "
              "describe a completed upgrade.")
    elif compare_states:
        print("Fetching contract state after upgrade...")
        with multiprocessing.Pool(STATE_FETCH_PROCESSES) as pool:
            pool.map(batch_fetch_mid_pairs_states, pairs_chunks)

        old_state_prefix = get_contract_save_name(PAIRS_LABEL, "", "pre")
        new_state_prefix = get_contract_save_name(PAIRS_LABEL, "", "mid")
        report_key_files_compare(str(OUTPUT_FOLDER), old_state_prefix, new_state_prefix, True)

    if aborted or upgraded_pairs != len(pair_addresses):
        print(f"FAILED: {len(pair_addresses) - upgraded_pairs} pair contracts were NOT upgraded.")
        sys.exit(1)


def count_successful_transactions(network_providers: NetworkProviders, tx_hashes: list, label: str) -> int:
    """Check each transaction and report how many actually succeeded on chain.

    send_transactions only reports mempool acceptance; an accepted transaction can still fail
    on chain (out of gas, signalError), so every hash has to be inspected individually.
    """

    successful = 0
    with ThreadPoolExecutor(max_workers=CONTRACT_FETCH_THREADS) as executor:
        futures = {
            executor.submit(network_providers.check_simple_tx_status, tx_hash.hex(), label): tx_hash
            for tx_hash in tx_hashes
        }
        for future in as_completed(futures):
            tx_hash = futures[future]
            try:
                if future.result():
                    successful += 1
                else:
                    print(f"Failed {label} tx: {tx_hash.hex()}")
            except Exception as e:
                print(f"Couldn't check {label} tx {tx_hash.hex()}: {e}")

    return successful


def batch_fetch_pre_pairs_states(pairs_addresses: list):
    """Fetch pairs states in batches"""

    network_providers = NetworkProviders(API, PROXY)
    fetch_contracts_states("pre", network_providers, pairs_addresses, PAIRS_LABEL)


def batch_fetch_mid_pairs_states(pairs_addresses: list):
    """Fetch pairs states in batches"""

    network_providers = NetworkProviders(API, PROXY)
    fetch_contracts_states("mid", network_providers, pairs_addresses, PAIRS_LABEL)

def set_fees_collector_in_pairs(_):
    """Set fees collector in pairs"""

    print("Setting fees collector in all pairs")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    fees_collector = FeesCollectorContract(context.get_contracts(config.FEES_COLLECTORS)[0].address)
    whitelist = get_depositing_addresses()

    if not whitelist:
        return

    count = 1
    for pair_address in whitelist:
        print(f"Processing contract {count} / {len(whitelist)}: {pair_address}")
        pair_contract = PairContract.load_contract_by_address(pair_address)
        fees_cut = 50000

        # setup fees collector in pair
        tx_hash = pair_contract.add_fees_collector(dex_owner, network_providers.proxy,
                                                   [fees_collector.address, fees_cut])
        _ = network_providers.check_simple_tx_status(tx_hash, "set fees collector in pair")

        if not get_user_continue():
            return

        count += 1


def remove_pairs_from_fees_collector(_):
    """Remove pairs from fees collector"""

    print("Removing pairs from fees collector")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)
    context = Context()

    fees_collector = FeesCollectorContract(context.get_contracts(config.FEES_COLLECTORS)[0].address)
    pair_addresses = get_all_pair_addresses()
    depositing_addresses = get_depositing_addresses()

    whitelisted_tokens = []

    print("Aligning planets...")
    for address in depositing_addresses:
        if address in pair_addresses:
            pair_addresses.remove(address)

        pair_contract = PairContract.load_contract_by_address(address)
        whitelisted_tokens.append(pair_contract.firstToken)
        whitelisted_tokens.append(pair_contract.secondToken)

    removable_addresses = []
    removable_tokens = []
    for pair_address in pair_addresses:
        pair_contract = PairContract.load_contract_by_address(pair_address)

        removable_addresses.append(pair_address)
        if pair_contract.firstToken not in whitelisted_tokens and \
           pair_contract.firstToken not in removable_tokens:
            removable_tokens.append(pair_contract.firstToken)
        if pair_contract.secondToken not in whitelisted_tokens and \
           pair_contract.secondToken not in removable_tokens:
            removable_tokens.append(pair_contract.secondToken)

    print(f"Will remove {len(removable_addresses)} pairs from fees collector.")
    print(f"Will remove {len(removable_tokens)} tokens from fees collector.")
    print(removable_tokens)
    if not get_user_continue():
        return

    count = 1
    # remove pair address in fees collector
    for address in removable_addresses:
        print(f"Processing contract {count} / {len(removable_addresses)}")
        tx_hash = fees_collector.remove_known_contracts(dex_owner,
                                                        network_providers.proxy, [address])
        if not network_providers.check_simple_tx_status(tx_hash, "remove pair addresses"):
            if not get_user_continue():
                return
        count += 1

    count = 1
    # remove token in fees collector
    for token in removable_tokens:
        print(f"Processing token {count} / {len(removable_tokens)}")
        tx_hash = fees_collector.remove_known_tokens(dex_owner,
                                                     network_providers.proxy, [f"str:{token}"])
        if not network_providers.check_simple_tx_status(tx_hash, "remove token"):
            if not get_user_continue():
                return
        count += 1

    if not get_user_continue():
        return


def update_fees_percentage(_):
    """Update fees percentage"""

    print("Updating fees percentage")

    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    pair_addresses = get_depositing_addresses()

    count = 1
    for pair_address in pair_addresses:
        print(f"Processing contract {count} / {len(pair_addresses)}: {pair_address}")
        pair_contract = PairContract.load_contract_by_address(pair_address)
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address),
                                                    network_providers.proxy.url)
        total_fee_percentage = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percentage = 100

        pair_contract.version = PairContractVersion.V2
        tx_hash = pair_contract.set_fees_percents(dex_owner, network_providers.proxy,
                                                  [total_fee_percentage, special_fee_percentage])

        if not network_providers.check_complex_tx_status(tx_hash, f"set fees percentages: {pair_address}"):
            if not get_user_continue():
                return

        fetch_new_and_compare_contract_states(PAIRS_LABEL, pair_address, network_providers)

        if not get_user_continue():
            return

        count += 1


def deploy_pair_view():
    """Deploy pair view contract"""

    print("Deploying pair view contract...")
    network_providers = NetworkProviders(API, PROXY)
    dex_owner = get_owner(network_providers.proxy)

    pair_view_contract = PairContract("", "", PairContractVersion.V1)

    tx_hash, address = pair_view_contract.view_contract_deploy(dex_owner, network_providers.proxy,
                                                               config.PAIR_VIEW_BYTECODE_PATH,
                                                               [config.ZERO_CONTRACT_ADDRESS])

    if not network_providers.check_complex_tx_status(tx_hash, f"deploy view contract: {address}"):
        if not get_user_continue():
            return


def get_depositing_addresses() -> list:
    """Get depositing addresses"""

    pair_addresses = get_pairs_for_fees_addresses()

    if not os.path.exists(OUTPUT_PAUSE_STATES):
        print("Contract initial states not found!"
              "Cannot proceed due to risk of whitelisting inactive pairs.")
        return []

    with open(OUTPUT_PAUSE_STATES, encoding="UTF-8") as reader:
        contract_states = json.load(reader)

    whitelist = []
    print("Whitelisted pairs:")
    # filter whitelistable contracts
    for pair_address in pair_addresses:
        if pair_address not in contract_states:
            print(f"Contract {pair_address} will be skipped. No available initial pause state!")
            continue
        # whitelist only if pool was active
        if contract_states[pair_address] == 1:
            whitelist.append(pair_address)
            pair_contract = PairContract.load_contract_by_address(pair_address)
            print(f"{pair_contract.firstToken} / {pair_contract.secondToken}")

    print(f"Number of contracts: {len(whitelist)}")

    if not get_user_continue():
        return []

    return whitelist


def get_pairs_for_fees_addresses() -> list:
    """Get pairs for fees addresses"""

    query = """
            { pairs (limit:100) {
             address
             lockedValueUSD
             type
             } }
            """

    result = run_graphql_query(config.GRAPHQL, query)
    pairs = result['data']['pairs']
    sorted_pairs = []

    for entry in pairs:
        if entry['type'] == 'Core' or entry['type'] == 'Ecosystem':
            sorted_pairs.append(entry['address'])

    return sorted_pairs


def get_all_pair_addresses() -> list:
    """Get all pair addresses"""

    return get_saved_contract_addresses(PAIRS_LABEL, OUTPUT_PAIR_CONTRACTS_FILE)
