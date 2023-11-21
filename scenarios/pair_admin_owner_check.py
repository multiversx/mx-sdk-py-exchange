import random
import sys
import time
from typing import List
import config
from context import Context
from events.event_generators import (
    generate_add_initial_liquidity_event, generate_add_liquidity_event,
    generate_swap_fixed_input)
from ported_arrows.stress.send_token_from_minter import main as send_token_from_minter
from ported_arrows.stress.shared import get_shard_of_address
from utils.account import Account


def main(cli_args: List[str]):
    context = Context()
    create_nonce_file(context)
    # send_tokens(context=context)

    owner_account = context.accounts.get_all()[0]
    admin_account = context.accounts.get_all()[1]  # erd1gvkklm20rk9vg0xnyq0aq3ae3cnle8qxa7eqcevnhfthe5gj9z4s293za5
    user_account = context.accounts.get_all()[3]

    fee_collector_contract = context.get_fee_collector_contract(0)
    pair_contract = context.get_pair_v2_contract(0)
    router_contract = context.get_router_v2_contract(0)
    simple_lock_contract = context.get_simple_lock_contract(0)


    ### Regular User doesn't have access to Owner specific endpoints ######
    tx_hash = pair_contract.whitelist_contract(user_account, context.proxy, user_account.address)
    print("Whitelist Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_add_trusted_swap_pair = [pair_contract.address, pair_contract.firstToken, pair_contract.secondToken]
    tx_hash = pair_contract.add_trusted_swap_pair(user_account, context.proxy, args_add_trusted_swap_pair)
    print("Add Trusted Swap Pair Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_add_fees_collector = [fee_collector_contract.address, 500]
    tx_hash = pair_contract.add_fees_collector(user_account, context.proxy, args_add_fees_collector)
    print("Add Fees Collector Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_set_fee_on_via_router = [fee_collector_contract.address, pair_contract.firstToken]
    tx_hash = pair_contract.set_fee_on_via_router(user_account, context.proxy, router_contract, args_set_fee_on_via_router)
    print("Set Fee On Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Endpoint can only be called by owner") else "Failed!")

    tx_hash = pair_contract.set_fee_percents(user_account, context.proxy, 500, 300)
    print("Set Fee Percent Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_locking_deadline_epoch(user_account, context.proxy, 1000)
    print("Set Locking Deadline Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_unlock_epoch(user_account, context.proxy, 1000)
    print("Set Unlock Epoch Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_lp_token_identifier(user_account, context.proxy, pair_contract.lpToken)
    print("Set LP Token ID Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_extern_swap_gas_limit(user_account, context.proxy, 100000000)
    print("Set Extern Swap Gas Limit Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    # Simple lock energy contract must be deployed
    tx_hash = pair_contract.set_locking_sc_address(user_account, context.proxy, simple_lock_contract.address)
    print("Set Unlock Epoch Test RegularUser NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")


    ### Admin doesn't have access to Owner specific endpoints
    tx_hash = pair_contract.whitelist_contract(admin_account, context.proxy, user_account.address)
    print("Whitelist Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_add_trusted_swap_pair = [pair_contract.address, pair_contract.firstToken, pair_contract.secondToken]
    tx_hash = pair_contract.add_trusted_swap_pair(admin_account, context.proxy, args_add_trusted_swap_pair)
    print("Add Trusted Swap Pair Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_add_fees_collector = [fee_collector_contract.address, 500]
    tx_hash = pair_contract.add_fees_collector(admin_account, context.proxy, args_add_fees_collector)
    print("Add Fees Collector Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    args_set_fee_on_via_router = [fee_collector_contract.address, pair_contract.firstToken]
    tx_hash = pair_contract.set_fee_on_via_router(admin_account, context.proxy, router_contract, args_set_fee_on_via_router)
    print("Add Fees Collector Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Endpoint can only be called by owner") else "Failed!")

    tx_hash = pair_contract.set_locking_deadline_epoch(admin_account, context.proxy, 1000)
    print("Set Locking Deadline Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_unlock_epoch(admin_account, context.proxy, 1000)
    print("Set Unlock Epoch Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_lp_token_identifier(admin_account, context.proxy, pair_contract.lpToken)
    print("Set LP Token ID Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_extern_swap_gas_limit(admin_account, context.proxy, 100000000)
    print("Set Extern Swap Gas Limit Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    # Simple lock energy contract must be deployed
    tx_hash = pair_contract.set_locking_sc_address(admin_account, context.proxy, simple_lock_contract.address)
    print("Set Unlock Epoch Test Admin NO Access -", "Success!" if context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")


    ### Owner Has access
    tx_hash = pair_contract.whitelist_contract(owner_account, context.proxy, user_account.address)
    print("Whitelist Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    args_add_trusted_swap_pair = [pair_contract.address, pair_contract.firstToken, pair_contract.secondToken]
    tx_hash = pair_contract.add_trusted_swap_pair(owner_account, context.proxy, args_add_trusted_swap_pair)
    print("Add Trusted Swap Pair Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    args_add_fees_collector = [fee_collector_contract.address, 500]
    tx_hash = pair_contract.add_fees_collector(owner_account, context.proxy, args_add_fees_collector)
    print("Add Fees Collector Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    args_set_fee_on_via_router = [fee_collector_contract.address, pair_contract.firstToken]
    tx_hash = pair_contract.set_fee_on_via_router(owner_account, context.proxy, router_contract, args_set_fee_on_via_router)
    print("Add Fees Collector Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    tx_hash = pair_contract.set_locking_deadline_epoch(owner_account, context.proxy, 1000)
    print("Set Locking Deadline Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    tx_hash = pair_contract.set_unlock_epoch(owner_account, context.proxy, 1000)
    print("Set Unlock Epoch Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    tx_hash = pair_contract.set_lp_token_identifier(owner_account, context.proxy, pair_contract.lpToken)
    print("Set LP Token ID Test Owner Has Access -", "Success!" if not context.network_provider.check_for_error_operation(tx_hash, "Permission denied") else "Failed!")

    tx_hash = pair_contract.set_extern_swap_gas_limit(owner_account, context.proxy, 100000000)
    print("Set Extern Swap Gas Limit Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

    # Simple lock energy contract must be deployed
    tx_hash = pair_contract.set_locking_sc_address(owner_account, context.proxy, simple_lock_contract.address)
    print("Set Unlock Epoch Test Owner Has Access -", "Success!" if context.network_provider.check_simple_tx_status(tx_hash, "Owner TX") else "Failed!")

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
