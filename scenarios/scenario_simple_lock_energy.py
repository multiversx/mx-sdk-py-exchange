import concurrent.futures
import random
import sys
import time
import pytest
from itertools import count
from typing import List
from argparse import ArgumentParser

import config
from context import Context
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from events.event_generators import (generate_add_initial_liquidity_event,
                                                       generate_add_liquidity_event,
                                                       generateEnterFarmEvent,
                                                       generateEnterMetastakeEvent,
                                                       generateClaimMetastakeRewardsEvent,
                                                       generateExitMetastakeEvent)
from utils.utils_tx import ESDTToken
from utils.utils_chain import nominated_amount, \
    get_token_details_for_address
from utils.utils_generic import log_step_fail, log_step_pass, log_condition_assert, TestStepConditions
from arrows.stress.send_token_from_minter import main as send_token_from_minter
from arrows.stress.shared import get_shard_of_address
from erdpy.accounts import Account


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--threads", required=False, default="1")  # number of concurrent threads to execute operations
    parser.add_argument("--repeats", required=False, default="1")  # number of total operations to execute; 0 - infinite
    parser.add_argument("--skip-minting", action="store_true", default=True)
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
    amount = nominated_amount(1000000)

    for token in context.deploy_structure.tokens:
        print(f"Funding each account with {amount} {token} tokens.")
        args = [f'--proxy={proxy_url}', f'--accounts={accounts}',
                f'--minter={minter}', f'--token={token}', f'--amount-atoms={amount}']
        send_token_from_minter(args)
        time.sleep(7)


def scenarios(context: Context, threads: int, repeats: int):
    accounts = context.accounts.get_all()

    if threads == 1:
        """Sequential run"""
        for _ in range(repeats if repeats != 0 else 9999):
            scenarios_per_account(context, random.choice(accounts))
    elif threads > 1:
        """ Concurential run """
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            jobs = min(threads, repeats) if repeats != 0 else threads
            finished_jobs = 0
            futures = [[executor.submit(scenarios_per_account, context, random.choice(accounts))
                        for _ in range(jobs)]]

            # feed the thread workers as they complete each job
            while finished_jobs < repeats or repeats == 0:
                try:
                    for _ in concurrent.futures.as_completed(futures):
                        finished_jobs += 1
                        log_step_pass(f"Finished {finished_jobs} repeats.")

                        if repeats == 0 or repeats > finished_jobs:
                            # spawn a new job
                            futures.append(executor.submit(scenarios_per_account, context, random.choice(accounts)))
                except Exception as ex:
                    pass
    else:
        log_step_fail(f"Number of threads must be minimum 1!")
        return


def scenarios_per_account(context: Context, account: Account):
    min_time = 2
    max_time = 10
    deployer_shard = get_shard_of_address(context.deployer_account.address)
    sleep_time = config.CROSS_SHARD_DELAY if get_shard_of_address(account.address) is not deployer_shard \
        else 1

    account.sync_nonce(context.network_provider.proxy)

    simple_lock_energy_contract: SimpleLockEnergyContract
    simple_lock_energy_contract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]

    # unlock early - pass
    test_unlock_early_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # lock tokens with valid lock option - pass
    test_lock_tokens_valid_option_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # lock tokens with valid lock option - pass
    test_lock_tokens_valid_option_2(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # lock tokens with invalid lock option - fail
    test_lock_tokens_invalid_option_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # lock other tokens - fail
    test_lock_other_tokens_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # unlock early - pass
    test_unlock_early_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # unlock early w. invalid token - fail
    test_unlock_early_invalid_token_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # unlock early w. invalid similar token - fail
    test_unlock_early_invalid_token_2(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # reduce lock - fail
    test_reduce_lock_invalid_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # reduce lock - fail
    test_reduce_lock_invalid_too_much_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # reduce lock - pass
    test_reduce_and_unlock_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # reduce lock - pass
    test_reduce_lock_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    # unlock tokens - fail
    test_unlock_invalid_1(context, account, simple_lock_energy_contract)
    time.sleep(sleep_time)

    wait_time = random.randint(min_time, max_time)
    print(f'Finished repeat execution. Waiting for {wait_time}s.')
    time.sleep(wait_time)


def test_lock_tokens_valid_option_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.base_token, 0, nominated_amount(1000))
    expected_token = ESDTToken(simple_lock_energy_contract.locked_token, 1, token.token_amount)
    args = [[token], 2]

    tx_hash = simple_lock_energy_contract.lock_tokens(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "lock tokens with valid lock option tx pass")
    teststep.add_condition(context.network_provider.check_for_burn_operation(tx_hash, token),
                           "base token burn")
    teststep.add_condition(context.network_provider.check_for_add_quantity_operation(tx_hash, expected_token),
                           "add quantity locked token")
    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, expected_token,
                                                                                 destination=account.address.bech32()),
                           "send locked token to user")
    teststep.assert_conditions()


def test_lock_tokens_valid_option_2(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.base_token, 0, nominated_amount(1000))
    expected_token = ESDTToken(simple_lock_energy_contract.locked_token, 2, token.token_amount)
    args = [[token], 6]

    tx_hash = simple_lock_energy_contract.lock_tokens(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "lock tokens with valid lock option tx pass")
    teststep.add_condition(context.network_provider.check_for_burn_operation(tx_hash, token),
                           "base token burn")
    teststep.add_condition(context.network_provider.check_for_add_quantity_operation(tx_hash, expected_token),
                           "add quantity locked token")
    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, expected_token,
                                                                                 destination=account.address.bech32()),
                           "send locked token to user")
    teststep.assert_conditions()


