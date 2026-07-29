"""
Farm-staking-package pytest fixtures.

"""

import pytest

from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import _check_staking_has_code, _ensure_deployer_has_egld
from tests.integration.shared_fixtures import alice, bob
from utils.logger import get_logger
from utils.utils_chain import WrapperAddress as Address
from utils.utils_chain import nominated_amount
from utils.utils_tx import endpoint_call

__all__ = ["alice", "bob", "seed_staking_rewards"]

logger = get_logger(__name__)


def _remaining_uncollected_rewards(staking_contract, proxy) -> int:
    reward_capacity = staking_contract.get_reward_capacity(proxy)
    accumulated_rewards = staking_contract.get_accumulated_rewards(proxy)
    return max(0, reward_capacity - accumulated_rewards)


def _withdraw_seeded_rewards(
    staking_contract,
    deployer_account,
    test_environment,
    network_providers,
    blockchain_controller,
    baseline_remaining,
):
    """Withdraw the reward capacity this fixture seeded, down to the baseline.

    withdrawRewards aggregates pending rewards before validating the requested
    amount, so any amount sized from a view read is stale by whatever accrued in
    between. The fixture only seeds when the pre-existing reserve is nearly
    depleted, so there is no headroom to absorb that and a request for the full
    excess is rejected. Stopping reward production first settles the pending
    rewards and halts further accrual, which makes the views exact and lets a
    single withdrawal restore the baseline precisely.
    """
    _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

    was_producing = staking_contract.get_produce_rewards_enabled(network_providers.proxy)
    if was_producing:
        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = staking_contract.end_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

    try:
        # Re-read after the freeze: endProduceRewards just aggregated the
        # pending rewards, so this is the settled figure the contract will
        # check the withdrawal against.
        outstanding = _remaining_uncollected_rewards(
            staking_contract, network_providers.proxy
        ) - baseline_remaining
        if outstanding <= 0:
            return

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = endpoint_call(
            network_providers.proxy,
            50_000_000,
            deployer_account,
            Address(staking_contract.address),
            "withdrawRewards",
            [outstanding],
        )
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
    finally:
        # Always hand the contract back producing rewards, even if the
        # withdrawal failed — leaving it frozen would silently zero out
        # rewards for every later test in the session.
        if was_producing:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking_contract.start_produce_rewards(
                deployer_account, network_providers.proxy
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)


@pytest.fixture()
def seed_staking_rewards(
    staking_contract,
    deployer_account,
    test_environment,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
):
    if not _check_staking_has_code(staking_contract, network_providers.proxy):
        pytest.skip("Staking contract bytecode not loaded on chain simulator")

    remained_rewards = _remaining_uncollected_rewards(staking_contract, network_providers.proxy)
    minimum_remaining = nominated_amount(100_000)
    topup_amount = nominated_amount(100_000)
    farming_token = staking_contract.farming_token

    if remained_rewards < minimum_remaining:
        logger.info(
            f"Reward reserve depleted (reserve={remained_rewards}), "
            f"topping up staking contract with {topup_amount} {farming_token}"
        )

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)
        ensure_esdt_amounts(deployer_account, {farming_token: topup_amount})

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = staking_contract.topup_rewards(
            deployer_account,
            network_providers.proxy,
            topup_amount,
        )
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        logger.info("✓ Staking contract reward capacity topped up")

    yield

    remaining_after = _remaining_uncollected_rewards(staking_contract, network_providers.proxy)
    if remaining_after <= remained_rewards:
        return

    _withdraw_seeded_rewards(
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        remained_rewards,
    )
