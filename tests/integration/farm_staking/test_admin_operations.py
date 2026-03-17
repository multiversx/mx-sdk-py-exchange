"""
Farm Staking Integration Tests - Category 9: Admin Operations

Tests privileged admin endpoints:
- startProduceRewards / endProduceRewards
- setPerBlockRewardAmount (per-second reward rate)
- setMaxApr
- setMinUnbondEpochs (including invalid > 30)
- topUpRewards
- withdrawRewards (raw endpoint call — not in Python class)
- pause / resume
All admin state changes use try/finally to restore state.
Deployer must be funded with EGLD before each admin test.

Coverage: 10 tests (P1)
"""

import pytest
from utils.logger import get_logger
from utils.utils_chain import nominated_amount
from utils.utils_tx import endpoint_call
from utils.utils_chain import WrapperAddress as Address
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _claim_rewards,
    _compound_rewards,
    _get_farm_tokens_for_user,
    _ensure_deployer_has_egld,
)

logger = get_logger(__name__)


def _require_supported_view(value: int, view_name: str) -> int:
    if value == -1:
        pytest.skip(f"{view_name} view unsupported on this staking contract")
    return value


def _is_already_enabled_error(tx_data) -> bool:
    return tx_data.status.is_failed and "Producing rewards is already enabled" in str(tx_data)


