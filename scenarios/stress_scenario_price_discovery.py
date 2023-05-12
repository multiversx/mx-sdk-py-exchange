import logging
import random
import time

from context import (Context)
from contracts.price_discovery_contract import PriceDiscoveryContract
from events.event_generators import generate_deposit_pd_liquidity_event, \
    generate_withdraw_pd_liquidity_event, generate_redeem_pd_liquidity_event, \
    generate_random_deposit_pd_liquidity_event, generate_random_withdraw_pd_liquidity_event, \
    generate_random_redeem_pd_liquidity_event


def main():
    logging.basicConfig(level=logging.ERROR)
    context = Context()
    create_nonce_file(context)

    price_discovery_contract: PriceDiscoveryContract
    price_discovery_contract = context.get_random_price_discovery_contract()

    print(f"Started waiting for deposit start block: {price_discovery_contract.start_block}")
    context.network_provider.wait_for_nonce_in_shard(1, price_discovery_contract.start_block)  # TODO: nice shard

    for i in range(1, context.numEvents):
        # generate_random_event(context)
        generate_deposit_pd_liquidity_event(context, context.accounts.get_all()[0], price_discovery_contract)
        time.sleep(6)
        generate_withdraw_pd_liquidity_event(context, context.accounts.get_all()[0], price_discovery_contract)
        time.sleep(6)

    deposit_end_block = price_discovery_contract.start_block + \
        price_discovery_contract.no_limit_phase_duration_blocks + \
        price_discovery_contract.linear_penalty_phase_duration_blocks + \
        price_discovery_contract.fixed_penalty_phase_duration_blocks

    print(f"Started waiting for deposit end period: {deposit_end_block}")
    context.network_provider.wait_for_nonce_in_shard(deposit_end_block)

    for i in range(1, context.numEvents):
        generate_redeem_pd_liquidity_event(context, context.accounts.get_all()[0], price_discovery_contract)


def create_nonce_file(context: Context):
    accounts = context.accounts.get_all()
    for account in accounts:
        account.sync_nonce(context.network_provider.proxy)
    context.accounts.store_nonces(context.nonces_file)


def generate_random_event(context: Context):
    events = {
        generate_random_deposit_pd_liquidity_event: 6,
        generate_random_withdraw_pd_liquidity_event: 2,
        generate_random_redeem_pd_liquidity_event: 6
    }

    eventFunction = weighted_random_choice(events)
    eventFunction(context)


def weighted_random_choice(choices):
    max = sum(choices.values())
    pick = random.uniform(0, max)
    current = 0
    for key, value in choices.items():
        current += value
        if current > pick:
            return key


if __name__ == "__main__":
    main()
