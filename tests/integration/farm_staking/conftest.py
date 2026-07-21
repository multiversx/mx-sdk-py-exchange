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
    target_amount,
):
    _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

    for attempt in range(3):
        current_remaining = _remaining_uncollected_rewards(
            staking_contract, network_providers.proxy
        )
        withdraw_amount = min(target_amount, current_remaining)
        if attempt > 0:
            withdraw_amount = withdraw_amount * 99 // 100
        if withdraw_amount <= 0:
            return

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = endpoint_call(
            network_providers.proxy,
            50_000_000,
            deployer_account,
            Address(staking_contract.address),
            "withdrawRewards",
            [withdraw_amount],
        )
        blockchain_controller.wait_for_tx(tx_hash)
        tx_data = network_providers.proxy.get_transaction(tx_hash)
        if tx_data.status.is_successful:
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
            return

        if "Withdraw amount is higher than the remaining uncollected rewards!" not in str(tx_data):
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
    excess_remaining = max(0, remaining_after - remained_rewards)
    if excess_remaining == 0:
        return

    _withdraw_seeded_rewards(
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        excess_remaining,
    )