class TestAdminOperations:
    """Test suite for staking contract admin operations"""

    def test_start_produce_rewards(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """startProduceRewards: transaction succeeds, last_reward_timestamp updated"""
        logger.info("TEST: Start produce rewards")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        last_ts_before = staking_contract.get_last_reward_timestamp(network_providers.proxy)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_hash)
        tx_data = network_providers.proxy.get_transaction(tx_hash)

        # Accept both success and "already enabled" as valid outcomes.
        # On loaded mainnet state, reward production is typically already running.
        if _is_already_enabled_error(tx_data):
            logger.info("Reward production already enabled (idempotent)")
        else:
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify timestamp is set (production is active)
        last_ts = staking_contract.get_last_reward_timestamp(network_providers.proxy)
        assert last_ts >= last_ts_before, (
            f"last_reward_timestamp should not decrease after start:\n"
            f"  Before: {last_ts_before}\n"
            f"  After: {last_ts}"
        )

        logger.info(f"✓ startProduceRewards: last_reward_timestamp={last_ts}")

    def test_end_produce_rewards(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """endProduceRewards: transaction succeeds, RPS freezes"""
        logger.info("TEST: End produce rewards")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_start = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_start)
        tx_start_data = network_providers.proxy.get_transaction(tx_start)
        if not _is_already_enabled_error(tx_start_data):
            TransactionAssertions.assert_transaction_success(tx_start, network_providers.proxy)

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_stop = staking_contract.end_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_stop)
            TransactionAssertions.assert_transaction_success(tx_stop, network_providers.proxy)

            rps_stopped = _require_supported_view(
                staking_contract.get_reward_per_share(network_providers.proxy),
                "getRewardPerShare",
            )
            blockchain_controller.wait_blocks(5)
            rps_after = _require_supported_view(
                staking_contract.get_reward_per_share(network_providers.proxy),
                "getRewardPerShare",
            )

            assert rps_after == rps_stopped, (
                f"RPS should be frozen after endProduceRewards:\n"
                f"  At stop: {rps_stopped}\n"
                f"  After wait: {rps_after}"
            )
            logger.info(f"✓ endProduceRewards: RPS frozen at {rps_stopped}")

        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restart = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_restart)
            TransactionAssertions.assert_transaction_success(tx_restart, network_providers.proxy)
            logger.info("Reward production restarted (cleanup)")

    def test_set_per_second_reward_amount(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """setPerBlockRewardAmount (per-second rate): new rate reflected in view"""
        logger.info("TEST: Set per second reward amount")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        original_rate = _require_supported_view(
            staking_contract.get_per_block_reward_amount(network_providers.proxy),
            "getPerBlockRewardAmount",
        )
        new_rate = max(2, original_rate // 2) if original_rate > 4 else 2

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, new_rate
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            updated_rate = _require_supported_view(
                staking_contract.get_per_block_reward_amount(network_providers.proxy),
                "getPerBlockRewardAmount",
            )
            assert updated_rate == new_rate, (
                f"Per-second rate mismatch:\n"
                f"  Expected: {new_rate}\n"
                f"  Actual: {updated_rate}"
            )
            logger.info(f"✓ setPerBlockRewardAmount: {original_rate} → {new_rate}")

        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = staking_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, original_rate
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Rate restored to {original_rate} (cleanup)")

    def test_set_max_apr(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """setMaxApr: new APR cap reflected in view"""
        logger.info("TEST: Set max APR")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        original_apr = _require_supported_view(
            staking_contract.get_max_apr(network_providers.proxy),
            "getAnnualPercentageRewards",
        )
        new_apr = 3000  # 30% — different from typical mainnet values

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking_contract.set_max_apr(deployer_account, network_providers.proxy, new_apr)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            updated_apr = _require_supported_view(
                staking_contract.get_max_apr(network_providers.proxy),
                "getAnnualPercentageRewards",
            )
            assert updated_apr == new_apr, (
                f"Max APR mismatch:\n"
                f"  Expected: {new_apr}\n"
                f"  Actual: {updated_apr}"
            )
            logger.info(f"✓ setMaxApr: {original_apr} → {new_apr}")

        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = staking_contract.set_max_apr(deployer_account, network_providers.proxy, original_apr)
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Max APR restored to {original_apr} (cleanup)")

    def test_set_min_unbond_epochs(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """setMinUnbondEpochs: new unbond period reflected in view"""
        logger.info("TEST: Set min unbond epochs")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        original_epochs = _require_supported_view(
            staking_contract.get_min_unbond_epochs(network_providers.proxy),
            "getMinUnbondEpochs",
        )
        new_epochs = 5  # Different from typical value (10)

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking_contract.set_unbond_epochs(deployer_account, network_providers.proxy, new_epochs)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            updated_epochs = _require_supported_view(
                staking_contract.get_min_unbond_epochs(network_providers.proxy),
                "getMinUnbondEpochs",
            )
            assert updated_epochs == new_epochs, (
                f"Min unbond epochs mismatch:\n"
                f"  Expected: {new_epochs}\n"
                f"  Actual: {updated_epochs}"
            )
            logger.info(f"✓ setMinUnbondEpochs: {original_epochs} → {new_epochs}")

        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = staking_contract.set_unbond_epochs(deployer_account, network_providers.proxy, original_epochs)
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Unbond epochs restored to {original_epochs} (cleanup)")

    def test_set_min_unbond_epochs_exceeds_max_fails(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """setMinUnbondEpochs > 30 fails with 'Invalid min unbond epochs'"""
        logger.info("TEST: Set min unbond epochs exceeds max fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        _require_supported_view(
            staking_contract.get_min_unbond_epochs(network_providers.proxy),
            "getMinUnbondEpochs",
        )

        invalid_epochs = 31  # MAX_MIN_UNBOND_EPOCHS = 30

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = staking_contract.set_unbond_epochs(deployer_account, network_providers.proxy, invalid_epochs)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        # Verify unchanged
        current_epochs = _require_supported_view(
            staking_contract.get_min_unbond_epochs(network_providers.proxy),
            "getMinUnbondEpochs",
        )
        assert current_epochs != invalid_epochs, "Unbond epochs should not have changed"

        logger.info(f"✓ Setting unbond epochs to {invalid_epochs} correctly failed")

    def test_topup_rewards(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """topUpRewards: getRewardCapacity increases by deposit amount"""
        logger.info("TEST: Top up rewards")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        topup_amount = nominated_amount(10)  # 10 farming tokens
        farming_token = staking_contract.farming_token

        # Fund deployer with farming tokens for topup
        ensure_esdt_amounts(deployer_account, {farming_token: topup_amount})

        capacity_before = staking_contract.get_reward_capacity(network_providers.proxy)
        capacity_before = _require_supported_view(capacity_before, "getRewardCapacity")
        accumulated_before = staking_contract.get_accumulated_rewards(network_providers.proxy)
        remaining_before = max(0, capacity_before - accumulated_before)
        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking_contract.topup_rewards(deployer_account, network_providers.proxy, topup_amount)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            capacity_after = _require_supported_view(
                staking_contract.get_reward_capacity(network_providers.proxy),
                "getRewardCapacity",
            )

            assert capacity_after == capacity_before + topup_amount, (
                f"Capacity should increase by topup amount:\n"
                f"  Before: {capacity_before}\n"
                f"  After: {capacity_after}\n"
                f"  Topup: {topup_amount}"
            )
            logger.info(f"✓ topUpRewards: capacity {capacity_before} → {capacity_after}")
        finally:
            # withdrawRewards calls generate_aggregated_rewards internally before checking
            # amount <= remaining_uncollected. This means accumulated_rewards is updated by
            # (blocks_since_last_update * per_block_reward) at execution time, not at read time.
            # Re-read everything fresh and subtract headroom for the blocks that wait_for_tx
            # will generate (chain sim generates ~5 blocks for tx finalization).
            per_block_reward = staking_contract.get_per_block_reward_amount(network_providers.proxy)
            current_capacity = staking_contract.get_reward_capacity(network_providers.proxy)
            current_accumulated = staking_contract.get_accumulated_rewards(network_providers.proxy)
            remaining_now = max(0, current_capacity - current_accumulated)
            excess_remaining = max(0, remaining_now - remaining_before)
            # Subtract headroom for reward accumulation during tx finalization
            safe_withdraw = max(0, excess_remaining - per_block_reward * 10)
            if safe_withdraw > 0:
                deployer_account.sync_nonce(network_providers.proxy)
                tx_restore = endpoint_call(
                    network_providers.proxy,
                    50_000_000,
                    deployer_account,
                    Address(staking_contract.address),
                    "withdrawRewards",
                    [safe_withdraw],
                )
                blockchain_controller.wait_for_tx(tx_restore)
                TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)

    def test_withdraw_rewards(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """withdrawRewards: admin withdraws uncollected rewards, capacity reduces"""
        logger.info("TEST: Withdraw rewards")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token

        original_capacity = _require_supported_view(
            staking_contract.get_reward_capacity(network_providers.proxy),
            "getRewardCapacity",
        )

        try:
            # First top up to ensure there are rewards to withdraw
            topup_amount = nominated_amount(100)
            ensure_esdt_amounts(deployer_account, {farming_token: topup_amount})
            deployer_account.sync_nonce(network_providers.proxy)
            tx_topup = staking_contract.topup_rewards(deployer_account, network_providers.proxy, topup_amount)
            blockchain_controller.wait_for_tx(tx_topup)
            TransactionAssertions.assert_transaction_success(tx_topup, network_providers.proxy)

            capacity_before = _require_supported_view(
                staking_contract.get_reward_capacity(network_providers.proxy),
                "getRewardCapacity",
            )
            accumulated = staking_contract.get_accumulated_rewards(network_providers.proxy)
            per_block = staking_contract.get_per_block_reward_amount(network_providers.proxy)
            remaining = capacity_before - accumulated

            # Per-block rewards accrue continuously. Between our query and the
            # withdrawRewards TX execution, blocks are generated (for nonce sync,
            # tx processing, cross-shard finalization). This increases accumulated
            # and shrinks remaining. We must subtract a safety margin to ensure
            # the SC's own remaining >= withdraw_amount at execution time.
            safety_blocks = 50
            safety_margin = per_block * safety_blocks
            safe_remaining = remaining - safety_margin

            withdraw_amount = safe_remaining // 2
            if withdraw_amount <= 0:
                pytest.skip(
                    f"Not enough withdrawable rewards after safety margin "
                    f"(remaining={remaining}, per_block={per_block}, margin={safety_margin})"
                )

            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = endpoint_call(
                network_providers.proxy, 50_000_000, deployer_account,
                Address(staking_contract.address), "withdrawRewards", [withdraw_amount]
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # withdrawRewards reduces reward_capacity by exactly the withdrawn
            # amount. accumulated grows independently (per-block rewards) but
            # does not affect capacity.
            capacity_after = _require_supported_view(
                staking_contract.get_reward_capacity(network_providers.proxy),
                "getRewardCapacity",
            )
            assert capacity_after == capacity_before - withdraw_amount, (
                f"Capacity should decrease by withdraw amount:\n"
                f"  Before: {capacity_before}\n"
                f"  After: {capacity_after}\n"
                f"  Withdrawn: {withdraw_amount}"
            )
            logger.info(f"✓ withdrawRewards: capacity {capacity_before} → {capacity_after}")
        finally:
            # Restore capacity to original value. Topup is always safe;
            # withdraw excess is best-effort (may fail if remaining < excess
            # due to continued per-block accrual).
            current_capacity = staking_contract.get_reward_capacity(network_providers.proxy)
            if current_capacity < original_capacity:
                restore_amount = original_capacity - current_capacity
                ensure_esdt_amounts(deployer_account, {farming_token: restore_amount})
                deployer_account.sync_nonce(network_providers.proxy)
                tx_restore = staking_contract.topup_rewards(
                    deployer_account, network_providers.proxy, restore_amount
                )
                blockchain_controller.wait_for_tx(tx_restore)
                TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            elif current_capacity > original_capacity:
                reduce_amount = current_capacity - original_capacity
                deployer_account.sync_nonce(network_providers.proxy)
                tx_restore = endpoint_call(
                    network_providers.proxy,
                    50_000_000,
                    deployer_account,
                    Address(staking_contract.address),
                    "withdrawRewards",
                    [reduce_amount],
                )
                blockchain_controller.wait_for_tx(tx_restore)
                TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)

    def test_withdraw_exceeds_remaining_fails(
        self,
        staking_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
    ):
        """Withdrawing more than remaining uncollected rewards fails"""
        logger.info("TEST: Withdraw exceeds remaining fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        capacity = _require_supported_view(
            staking_contract.get_reward_capacity(network_providers.proxy),
            "getRewardCapacity",
        )
        accumulated = staking_contract.get_accumulated_rewards(network_providers.proxy)
        remaining = capacity - accumulated

        # Try to withdraw more than remaining
        exceed_amount = remaining + nominated_amount(1000)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = endpoint_call(
            network_providers.proxy, 50_000_000, deployer_account,
            Address(staking_contract.address), "withdrawRewards", [exceed_amount]
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info(
            f"✓ Excess withdrawal correctly failed: tried {exceed_amount}, remaining was {remaining}"
        )

    def test_pause_resume(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """pause/resume: operations fail when paused, succeed after resume"""
        logger.info("TEST: Pause and resume")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        state_before = _require_supported_view(
            staking_contract.get_state(network_providers.proxy),
            "getState",
        )
        assert state_before == 1, f"Contract should be active before test, got {state_before}"

        # Pause
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)

        try:
            state_paused = _require_supported_view(
                staking_contract.get_state(network_providers.proxy),
                "getState",
            )
            assert state_paused == 0, f"Expected state=0 after pause, got {state_paused}"

            # Staking while paused should fail
            tx_stake = _stake_farm(
                staking_contract, alice, farming_token, stake_amount,
                network_providers, blockchain_controller,
            )
            TransactionAssertions.assert_transaction_failed(tx_stake, network_providers.proxy)
            logger.info("  stakeFarm correctly rejected while paused")

        finally:
            # Always resume
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = staking_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)

        state_after = _require_supported_view(
            staking_contract.get_state(network_providers.proxy),
            "getState",
        )
        assert state_after == 1, f"Expected state=1 after resume, got {state_after}"

        logger.info("✓ pause/resume: operations correctly blocked when paused")

    def test_claim_rewards_while_paused_fails(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """claimRewards should fail while the contract is paused."""
        logger.info("TEST: Claim rewards while paused fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_stake = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        blockchain_controller.wait_blocks(5)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)

        try:
            tx_claim = _claim_rewards(
                staking_contract,
                alice,
                farm_token.token.nonce,
                farm_token.amount,
                network_providers,
                blockchain_controller,
            )
            TransactionAssertions.assert_transaction_failed(tx_claim, network_providers.proxy)
        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = staking_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)

        logger.info("✓ claimRewards correctly rejected while paused")

    def test_compound_rewards_while_paused_fails(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """compoundRewards should fail while the contract is paused."""
        logger.info("TEST: Compound rewards while paused fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_stake = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        blockchain_controller.wait_blocks(5)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)

        try:
            tx_compound = _compound_rewards(
                staking_contract,
                alice,
                farm_token.token.nonce,
                farm_token.amount,
                network_providers,
                blockchain_controller,
            )
            TransactionAssertions.assert_transaction_failed(tx_compound, network_providers.proxy)
        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = staking_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)

        logger.info("✓ compoundRewards correctly rejected while paused")

    def test_non_admin_pause_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
    ):
        """Non-admin accounts should not be able to pause the contract."""
        logger.info("TEST: Non-admin pause fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        alice.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(alice, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_failed(tx_pause, network_providers.proxy)

        logger.info("✓ Non-admin pause correctly rejected")

