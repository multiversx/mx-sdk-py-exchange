import concurrent.futures
import logging
import random
import sys
import time
import traceback
from itertools import count
from typing import List, Optional
from argparse import ArgumentParser

from multiversx_sdk_network_providers import ApiNetworkProvider, ProxyNetworkProvider

import config
from contracts.egld_wrap_contract import EgldWrapContract
from utils.logger import get_logger
from context import Context
from contracts.metastaking_contract import MetaStakingContract
from contracts.pair_contract import PairContract, AddLiquidityEvent, SwapFixedInputEvent
from events.event_generators import (generate_add_initial_liquidity_event,
                                                       generate_add_liquidity_event,
                                                       generateEnterFarmEvent,
                                                       generateEnterMetastakeEvent,
                                                       generateClaimMetastakeRewardsEvent,
                                                       generateExitMetastakeEvent,
                                                       generateExitFarmEvent)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_generic import log_step_pass, log_step_fail
from ported_arrows.stress.send_token_from_minter import main as send_token_from_minter
from ported_arrows.stress.send_egld_from_minter import main as send_egld_from_minter
from utils.utils_chain import Account, BunchOfAccounts, WrapperAddress as Address, nominated_amount
from utils.utils_scenarios import FetchedUsers, collect_farm_contract_users


logger = get_logger(__name__)


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--threads", required=False, default="3")  # number of concurrent threads to execute operations
    parser.add_argument("--repeats", required=False, default="0")  # number of total operations to execute; 0 - infinite
    parser.add_argument("--users", required=False, default="10")  # number of total users per contract to use
    args = parser.parse_args(cli_args)

    if int(args.threads) > int(args.users):
        log_step_fail(f"Number of threads must be lower than number of users!")
        return

    context = Context()

    mainnet_api = ApiNetworkProvider("https://api.multiversx.com")
    contract: MetaStakingContract = context.get_contracts(config.METASTAKINGS_V2)[0]
    collected_users: FetchedUsers = collect_farm_contract_users(int(args.users), contract.address, contract.farm_token, contract.metastake_token,
                                                                mainnet_api, context.network_provider.proxy)

    prepare_context_sf_accounts(context, collected_users)

    # stress generator for adding liquidity, enter farm, enter metastaking, claim metastaking, exit metastaking
    stress(context, int(args.threads), int(args.repeats), contract)


def prepare_context_sf_accounts(context: Context, collected_users: FetchedUsers):
    collected_accounts: list[Account] = []
    for user in collected_users.users:
        account = Account(pem_file=config.DEFAULT_ADMIN)
        account.address = user.address
        collected_accounts.append(account)

    context.accounts = BunchOfAccounts(collected_accounts)


def swap_tokens(context: Context):
    max_egld_to_spend = nominated_amount(20)

    egld_on_purse = context.network_provider.proxy.get_account(context.admin_account.address).balance
    egld_to_spend = min(egld_on_purse - nominated_amount(1), max_egld_to_spend)
    egld_to_swap = egld_to_spend // 2
    logger.info(f"Swapping {egld_to_swap} eGLD for wEGLD and {egld_to_swap} eGLD for tokens.")

    wrap_contracts = context.get_contracts(config.EGLD_WRAPS)
    wrap_contract: Optional[EgldWrapContract] = None
    for wrap_contract in wrap_contracts:
        if Address(wrap_contract.address).get_shard() == context.admin_account.address.get_shard():
            break

    if wrap_contract is None:
        log_step_fail("No wrap contract found.")
        sys.exit(1)

    # swap all spendable eGLD for wEGLD
    tx_hash = wrap_contract.wrap_egld(context.admin_account, context.network_provider.proxy, egld_to_spend)
    context.network_provider.check_simple_tx_status(tx_hash)

    # swap half of the wEGLD for tokens
    pair_contracts = context.get_contracts(config.PAIRS_V2)
    egld_per_pair = egld_to_swap // len(pair_contracts)
    pair_contract: Optional[PairContract] = None
    for pair_contract in pair_contracts:
        swapped_token = pair_contract.firstToken if wrap_contract.wrapped_token == pair_contract.secondToken else \
            pair_contract.secondToken
        swap_event = SwapFixedInputEvent(tokenA=wrap_contract.wrapped_token,
                                         amountA=egld_per_pair,
                                         tokenB=swapped_token,
                                         amountBmin=1)
        logger.info(f"Swapping {egld_per_pair} {wrap_contract.wrapped_token} for {swapped_token} "
                    f"in pair {pair_contract.address}.")
        tx_hash = pair_contract.swap_fixed_input(context.network_provider, context.admin_account, swap_event)
        context.network_provider.check_simple_tx_status(tx_hash)


def send_egld(context: Context):
    proxy_url = config.DEFAULT_PROXY
    accounts = config.DEFAULT_ACCOUNTS
    minter = config.DEFAULT_ADMIN
    amount = nominated_amount(1)

    logger.info(f"Funding each account with {amount} eGLD.")
    args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
            f'--minter={minter}', f'--value-atoms={amount}']
    send_egld_from_minter(args)
    time.sleep(7)
    context.admin_account.sync_nonce(context.network_provider.proxy)


