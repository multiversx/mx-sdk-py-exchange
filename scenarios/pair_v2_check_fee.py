import random
import sys
import time
from typing import List

import config
from context import Context
from events.event_generators import (
    generate_add_initial_liquidity_event, generate_add_liquidity_event,
    generate_swap_fixed_input)
from utils.contract_data_fetchers import (
    FeeCollectorContractDataFetcher, PairContractDataFetcher)
from arrows.stress.send_token_from_minter import main as send_token_from_minter
from arrows.stress.shared import get_shard_of_address
from erdpy.accounts import Account, Address


def main(cli_args: List[str]):
    context = Context()
    create_nonce_file(context)
    # send_tokens(context=context)

    user_account = context.accounts.get_all()[0]
    pair_contract = context.get_pair_v2_contract(0)
    fee_collector_contract = context.get_fee_collector_contract(0)
    contract_data_fetcher = FeeCollectorContractDataFetcher(Address(fee_collector_contract.address), context.proxy.url)
    tokens = [pair_contract.firstToken, pair_contract.secondToken]

    # add_initial_liquidity(context=context, account=user_account)
    # add_liquidity(context=context, account=user_account)

    initial_amount_token = contract_data_fetcher.get_token_reserve(tokens[0])
    swap(context=context, account=user_account)
    final_amount_token = contract_data_fetcher.get_token_reserve(tokens[0])

    print("initial_amount_token = ", initial_amount_token, " final_amount_token = ", final_amount_token)
    if final_amount_token <= initial_amount_token:
        # TODO Proper throw error
        print("Error! Amount didn't increase!")
        return -1

    return


def add_initial_liquidity(context: Context, account: Account):
    for pair_contract in context.get_contracts(config.PAIRS_V2):
        generate_add_initial_liquidity_event(context, context.deployer_account, pair_contract)
        time.sleep(config.INTRA_SHARD_DELAY)
        pair_contract.resume(context.deployer_account, context.network_provider.proxy)
        time.sleep(config.INTRA_SHARD_DELAY)


def add_liquidity(context: Context, account: Account):
    min_time = 2
    max_time = 10
    deployer_shard = get_shard_of_address(context.deployer_account.address)
    sleep_time = config.CROSS_SHARD_DELAY if get_shard_of_address(account.address) is not deployer_shard \
        else config.INTRA_SHARD_DELAY

    account.sync_nonce(context.network_provider.proxy)

    pair_contract = context.get_pair_v2_contract(0)
    generate_add_liquidity_event(context, account, pair_contract)
    time.sleep(sleep_time)

    wait_time = random.randint(min_time, max_time)

    print(f'Finished repeat execution. Waiting for {wait_time}s.')
    time.sleep(wait_time)


def swap(context: Context, account: Account):
    min_time = 2
    max_time = 10
    deployer_shard = get_shard_of_address(context.deployer_account.address)
    sleep_time = config.CROSS_SHARD_DELAY if get_shard_of_address(account.address) is not deployer_shard \
        else config.INTRA_SHARD_DELAY

    account.sync_nonce(context.network_provider.proxy)

    pair_contract = context.get_pair_v2_contract(0)
    generate_swap_fixed_input(context, account, pair_contract)
    time.sleep(sleep_time)

    wait_time = random.randint(min_time, max_time)

    print(f'Finished repeat execution. Waiting for {wait_time}s.')
    time.sleep(wait_time)


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


if __name__ == "__main__":
    main(sys.argv[1:])
