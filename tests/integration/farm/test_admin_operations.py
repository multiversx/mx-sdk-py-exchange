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
from events.farm_events import EnterFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.utils_chain import nominated_amount, Account, hex_to_string
from utils.utils_tx import NetworkProviders, endpoint_call
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _get_farm_state,
    _check_farm_has_code,
    _get_stake_amount,
    _enter_farm,
    _exit_farm,
    _claim_rewards,
    _claim_boosted_rewards,
    _get_farm_tokens_for_user,
    _get_minimum_farming_epochs,
    _get_farming_token_balance,
    _get_locked_token_id,
    _get_locked_tokens_for_user,
    _ensure_deployer_has_egld,
)
from utils.logger import get_logger
from multiversx_sdk import Address


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
            - getLastRewardBlockNonce is set (> 0)

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
            pytest.skip("Reward production is already enabled in the loaded mainnet state")
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify last reward block nonce is set
        last_block = farm_contract.get_last_reward_block_nonce(network_providers.proxy)
        logger.info(f"Last reward block nonce: {last_block}")
        assert last_block > 0, (
            f"getLastRewardBlockNonce should be > 0 after startProduceRewards, got {last_block}"
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

            reserve_stopped = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
            blockchain_controller.wait_blocks(5)
            reserve_after_wait = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

            assert reserve_after_wait == reserve_stopped, (
                f"Reward reserve should freeze after endProduceRewards:\n"
                f"  At stop: {reserve_stopped}\n"
                f"  After wait: {reserve_after_wait}"
            )
            logger.info(f"Reward reserve frozen at {reserve_stopped}")

        finally:
            # Always restart reward production
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restart = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_restart)
            TransactionAssertions.assert_transaction_success(tx_restart, network_providers.proxy)
            logger.info("Reward production restarted (cleanup)")

        logger.info("PASSED: test_end_produce_rewards")

    # ----------------------------------------------------------------
    # Configuration Tests
    # ----------------------------------------------------------------

    def test_set_per_block_reward_amount(
        self,
        farm_contract: FarmContract,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Change the per-block reward amount

        GIVEN: Farm contract with a known per-block reward rate
        WHEN: Deployer sets a new per-block reward amount
        THEN:
            - Transaction succeeds
            - getPerBlockRewardAmount reflects the new value

        CLEANUP: Always restore the original per-block reward amount
        """
        logger.info("TEST: Set per-block reward amount")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Read current rate
        original_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
        logger.info(f"Original per-block reward amount: {original_rate}")

        # Set a new rate (use a small but distinct value)
        new_rate = 2
        assert new_rate != original_rate, (
            f"New rate must differ from original for a meaningful test. "
            f"Original: {original_rate}, New: {new_rate}"
        )

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = farm_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, new_rate
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Verify the rate changed
            updated_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
            logger.info(f"Updated per-block reward amount: {updated_rate}")
            assert updated_rate == new_rate, (
                f"Per-block reward amount mismatch after set:\n"
                f"  Expected: {new_rate}\n"
                f"  Actual: {updated_rate}"
            )

        finally:
            # Restore original rate
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = farm_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, original_rate
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)

            # Verify restoration
            restored_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
            assert restored_rate == original_rate, (
                f"Failed to restore per-block reward amount:\n"
                f"  Expected: {original_rate}\n"
                f"  Actual: {restored_rate}"
            )
            logger.info(f"Per-block reward amount restored to {original_rate} (cleanup)")

        logger.info("PASSED: test_set_per_block_reward_amount")

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
        new_percentage = 5000       # 50%

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
            assert state_paused == 0, (
                f"Farm should be inactive (0) after pause, got {state_paused}"
            )

            # Attempt enterFarm while paused - should fail
            tx_enter = _enter_farm(
                farm_contract, alice, farming_token, stake_amount,
                network_providers, blockchain_controller
            )
            TransactionAssertions.assert_transaction_failed(
                tx_enter, network_providers.proxy,
                expected_error="Not active"
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
        assert state_after == 1, (
            f"Farm should be active (1) after resume, got {state_after}"
        )

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
        assert state == 1, (
            f"Farm should still be active after rejected pause, got {state}"
        )

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
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Collect undistributed boosted rewards

        GIVEN: Farm contract with boosted yields configured
        WHEN: Deployer calls collectUndistributedBoostedRewards
        THEN:
            - Transaction succeeds
            - May return 0 rewards on chain simulator (no accumulated rewards)

        NOTE: On chain simulator with freshly loaded state, there are typically
        no undistributed boosted rewards to collect. This test verifies the
        endpoint is callable and does not revert.
        """
        logger.info("TEST: Collect undistributed boosted rewards")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Check reward reserve before collection
        reward_reserve_before = farm_contract.get_reward_reserve(network_providers.proxy)
        logger.info(f"Reward reserve before collection: {reward_reserve_before}")

        # Call collectUndistributedBoostedRewards
        # Note: signature is (proxy, user) - different parameter order from most methods
        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = farm_contract.collect_undistributed_boosted_rewards(
            network_providers.proxy, deployer_account
        )
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info("collectUndistributedBoostedRewards succeeded")

        # Check reward reserve after collection
        reward_reserve_after = farm_contract.get_reward_reserve(network_providers.proxy)
        logger.info(f"Reward reserve after collection: {reward_reserve_after}")

        logger.info("PASSED: test_collect_undistributed_rewards")