def test_lock_tokens_invalid_option_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.base_token, 0, nominated_amount(100))
    args = [[token], 5]

    tx_hash = simple_lock_energy_contract.lock_tokens(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "lock tokens with invalid lock option")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Invalid lock choice"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_lock_other_tokens_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(context.deploy_structure.tokens[1], 0, nominated_amount(100))
    args = [[token], 2]

    tx_hash = simple_lock_energy_contract.lock_tokens(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "lock other tokens")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Invalid payment token"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_unlock_early_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.locked_token, 2, nominated_amount(100))
    expected_token = ESDTToken(simple_lock_energy_contract.base_token, 0, token.token_amount)
    args = [[token]]

    tx_hash = simple_lock_energy_contract.unlock_early(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "unlock early")
    teststep.add_condition(context.network_provider.check_for_burn_operation(tx_hash, token),
                           "locked token burn")
    teststep.add_condition(context.network_provider.check_for_mint_operation(tx_hash, expected_token),
                           "mint base token")
    # TODO: calculate burned penalties, rest of penalties sent to fees collector, rest sent to user
    penalty = context.simple_lock_tracker.get_expected_penalty(token)

    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, expected_token,
                                                                                 destination=account.address.bech32()),
                           "send base token to user")
    teststep.assert_conditions()


def test_unlock_early_invalid_token_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.base_token, 0, nominated_amount(100))
    args = [[token]]

    tx_hash = simple_lock_energy_contract.unlock_early(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "unlock early with invalid token")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Invalid payment token"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_unlock_early_invalid_token_2(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    forged_contract: SimpleLockEnergyContract
    forged_contract = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[1]
    # create forged token
    token = ESDTToken(context.deploy_structure.tokens[0], 0, nominated_amount(1))
    args = [[token], 30]
    forged_token = ESDTToken(forged_contract.locked_token, 1, 1)
    tx_hash = forged_contract.lock_tokens(account, context.network_provider.proxy, args)
    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "lock forged token pass")
    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, forged_token,
                                                                                 destination=account.address.bech32()),
                           "send base token to user")
    teststep.assert_conditions()

    # attempt unlocking of forged token in tested contract
    token = forged_token
    args = [[token]]
    tx_hash = simple_lock_energy_contract.unlock_early(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "unlock early with invalid similar token tx fail")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Invalid payment token"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_reduce_lock_invalid_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.locked_token, 2, nominated_amount(100))
    args = [[token], 1]

    tx_hash = simple_lock_energy_contract.reduce_lock(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "reduce lock tx fail")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "May only reduce by multiples of months (30 epochs)"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_reduce_lock_invalid_too_much_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.locked_token, 1, nominated_amount(100))
    args = [[token], 3]

    tx_hash = simple_lock_energy_contract.reduce_lock(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "reduce lock tx fail")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Invalid epochs to reduce"),
                           "tx fail with expected error")
    teststep.assert_conditions()


def test_reduce_and_unlock_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    # check complete unlocking via reduce (when reduce period = remaining period)
    token = ESDTToken(simple_lock_energy_contract.locked_token, 1, nominated_amount(100))
    expected_token = ESDTToken(simple_lock_energy_contract.base_token, 0, token.token_amount)
    args = [[token], 2]

    tx_hash = simple_lock_energy_contract.reduce_lock(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "reduce lock tx pass")
    teststep.add_condition(context.network_provider.check_for_burn_operation(tx_hash, token),
                           "locked token burn")
    teststep.add_condition(context.network_provider.check_for_mint_operation(tx_hash, expected_token),
                           "mint base token")
    # TODO: apply expected penalty calculation - burned penalties, rest of penalties sent to fees collector, rest sent to user
    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, expected_token,
                                                                                 destination=account.address.bech32()),
                           "send new base token to user")
    teststep.assert_conditions()


def test_reduce_lock_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.locked_token, 2, nominated_amount(100))
    expected_token = ESDTToken(simple_lock_energy_contract.locked_token, 1, token.token_amount)
    penalties_token = ESDTToken(simple_lock_energy_contract.base_token, 0, token.token_amount)
    args = [[token], 3]

    tx_hash = simple_lock_energy_contract.reduce_lock(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(context.network_provider.check_simple_tx_status(tx_hash),
                           "reduce lock tx pass")
    teststep.add_condition(context.network_provider.check_for_burn_operation(tx_hash, token),
                           "locked token burn")
    # TODO: apply expected penalty calculation - mint, burned penalties, rest of penalties sent to fees collector, rest sent to user
    teststep.add_condition(context.network_provider.check_for_add_quantity_operation(tx_hash, expected_token),
                           "add quantity new locked token")
    teststep.add_condition(context.network_provider.check_for_add_quantity_operation(tx_hash, penalties_token),
                           "mint base token")
    teststep.add_condition(context.network_provider.check_for_transfer_operation(tx_hash, expected_token,
                                                                                 destination=account.address.bech32()),
                           "send new locked token to user")
    teststep.assert_conditions()


def test_unlock_invalid_1(context, account: Account, simple_lock_energy_contract: SimpleLockEnergyContract):
    token = ESDTToken(simple_lock_energy_contract.locked_token, 1, nominated_amount(100))
    args = [[token]]

    tx_hash = simple_lock_energy_contract.unlock_tokens(account, context.network_provider.proxy, args)

    teststep = TestStepConditions()
    teststep.add_condition(not context.network_provider.check_simple_tx_status(tx_hash),
                           "unlock tokens tx fail")
    teststep.add_condition(context.network_provider.check_for_error_operation(tx_hash, "Cannot unlock yet"),
                           "tx fail with expected error")
    teststep.assert_conditions()


if __name__ == "__main__":
    main(sys.argv[1:])
