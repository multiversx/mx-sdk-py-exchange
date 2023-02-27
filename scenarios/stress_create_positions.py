import concurrent.futures
import random
import sys
import time
from itertools import count
from typing import List
from argparse import ArgumentParser

import config
from context import Context
from events.event_generators import (generate_add_initial_liquidity_event,
                                                       generate_add_liquidity_event,
                                                       generateEnterFarmEvent,
                                                       generateEnterMetastakeEvent,
                                                       generateClaimMetastakeRewardsEvent,
                                                       generateExitMetastakeEvent,
                                                       generateExitFarmEvent)
from utils.utils_chain import print_test_step_pass
from arrows.stress.send_token_from_minter import main as send_token_from_minter
from arrows.stress.shared import get_shard_of_address
from erdpy.accounts import Account


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--threads", required=False, default="3")  # number of concurrent threads to execute operations
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
    stress(context, int(args.threads), int(args.repeats))


def create_nonce_file(context: Context):
    context.accounts.sync_nonces(context.proxy)
    context.accounts.store_nonces(context.nonces_file)
    context.deployer_account.sync_nonce(context.proxy)


def send_tokens(context: Context):
    proxy_url = config.DEFAULT_PROXY
    accounts = config.DEFAULT_ACCOUNTS
    minter = config.DEFAULT_OWNER
    amount = 3000000000000000000

    for token in context.deploy_structure.tokens:
        print(f"Funding each account with {amount} {token} tokens.")
        args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
                f'--minter={minter}', f'--token={token}', f'--amount-atoms={amount}']
        send_token_from_minter(args)
        time.sleep(7)


def stress(context: Context, threads: int, repeats: int):
    # set initial liquidity and start pair contract
    # TODO: should be done only once
    """
    for pair_contract in context.get_contracts(config.PAIRS):
        generate_add_initial_liquidity_event(context, context.deployer_account, pair_contract)
        time.sleep(config.INTRA_SHARD_DELAY)
        pair_contract.resume(context.deployer_account, context.network_provider.proxy)
        time.sleep(config.INTRA_SHARD_DELAY)
    """
    accounts = context.accounts.get_all()

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        jobs = min(threads, repeats) if repeats != 0 else threads
        finished_jobs = 0
        futures = [[executor.submit(stress_per_account, context, random.choice(accounts))
                    for _ in range(jobs)]]

        # feed the thread workers as they complete each job
        while finished_jobs < repeats or repeats == 0:
            try:
                for _ in concurrent.futures.as_completed(futures):
                    finished_jobs += 1
                    print_test_step_pass(f"Finished {finished_jobs} repeats.")

                    if repeats == 0 or repeats > finished_jobs:
                        # spawn a new job
                        futures.append(executor.submit(stress_per_account, context, random.choice(accounts)))
            except Exception as ex:
                pass


def stress_per_account(context: Context, account: Account):
    min_time = 2
    max_time = 10
    deployer_shard = get_shard_of_address(context.deployer_account.address)
    sleep_time = config.CROSS_SHARD_DELAY if get_shard_of_address(account.address) is not deployer_shard \
        else config.INTRA_SHARD_DELAY

    account.sync_nonce(context.network_provider.proxy)

    for metastaking_contract in context.get_contracts(config.METASTAKINGS):
        farm_contract = context.get_farm_contract_by_address(metastaking_contract.farm_address)
        pair_contract = context.get_pair_contract_by_address(metastaking_contract.lp_address)

        generate_add_liquidity_event(context, account, pair_contract)
        time.sleep(sleep_time)

        for _ in range(1):
            if generateEnterFarmEvent(context, account, farm_contract):
                time.sleep(sleep_time)
            if generateEnterMetastakeEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)
            if generateClaimMetastakeRewardsEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)
            if generateExitMetastakeEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)

        wait_time = random.randint(min_time, max_time)
        print(f'Finished repeat execution. Waiting for {wait_time}s.')
        time.sleep(wait_time)


if __name__ == "__main__":
    main(sys.argv[1:])
