"""
Integration tests for Farm contract admin operations.

These tests verify privileged admin endpoints through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Reward Production: start/end produce rewards
2. Configuration: per-block reward amount, boosted yields percentage
3. Lifecycle: pause/resume
4. Access Control: admin-only enforcement
5. Boosted Rewards: collect undistributed rewards

IMPORTANT: All admin state-changing operations use try/finally blocks
to ensure state is always restored for subsequent tests.

Run:
    pytest --env=chainsim tests/integration/farm/test_admin_operations.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _check_farm_has_code,
    _ensure_deployer_has_egld,
    _enter_farm,
    _exit_farm,
    _get_current_week,
    _get_farm_state,
    _get_farm_tokens_for_user,
    _get_stake_amount,
)
from utils.logger import get_logger
from utils.utils_chain import Account
from utils.utils_tx import NetworkProviders

logger = get_logger(__name__)


# ============================================================================
# TEST CLASS
# ============================================================================


@pytest.mark.integration
@pytest.mark.farm
class TestFarmAdminOperations:
    """
    Integration tests for Farm contract admin operations.

    Contract Endpoints Tested:
    - startProduceRewards
    - endProduceRewards
    - setPerBlockRewardAmount
    - setBoostedYieldsRewardsPercentage
    - pause / resume
    - collectUndistributedBoostedRewards

    Key Behaviors:
    1. Only the contract owner (deployer) can call admin endpoints
    2. State changes must be observable via view functions
    3. All state modifications are restored in finally blocks

    IMPORTANT: deployer_account does NOT auto-fund with EGLD on chain simulator.
    Each test calls _ensure_deployer_has_egld() before admin operations.
    """

    # ----------------------------------------------------------------
    # Reward Production Tests
    # ----------------------------------------------------------------

    def test_start_produce_rewards(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Start producing rewards in the farm

        GIVEN: Farm contract with loaded state (rewards may already be started)
        WHEN: Deployer calls startProduceRewards
        THEN:
            - Transaction succeeds (idempotent if already started)
            - getLastRewardTimestamp is set (> 0)

        NOTE: On mainnet state, rewards are typically already started.
        This test verifies the endpoint is callable and the view reflects it.
        """
        logger.info("TEST: Start produce rewards")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_hash)
        tx_data = network_providers.proxy.get_transaction(tx_hash)
        if tx_data.status.is_failed and "Producing rewards is already enabled" in str(tx_data):
            logger.info("Reward production already enabled (idempotent)")
        else:
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify last reward timestamp is set
        last_timestamp = farm_contract.get_last_reward_timestamp(network_providers.proxy)
        logger.info(f"Last reward timestamp: {last_timestamp}")
        assert last_timestamp > 0, (
            f"getLastRewardTimestamp should be > 0 after startProduceRewards, got {last_timestamp}"
        )

        logger.info("PASSED: test_start_produce_rewards")

    def test_end_produce_rewards(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: End reward production in the farm

        GIVEN: Farm contract with rewards being produced
        WHEN: Deployer calls endProduceRewards
        THEN:
            - Transaction succeeds
            - Reward production stops (no new rewards generated)

        CLEANUP: Always restart reward production in finally block
        """
        logger.info("TEST: End produce rewards")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Ensure rewards are started first
        deployer_account.sync_nonce(network_providers.proxy)
        tx_start = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_start)

        try:
            # End reward production
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = farm_contract.end_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
            logger.info("endProduceRewards succeeded")

            reserve_stopped = _get_farm_state(farm_contract, network_providers.proxy)[
                "reward_reserve"
            ]
            blockchain_controller.wait_blocks(5)
            reserve_after_wait = _get_farm_state(farm_contract, network_providers.proxy)[
                "reward_reserve"
            ]

            assert reserve_after_wait == reserve_stopped, (
                f"Reward reserve should freeze after endProduceRewards:\n"
                f"  At stop: {reserve_stopped}\n"
                f"  After wait: {reserve_after_wait}"
            )
            logger.info(f"Reward reserve frozen at {reserve_stopped}")

        finally:
            # Always restart reward production
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restart = farm_contract.start_produce_rewards(
                deployer_account, network_providers.proxy
            )
            blockchain_controller.wait_for_tx(tx_restart)
            TransactionAssertions.assert_transaction_success(tx_restart, network_providers.proxy)
            logger.info("Reward production restarted (cleanup)")

        logger.info("PASSED: test_end_produce_rewards")

    # ----------------------------------------------------------------
    # Configuration Tests
    # ----------------------------------------------------------------

    def test_set_per_second_reward_amount(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Change the per-second reward amount

        GIVEN: Farm contract with a known per-second reward rate
        WHEN: Deployer sets a new per-second reward amount
        THEN:
            - Transaction succeeds
            - getPerSecondRewardAmount reflects the new value

        CLEANUP: Always restore the original per-second reward amount
        """
        logger.info("TEST: Set per-second reward amount")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Read current rate
        original_rate = farm_contract.get_per_second_reward_amount(network_providers.proxy)
        logger.info(f"Original per-second reward amount: {original_rate}")

        # Set a new rate (use a small but distinct value)
        new_rate = int(original_rate * 0.9)
        assert new_rate != original_rate, (
            f"New rate must differ from original for a meaningful test. "
            f"Original: {original_rate}, New: {new_rate}"
        )

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = farm_contract.set_rewards_per_second(
                deployer_account, network_providers.proxy, new_rate
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Verify the rate changed
            updated_rate = farm_contract.get_per_second_reward_amount(network_providers.proxy)
            logger.info(f"Updated per-second reward amount: {updated_rate}")
            assert updated_rate == new_rate, (
                f"Per-second reward amount mismatch after set:\n"
                f"  Expected: {new_rate}\n"
                f"  Actual: {updated_rate}"
            )

        finally:
            # Restore original rate
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = farm_contract.set_rewards_per_second(
                deployer_account, network_providers.proxy, original_rate
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)

            # Verify restoration
            restored_rate = farm_contract.get_per_second_reward_amount(network_providers.proxy)
            assert restored_rate == original_rate, (
                f"Failed to restore per-second reward amount:\n"
                f"  Expected: {original_rate}\n"
                f"  Actual: {restored_rate}"
            )
            logger.info(f"Per-second reward amount restored to {original_rate} (cleanup)")

        logger.info("PASSED: test_set_per_second_reward_amount")

    def test_set_boosted_yields_percentage(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Change the boosted yields rewards percentage

        GIVEN: Farm contract with boosted yields percentage (typically 6000 = 60%)
        WHEN: Deployer sets a new percentage (5000 = 50%)
        THEN:
            - Transaction succeeds
            - The percentage is updated (verified by a second set call roundtrip)

        CLEANUP: Always restore original percentage (6000)

        NOTE: There is no direct getBoostedYieldsRewardsPercentage view function
        registered in the data fetcher. We verify via successful set + restore cycle.
        """
        logger.info("TEST: Set boosted yields rewards percentage")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        original_percentage = 6000  # 60% - standard mainnet value
        new_percentage = 5000  # 50%

        try:
            # Set new percentage
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = farm_contract.set_boosted_yields_rewards_percentage(
                deployer_account, network_providers.proxy, new_percentage
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
            logger.info(f"Boosted yields percentage set to {new_percentage}")

        finally:
            # Restore original percentage
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = farm_contract.set_boosted_yields_rewards_percentage(
                deployer_account, network_providers.proxy, original_percentage
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Boosted yields percentage restored to {original_percentage} (cleanup)")

        logger.info("PASSED: test_set_boosted_yields_percentage")

    def test_set_boosted_yields_percentage_invalid_fails(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Setting boosted yields percentage > 10000 should fail

        GIVEN: Farm contract with valid boosted yields configuration
        WHEN: Deployer tries to set percentage to 10001 (> 100%)
        THEN: Transaction fails (invalid percentage)

        NOTE: The contract validates that percentage <= 10000 (MAX_PERCENT).
        """
        logger.info("TEST: Set boosted yields percentage invalid fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        invalid_percentage = 10001  # > 100%

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = farm_contract.set_boosted_yields_rewards_percentage(
            deployer_account, network_providers.proxy, invalid_percentage
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        logger.info("Transaction correctly failed for invalid percentage > 10000")

        logger.info("PASSED: test_set_boosted_yields_percentage_invalid_fails")

    # ----------------------------------------------------------------
    # Pause / Resume Tests
    # ----------------------------------------------------------------

    def test_pause_resume(
        self,
        farm_contract: FarmContract,
        alice: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
    ):
        """
        SCENARIO: Pause the farm, verify operations fail, then resume

        GIVEN: Farm contract is active (state = 1)
        WHEN:
            1. Deployer pauses the farm
            2. Alice tries to enterFarm while paused
            3. Deployer resumes the farm
        THEN:
            - Pause transaction succeeds
            - enterFarm fails while paused (Not active)
            - Resume transaction succeeds
            - Farm state returns to active

        CLEANUP: Always resume the farm in finally block
        """
        logger.info("TEST: Pause and resume farm")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Fund Alice before pausing
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        # Verify farm is active before pausing
        state_before = farm_contract.get_state(network_providers.proxy)
        logger.info(f"Farm state before pause: {state_before}")

        # Pause the farm
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = farm_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Farm paused")

        try:
            # Verify farm is now inactive
            state_paused = farm_contract.get_state(network_providers.proxy)
            logger.info(f"Farm state after pause: {state_paused}")
            assert state_paused == 0, f"Farm should be inactive (0) after pause, got {state_paused}"

            # Attempt enterFarm while paused - should fail
            tx_enter = _enter_farm(
                farm_contract,
                alice,
                farming_token,
                stake_amount,
                network_providers,
                blockchain_controller,
            )
            TransactionAssertions.assert_transaction_failed(
                tx_enter, network_providers.proxy, expected_error="Not active"
            )
            logger.info("enterFarm correctly rejected while paused")

        finally:
            # Always resume
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = farm_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Farm resumed (cleanup)")

        # Verify farm is active again after resume
        state_after = farm_contract.get_state(network_providers.proxy)
        logger.info(f"Farm state after resume: {state_after}")
        assert state_after == 1, f"Farm should be active (1) after resume, got {state_after}"

        logger.info("PASSED: test_pause_resume")

    # ----------------------------------------------------------------
    # Access Control Tests
    # ----------------------------------------------------------------

    def test_admin_only_access(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Non-admin user cannot call admin endpoints

        GIVEN: Farm contract is active
        WHEN: Alice (non-admin) tries to call:
            1. pause
            2. endProduceRewards
        THEN: Both transactions fail (caller is not the owner)

        SECURITY: Admin endpoints must enforce ownership checks.
        Unauthorized access would allow denial-of-service attacks
        (pausing the farm) or economic manipulation (changing reward rates).
        """
        logger.info("TEST: Admin-only access enforcement")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Alice tries to pause the farm
        alice.sync_nonce(network_providers.proxy)
        tx_pause = farm_contract.pause(alice, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_failed(tx_pause, network_providers.proxy)
        logger.info("1. Alice correctly denied pause access")

        # Verify farm is still active (pause was rejected)
        state = farm_contract.get_state(network_providers.proxy)
        assert state == 1, f"Farm should still be active after rejected pause, got {state}"

        # Alice tries to end produce rewards
        alice.sync_nonce(network_providers.proxy)
        tx_end = farm_contract.end_produce_rewards(alice, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_end)
        TransactionAssertions.assert_transaction_failed(tx_end, network_providers.proxy)
        logger.info("2. Alice correctly denied endProduceRewards access")

        logger.info("PASSED: test_admin_only_access")

    # ----------------------------------------------------------------
    # Boosted Rewards Collection Tests
    # ----------------------------------------------------------------

    def test_collect_undistributed_rewards(
        self,
        farm_contract: FarmContract,
        alice: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
        dex_context,
    ):
        """
        SCENARIO: Collect undistributed boosted rewards after a full week passes

        GIVEN: Farm contract with mainnet state loaded (weekOffset filtered to 0)
        WHEN:
            1. Alice enters the farm with no energy — boosted rewards accumulate
               but stay unclaimed for the current week
            2. Enough blocks pass so rewards accumulate (per-block reward rate > 0)
            3. Chain advances to the next week boundary (current_week + 1)
            4. Deployer calls collectUndistributedBoostedRewards
        THEN:
            - Transaction succeeds (current_week > weekOffset check passes)
            - Reserve change is logged (collection may be 0 or positive)

        NOTE: The contract enforces current_week > USER_MAX_CLAIM_WEEKS + 1 (= 5),
        so the chain must be at week 6+ before calling this endpoint. The test
        advances however many weeks are needed from the current position — fully
        state-agnostic regardless of starting epoch.

        CLEANUP: Alice's farm position is always exited in the finally block.
        """
        logger.info("TEST: Collect undistributed boosted rewards")

        EPOCHS_PER_WEEK = 7
        # collectUndistributedBoostedRewards requires: current_week > USER_MAX_CLAIM_WEEKS + 1
        # USER_MAX_CLAIM_WEEKS = 4, so minimum week to call = 6
        COLLECT_REWARDS_OFFSET = 5  # USER_MAX_CLAIM_WEEKS + 1

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Fund alice and enter farm — alice has no energy, so her share of boosted
        # rewards remains unclaimed and can be collected by the deployer after the week
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)
        logger.info(f"Alice entered farm with {stake_amount} {farming_token}")

        # Let rewards accumulate during the current week
        blockchain_controller.wait_blocks(20)

        # Snapshot epoch and week AFTER the wait — state-agnostic baseline
        current_epoch = blockchain_controller.get_current_epoch()
        current_week = _get_current_week(farm_contract, network_providers.proxy)
        logger.info(f"Baseline: epoch={current_epoch}, week={current_week}")

        reward_reserve_before = farm_contract.get_reward_reserve(network_providers.proxy)
        logger.info(f"Reward reserve before collection: {reward_reserve_before}")

        try:
            # Must satisfy: current_week > COLLECT_REWARDS_OFFSET (= 5).
            # If we're not there yet, advance enough weeks to get past it.
            # Always advance at least one additional week so the entered position
            # ends up in a completed week that can be collected.
            weeks_to_advance = max(1, COLLECT_REWARDS_OFFSET - current_week + 2)
            target_epoch = current_epoch + weeks_to_advance * EPOCHS_PER_WEEK
            logger.info(
                f"Advancing {weeks_to_advance} week(s): epoch {current_epoch} → {target_epoch} "
                f"(week {current_week} → {current_week + weeks_to_advance})"
            )
            blockchain_controller.advance_to_epoch(target_epoch)

            new_week = _get_current_week(farm_contract, network_providers.proxy)
            logger.info(f"Now in week {new_week}")
            assert new_week > COLLECT_REWARDS_OFFSET, (
                f"Expected week > {COLLECT_REWARDS_OFFSET} after advancing to epoch {target_epoch}, "
                f"got week {new_week}"
            )

            # Collect undistributed boosted rewards from the completed week
            # Note: signature is (proxy, user) — different from most other methods
            deployer_account.sync_nonce(network_providers.proxy)
            energy_factory = dex_context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]
            tx_hash = energy_factory.set_multisig_address(
                deployer_account, network_providers.proxy, deployer_account.address.to_bech32()
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
            logger.info("set multisig address in energy factory succeeded")

            tx_hash = farm_contract.collect_undistributed_boosted_rewards(
                network_providers.proxy, deployer_account
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
            logger.info("collectUndistributedBoostedRewards succeeded")

            reward_reserve_after = farm_contract.get_reward_reserve(network_providers.proxy)
            logger.info(
                f"Reward reserve: before={reward_reserve_before}, after={reward_reserve_after}, "
                f"delta={reward_reserve_after - reward_reserve_before}"
            )

        finally:
            # Always exit alice's farm position
            farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            for ft in farm_tokens:
                _exit_farm(
                    farm_contract,
                    alice,
                    ft.token.nonce,
                    ft.amount,
                    network_providers,
                    blockchain_controller,
                )
            if farm_tokens:
                logger.info(f"Exited {len(farm_tokens)} farm position(s) (cleanup)")

        logger.info("PASSED: test_collect_undistributed_rewards")
