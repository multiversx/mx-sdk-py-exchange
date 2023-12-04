import logging
import random
import time
from context import Context
from contracts.farm_contract import FarmContract
from events.event_generators import generate_add_liquidity_event, \
    generate_add_initial_liquidity_event, generate_random_swap_fixed_input, \
    generate_random_swap_fixed_output, generate_remove_liquidity_event, \
    generate_swap_fixed_input, generate_migrate_farm_event, generateAddLiquidityProxyEvent, \
    generateClaimRewardsEvent, generateEnterFarmEvent, generateEnterFarmv12Event, \
    generateExitFarmEvent, generateRandomClaimRewardsEvent, generateRandomClaimRewardsProxyEvent, \
    generateRandomCompoundRewardsEvent, generateRandomCompoundRewardsProxyEvent, \
    generateRandomEnterFarmEvent, generateRandomEnterFarmProxyEvent, generateRandomExitFarmEvent, \
    generateRandomExitFarmProxyEvent, generateRemoveLiquidityProxyEvent
from utils.utils_chain import Account


def main():
    logging.basicConfig(level=logging.ERROR)
    context = Context()
    create_nonce_file(context)

    # stress generator for SafePrice scenario
    safeprice_stress(context)

    context.results_logger.save_log()


def safeprice_stress(context: Context):
    # generate random pool transactions in both directions to stimulate the SafePrice mechanism
    min_time = 2
    max_time = 10
    pair_contract = context.get_pair_contract(0)

    generate_add_initial_liquidity_event(context, context.deployer_account, pair_contract)

    while 1:
        account = context.accounts.get_all()[0]
        generate_add_liquidity_event(context, account, pair_contract)

        print("Dump tx")
        context.set_swap_spend_limits(0.7, 0.8)
        generate_swap_fixed_input(context, account, pair_contract)

        for i in range(15):
            print("Noise tx")
            context.set_swap_spend_limits(0, 0.01)
            generate_swap_fixed_input(context, account, pair_contract)
            time.sleep(5)

        wait_time = random.randrange(min_time, max_time)
        print(f"Waiting for {wait_time}s until next swap")
        time.sleep(wait_time)


def migration_stress(context: Context):
    # generate farm events on v1.2 farm
    for i in range(1, context.numEvents):
        account = context.get_random_user_account()

        # TODO: care for the locked rewards handling
        generate_random_farm_v12_event(context, account, context.get_unlocked_farm_contract(0))
        time.sleep(7)

    # wait for migration setup
    input("Setup the migration on contracts then press Enter to continue...")

    # migrate some accounts
    account_list = context.accounts.get_all()
    migrated_accounts = random.sample(account_list, random.randrange(1, len(account_list)))  # random subset of accounts
    for account in migrated_accounts:
        generate_migrate_farm_event(context, account, context.get_unlocked_farm_contract(0))

    # context.migrate_farm_economics(0, 1, 2)

    # generate farm events on v1.4 farms
    for i in range(1, context.numEvents):
        account = random.choice(migrated_accounts)

        generate_random_farm_event(context, account, context.get_unlocked_farm_contract(1))
        time.sleep(7)
        generate_random_farm_event(context, account, context.get_unlocked_farm_contract(2))
        time.sleep(7)


def create_nonce_file(context: Context):
    context.accounts.sync_nonces(context.proxy)
    context.accounts.store_nonces(context.nonces_file)


def weighted_random_choice(choices):
    max = sum(choices.values())
    pick = random.uniform(0, max)
    current = 0
    for key, value in choices.items():
        current += value
        if current > pick:
            return key


def generateRandomEvent(context: Context):
    events = {
        generate_add_liquidity_event: 2,
        generate_remove_liquidity_event: 2,
        generate_random_swap_fixed_input: 6,
        generate_random_swap_fixed_output: 6,
        generateRandomEnterFarmEvent: 6,
        generateRandomExitFarmEvent: 4,
        generateRandomClaimRewardsEvent: 4,
        generateRandomCompoundRewardsEvent: 4,
        generateAddLiquidityProxyEvent: 3,
        generateRemoveLiquidityProxyEvent: 3,
        generateRandomEnterFarmProxyEvent: 4,
        generateRandomExitFarmProxyEvent: 2,
        generateRandomClaimRewardsProxyEvent: 2,
        generateRandomCompoundRewardsProxyEvent: 2,
    }

    eventFunction = weighted_random_choice(events)
    eventFunction(context)


def generate_random_farm_event(context: Context, user_account: Account, farm: FarmContract):
    events = {
        generateEnterFarmEvent: 6,
        generateExitFarmEvent: 2,
        generateClaimRewardsEvent: 6,
    }

    event_function = weighted_random_choice(events)
    event_function(context, user_account, farm)


def generate_random_farm_v12_event(context: Context, user_account: Account, farm: FarmContract):
    events = {
        generateEnterFarmv12Event: 6,
        generateExitFarmEvent: 2,
        generateClaimRewardsEvent: 6,
    }

    event_function = weighted_random_choice(events)
    event_function(context, user_account, farm)


if __name__ == "__main__":
    main()
