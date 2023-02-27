import concurrent.futures
import random
import sys
import time
import traceback

import pytest
from itertools import count
from typing import List
from argparse import ArgumentParser

import config
from context import Context
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.pair_contract import PairContract, AddLiquidityEvent
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from events.event_generators import (generate_add_initial_liquidity_event,
                                                       generate_add_liquidity_event,
                                                       generateEnterFarmEvent,
                                                       generateEnterMetastakeEvent,
                                                       generateClaimMetastakeRewardsEvent,
                                                       generateExitMetastakeEvent, generate_swap_fixed_input)
from utils.contract_data_fetchers import PairContractDataFetcher, SimpleLockEnergyContractDataFetcher
from utils.utils_tx import ESDTToken
from utils.utils_chain import print_test_step_pass, print_condition_assert, nominated_amount, \
    print_test_step_fail, TestStepConditions, get_token_details_for_address, get_all_token_nonces_details_for_account
from arrows.stress.send_token_from_minter import main as send_token_from_minter
from arrows.stress.send_egld_from_minter import main as send_egld_from_minter
from arrows.stress.shared import get_shard_of_address
from erdpy.accounts import Account, Address


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--threads", required=False, default="2")  # number of concurrent threads to execute operations
    parser.add_argument("--repeats", required=False, default="0")  # number of total operations to execute; 0 - infinite
    parser.add_argument("--skip-minting", action="store_true", default=False)
    args = parser.parse_args(cli_args)

    context = Context()

    if not args.skip_minting:
        send_tokens(context)
        wait_time = 40
        print(f"Minting accounts done. Waiting for the dust to settle: {wait_time}s until execution start")
        time.sleep(wait_time)

    create_nonce_file(context)

    # stress generator for adding liquidity, enter farm, enter metastaking, claim metastaking, exit metastaking
    scenarios(context, int(args.threads), int(args.repeats))


def create_nonce_file(context: Context):
    context.accounts.sync_nonces(context.proxy)
    context.accounts.store_nonces(context.nonces_file)
    context.deployer_account.sync_nonce(context.proxy)


def send_tokens(context: Context):
    proxy_url = config.DEFAULT_PROXY
    accounts = config.DEFAULT_ACCOUNTS
    minter = config.DEFAULT_OWNER
    tk_amount = nominated_amount(100000)
    egld_amount = nominated_amount(1)

    for token in context.deploy_structure.tokens:
        print(f"Funding each account with {tk_amount} {token} tokens.")
        args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
                f'--minter={minter}', f'--token={token}', f'--amount-atoms={tk_amount}']
        send_token_from_minter(args)
        time.sleep(7)

    print(f"Funding each account with {egld_amount} eGLD tokens.")
    args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
            f'--minter={minter}', f'--value-atoms={egld_amount}']
    send_egld_from_minter(args)
    time.sleep(7)


def add_initial_liquidity(context: Context):
    # add initial liquidity
    pair_contract: PairContract
    for pair_contract in context.get_contracts(config.PAIRS):
        pair_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.network_provider.proxy.url)
        first_token_liquidity = pair_data_fetcher.get_token_reserve(pair_contract.firstToken)
        if first_token_liquidity == 0:
            event = AddLiquidityEvent(
                pair_contract.firstToken, nominated_amount(1000000), 1,
                pair_contract.secondToken, nominated_amount(1000000), 1
            )
            pair_contract.addLiquidity(context.network_provider, context.deployer_account, event)
            time.sleep(6)


def scenarios(context: Context, threads: int, repeats: int):
    accounts = context.accounts.get_all()

    context.swap_min_tokens_to_spend = 0.0001
    context.swap_max_tokens_to_spend = 0.001

    # add initial liquidity in contract if necessary
    add_initial_liquidity(context)

    if threads == 1:
        """Sequential run"""
        for _ in range(repeats if repeats != 0 else 99999999):
            scenarios_per_account(context, random.choice(accounts))
    elif threads > 1:
        """ Concurential run """
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            jobs = min(threads, repeats) if repeats != 0 else threads
            finished_jobs = 0
            futures = [executor.submit(scenarios_per_account, context, random.choice(accounts))
                       for _ in range(jobs)]

            # feed the thread workers as they complete each job
            while finished_jobs < repeats or repeats == 0:
                try:
                    for future in concurrent.futures.as_completed(futures):
                        finished_jobs += 1
                        print_test_step_pass(f"Finished {finished_jobs} repeats.")
                        futures.remove(future)
                        # spawn a new job
                        futures.append(executor.submit(scenarios_per_account, context, random.choice(accounts)))
                        if future.exception() is not None:
                            print_test_step_fail(f"Thread failed: {future.exception()}")
                except Exception as ex:
                    traceback.print_exception(*sys.exc_info())
                    print_test_step_fail(f"Something failed: {ex}")
    else:
        print_test_step_fail(f"Number of threads must be minimum 1!")
        return


def scenarios_per_account(context: Context, account: Account):
    min_time = 10
    max_time = 30
    deployer_shard = get_shard_of_address(context.deployer_account.address)
    sleep_time = config.CROSS_SHARD_DELAY if get_shard_of_address(account.address) is not deployer_shard \
        else 6

    account.sync_nonce(context.network_provider.proxy)

    pair_contract: PairContract
    pair_contract = random.choice(context.get_contracts(config.PAIRS))

    # swap tokens
    generate_swap_fixed_input(context, account, pair_contract)
    time.sleep(sleep_time)

    wait_time = random.randint(min_time, max_time)
    print(f'Finished repeat execution. Waiting for {wait_time}s.')
    time.sleep(wait_time)


if __name__ == "__main__":
    main(sys.argv[1:])
