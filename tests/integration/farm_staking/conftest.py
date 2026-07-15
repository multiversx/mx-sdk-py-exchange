"""
Farm-package pytest fixtures.

Overrides the primary test user (`alice`) so that every farm test uses the
same shard-1 account. Farm operations (enter/exit/claim, boosted yields) are
exercised consistently from a single, deterministic shard-1 account; multi-user
tests still get distinct `bob`/`charlie` accounts from the shared pool.
"""

import pytest

from tests.conftest import _ensure_account_has_egld
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import _ensure_deployer_has_egld
from utils.logger import get_logger
from utils.utils_chain import Account, nominated_amount
from utils.utils_chain import WrapperAddress as Address
from utils.utils_tx import endpoint_call

logger = get_logger(__name__)


@pytest.fixture
def alice(shard1_account) -> Account:
    """
    Primary farm-test user, pinned to a shard-1 account.

    This overrides the session-wide `alice` fixture for the farm package only,
    so all farm tests share the same shard-1 account as their main actor.
    """
    return shard1_account


@pytest.fixture
def bob(dex_context, test_environment, network_providers) -> Account:
    """
    Primary farm-test user, pinned to a shard-1 account.

    This overrides the session-wide `alice` fixture for the farm package only,
    so all farm tests share the same shard-1 account as their main actor.
    """
    shard1_accounts = dex_context.accounts.get_in_shard(1)
    if not shard1_accounts:
        pytest.skip("No test account available in shard 1")

    account = shard1_accounts[1]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(account, test_environment, network_providers.proxy)

    account.sync_nonce(network_providers.proxy)
    return account


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