def send_tokens(context: Context):
    proxy_url = config.DEFAULT_PROXY
    accounts = config.DEFAULT_ACCOUNTS
    minter = config.DEFAULT_ADMIN

    for token in context.deploy_structure.tokens:
        amount_on_deployer = context.network_provider.proxy.get_fungible_token_of_account(
            context.admin_account.address, token).balance
        
        if amount_on_deployer == 0:
            continue

        # divide the amount between all user accounts + deployer
        no_accounts = len(context.accounts.accounts) + 1
        amount = amount_on_deployer // no_accounts
        logger.info(f"Funding {no_accounts} accounts with {amount} {token} tokens each "
                    f"from a total of {amount_on_deployer}.")
        args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
                f'--minter={minter}', f'--token={token}', f'--amount-atoms={amount}']
        send_token_from_minter(args)
        time.sleep(7)
    
    context.admin_account.sync_nonce(context.network_provider.proxy)


def add_initial_liquidity(context: Context):
    # add initial liquidity
    pair_contract: PairContract
    for pair_contract in context.get_contracts(config.PAIRS_V2):
        pair_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.network_provider.proxy.url)
        first_token_liquidity = pair_data_fetcher.get_token_reserve(pair_contract.firstToken)
        if first_token_liquidity == 0:
            event = AddLiquidityEvent(
                pair_contract.firstToken, nominated_amount(10), 1,
                pair_contract.secondToken, nominated_amount(10), 1
            )
            pair_contract.add_initial_liquidity(context.network_provider, context.deployer_account, event)
            time.sleep(6)


def stress(context: Context, threads: int, repeats: int, contract: MetaStakingContract):
    deployer_shard = context.deployer_account.address.get_shard()
    accounts = context.accounts.get_in_shard(deployer_shard)

    context.swap_min_tokens_to_spend = 0.0001
    context.swap_max_tokens_to_spend = 0.001

    if threads == 1:
        """Sequential run"""
        for _ in range(repeats if repeats != 0 else 99999999):
            stress_per_account(context, random.choice(accounts), contract)
    elif threads > 1:
        """ Concurential run """
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            jobs = min(threads, repeats) if repeats != 0 else threads
            finished_jobs = 0
            futures_per_account = {}
            for _ in range(jobs):
                account = random.choice(accounts)
                future = executor.submit(stress_per_account, context, account, contract)
                futures_per_account[account.address.bech32()] = future

            # feed the thread workers as they complete each job
            while finished_jobs < repeats or repeats == 0:
                try:
                    for completed_future in concurrent.futures.as_completed(list(futures_per_account.values())):
                        finished_jobs += 1
                        # since we are feeding the workers as they complete, we need to check if we are done
                        if finished_jobs >= repeats and repeats != 0:
                            break

                        if completed_future.exception() is not None:
                            log_step_fail(f"Thread failed: {future.exception()}")
                        
                        log_step_pass(f"Finished {finished_jobs} repeats.")
                        # remove the account that finished
                        for account in list(futures_per_account.keys()):
                            future = futures_per_account[account]
                            if future == completed_future:
                                del futures_per_account[account]
                                break

                        # get a new account that is not already running
                        account = random.choice(accounts)
                        while account.address.bech32() in futures_per_account.keys():
                            account = random.choice(accounts)
                        
                        # spawn a new job
                        new_future = executor.submit(stress_per_account, context, account, contract)
                        futures_per_account[account.address.bech32()] = new_future
                        
                except Exception as ex:
                    traceback.print_exception(*sys.exc_info())
                    log_step_fail(f"Something failed: {ex}")
    else:
        log_step_fail(f"Number of threads must be minimum 1!")
        return


def stress_per_account(context: Context, account: Account, metastaking_contract: MetaStakingContract):
    min_time = 2
    max_time = 10
    deployer_shard = context.deployer_account.address.get_shard()
    sleep_time = config.CROSS_SHARD_DELAY if account.address.get_shard() is not deployer_shard \
        else config.INTRA_SHARD_DELAY

    account.sync_nonce(context.network_provider.proxy)

    farm_contract = context.get_farm_contract_by_address(metastaking_contract.farm_address)
    pair_contract = context.get_pair_contract_by_address(metastaking_contract.lp_address)

    operation_hit = False

    for _ in range(1):
        if random.randint(0, 100) <= 10:    # 40% chance
            if generate_add_liquidity_event(context, account, pair_contract):
                time.sleep(sleep_time)
                operation_hit = True
            if generateEnterFarmEvent(context, account, farm_contract):
                time.sleep(sleep_time)
                operation_hit = True
            if generateEnterMetastakeEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)
                operation_hit = True
        if random.randint(0, 100) <= 70:    # 70% chance
            if generateClaimMetastakeRewardsEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)
                operation_hit = True
        if random.randint(0, 100) <= 20:    # 20% chance
            if generateExitMetastakeEvent(context, account, metastaking_contract):
                time.sleep(sleep_time)
                operation_hit = True

    if operation_hit:
        wait_time = random.randint(min_time, max_time)
        logger.info(f'Finished repeat execution. Waiting for {wait_time}s.')
        time.sleep(wait_time)


if __name__ == "__main__":
    main(sys.argv[1:])
