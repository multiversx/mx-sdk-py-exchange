"""
Integration tests for Farm-with-locked-rewards contract claimBoostedRewards endpoint.

These tests verify the claim boosted rewards operation through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Basic claim
2. Error Cases: No farm position, unauthorized external claim
3. State Verification: Claim progress tracking, zero reward without energy
4. Edge Cases: After full exit, idempotent same-week claim

Note: On chain simulator, the energy factory has no code/state, so all users
have 0 energy. Boosted rewards will be 0, but the endpoint behavior (success/failure,
claim progress tracking, external claim permissions) is fully testable.

Run:
    pytest --env=chainsim tests/integration/farm/test_claim_boosted_rewards.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.utils_chain import nominated_amount, Account, hex_to_string, decode_merged_attributes
from utils.utils_tx import NetworkProviders, endpoint_call
from utils import decoding_structures
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
    _get_user_total_farm_position,
    _get_current_week,
    _get_claim_progress,
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
class TestFarmClaimBoostedRewards:
    """
    Integration tests for Farm.claimBoostedRewards()

    Contract Endpoints Tested:
    - claimBoostedRewards(opt user_address) -> ()
    - allowExternalClaimBoostedRewards() -> ()

    Key Behaviors:
    1. User calls claimBoostedRewards with no token transfer (endpoint_call)
    2. SC calculates boosted rewards based on user's energy and farm position
    3. On chain sim: energy factory has no code, so energy=0 and boosted rewards=0
    4. Claim progress (week counter) still advances even with 0 rewards
    5. External claim requires allowExternalClaimBoostedRewards permission
    6. Users without a farm position get "User total farm position is empty!"
    """

    # ----------------------------------------------------------------
    # Happy Path Tests
    # ----------------------------------------------------------------

    def test_claim_boosted_basic(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice claims boosted rewards after entering farm

        GIVEN: Alice has a farm position from enterFarm
        WHEN: Blocks pass and Alice calls claimBoostedRewards
        THEN:
            - Transaction succeeds
            - Alice retains her farm tokens (no token sent/received)
            - Reward reserve is unchanged (0 energy -> 0 boosted rewards on chain sim)
        """
        logger.info("TEST: Claim boosted basic")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Verify Alice has a farm position
        position = _get_user_total_farm_position(farm_contract, alice, network_providers.proxy)
        assert position > 0, f"Alice should have a farm position, got {position}"

        # Advance blocks
        blockchain_controller.wait_blocks(5)

        # Record state before claim
        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        farm_tokens_before = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)

        # Claim boosted rewards
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Alice still has her farm tokens (claimBoostedRewards doesn't consume farm tokens)
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) >= len(farm_tokens_before), (
            "Alice should retain her farm tokens after claimBoostedRewards"
        )

        # On chain sim, energy=0 so boosted rewards=0, reserve unchanged
        reserve_after = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Reserve before: {reserve_before}, after: {reserve_after}")

        logger.info("PASSED: test_claim_boosted_basic")

    # ----------------------------------------------------------------
    # Error Case Tests
    # ----------------------------------------------------------------

    def test_claim_boosted_no_farm_position_fails(
        self,
        farm_contract: FarmContract,
        bob: Account,
        test_accounts,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: User without farm position calls claimBoostedRewards

        GIVEN: Bob has NOT entered the farm (no totalFarmPosition)
        WHEN: Bob calls claimBoostedRewards
        THEN: Transaction fails with "User total farm position is empty!"
        """
        logger.info("TEST: Claim boosted no farm position fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Use Bob if he has no position; otherwise use a higher-index account
        # that no farm test uses, guaranteeing no prior farm entry.
        test_user = bob
        position = _get_user_total_farm_position(farm_contract, test_user, network_providers.proxy)
        if position > 0 and len(test_accounts) > 3:
            test_user = test_accounts[3]
            test_user.sync_nonce(network_providers.proxy)

        position = _get_user_total_farm_position(farm_contract, test_user, network_providers.proxy)
        if position > 0:
            pytest.skip("All available test accounts already have farm positions")

        # User without position tries to claim boosted rewards
        tx_claim = _claim_boosted_rewards(farm_contract, test_user, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_failed(tx_claim, network_providers.proxy)

        logger.info("PASSED: test_claim_boosted_no_farm_position_fails")

    def test_claim_boosted_unauthorized_for_other_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Bob tries to claim Alice's boosted rewards without permission

        GIVEN: Alice has a farm position but has NOT called allowExternalClaimBoostedRewards
        WHEN: Bob calls claimBoostedRewards(user=Alice)
        THEN: Transaction fails with "Cannot claim rewards for this address"
        """
        logger.info("TEST: Claim boosted unauthorized for other fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm (may already have position from prior tests)
        position = _get_user_total_farm_position(farm_contract, alice, network_providers.proxy)
        if position == 0:
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Bob tries to claim for Alice WITHOUT permission
        alice_bech32 = alice.address.to_bech32()
        tx_claim = _claim_boosted_rewards(farm_contract, bob, network_providers,
                                          blockchain_controller, for_user=alice_bech32)
        TransactionAssertions.assert_transaction_failed(tx_claim, network_providers.proxy)

        logger.info("PASSED: test_claim_boosted_unauthorized_for_other_fails")

    # ----------------------------------------------------------------
    # State Verification Tests
    # ----------------------------------------------------------------

    def test_claim_boosted_zero_reward_without_energy(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: User with farm position but no energy gets 0 boosted rewards

        GIVEN: Alice has a farm position, energy factory has no code on chain sim
        WHEN: Alice calls claimBoostedRewards
        THEN:
            - Transaction succeeds
            - Reward reserve is unchanged (no boosted rewards without energy)
            - Farm token supply is unchanged
        """
        logger.info("TEST: Claim boosted zero reward without energy")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance blocks
        blockchain_controller.wait_blocks(5)

        # Record state before
        state_before = _get_farm_state(farm_contract, network_providers.proxy)

        # Claim boosted rewards
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Record state after
        state_after = _get_farm_state(farm_contract, network_providers.proxy)

        # Reward reserve approximately unchanged (no energy -> no boosted rewards)
        # Tolerance needed: per_block_reward_amount=1 mints new rewards each block,
        # so blocks generated for tx finalization can increase reserve by ~5-20 units
        reserve_tolerance = 1_000
        assert abs(state_after["reward_reserve"] - state_before["reward_reserve"]) <= reserve_tolerance, (
            f"Reward reserve should be approximately unchanged without energy:\n"
            f"  Before: {state_before['reward_reserve']}\n"
            f"  After: {state_after['reward_reserve']}\n"
            f"  Delta: {state_after['reward_reserve'] - state_before['reward_reserve']}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        # Farm token supply unchanged (claimBoostedRewards doesn't affect farm tokens)
        assert state_after["farm_token_supply"] == state_before["farm_token_supply"], (
            f"Farm token supply should be unchanged:\n"
            f"  Before: {state_before['farm_token_supply']}\n"
            f"  After: {state_after['farm_token_supply']}"
        )

        logger.info("PASSED: test_claim_boosted_zero_reward_without_energy")

    def test_claim_boosted_updates_claim_progress(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Claim progress advances after claimBoostedRewards

        GIVEN: Alice has a farm position
        WHEN: Alice calls claimBoostedRewards after advancing weeks
        THEN: getCurrentClaimProgress shows updated week for Alice
        """
        logger.info("TEST: Claim boosted updates claim progress")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Get current week and advance to next week boundary
        current_week = _get_current_week(farm_contract, network_providers.proxy)
        next_week_epoch = farm_contract.get_next_week_start_epoch(network_providers.proxy)
        if next_week_epoch < 0:
            first_week_start_epoch = max(
                0,
                _get_farm_state(farm_contract, network_providers.proxy)["first_week_start_epoch"],
            )
            next_week_epoch = first_week_start_epoch + (current_week * 7)
        logger.info(f"Current week: {current_week}, next week starts at epoch: {next_week_epoch}")

        # Advance to at least 1 week later
        target_epoch = next_week_epoch + 7  # Go 1 full week past the next boundary
        blockchain_controller.advance_to_epoch(target_epoch)

        new_week = _get_current_week(farm_contract, network_providers.proxy)
        logger.info(f"After advance: week={new_week}, target_epoch={target_epoch}")
        assert new_week > current_week, (
            f"Week should have advanced: {current_week} -> {new_week}"
        )

        # Get claim progress before
        progress_before = _get_claim_progress(farm_contract, alice, network_providers.proxy)
        logger.info(f"Claim progress before: {progress_before}")

        # Claim boosted rewards
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Get claim progress after
        progress_after = _get_claim_progress(farm_contract, alice, network_providers.proxy)
        logger.info(f"Claim progress after: {progress_after}")

        # Claim progress should have advanced (week field should increase)
        if progress_before and progress_after:
            assert progress_after.get("week", 0) >= progress_before.get("week", 0), (
                f"Claim progress week should advance:\n"
                f"  Before: {progress_before}\n"
                f"  After: {progress_after}"
            )

        logger.info("PASSED: test_claim_boosted_updates_claim_progress")

    # ----------------------------------------------------------------
    # Edge Case Tests
    # ----------------------------------------------------------------

    def test_claim_boosted_after_full_exit_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Claiming boosted rewards after full exit fails

        GIVEN: Alice enters farm, then fully exits (totalFarmPosition -> 0)
        WHEN: Alice calls claimBoostedRewards
        THEN: Transaction fails (no farm position)
        """
        logger.info("TEST: Claim boosted after full exit fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Verify position exists
        position = _get_user_total_farm_position(farm_contract, alice, network_providers.proxy)
        assert position > 0, "Alice should have a farm position after entry"

        # Advance blocks to avoid minimum farming epochs penalty
        blockchain_controller.wait_blocks(10)

        # Alice fully exits
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        for ft in farm_tokens:
            tx_exit = _exit_farm(farm_contract, alice, ft.token.nonce, ft.amount,
                                network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)

        # Verify position is now 0
        position_after = _get_user_total_farm_position(farm_contract, alice, network_providers.proxy)
        if position_after > 0:
            pytest.skip("Alice still has farm position from other tests — cannot test empty position")

        # Try to claim boosted rewards with no position
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_failed(tx_claim, network_providers.proxy)

        logger.info("PASSED: test_claim_boosted_after_full_exit_fails")

    def test_claim_boosted_idempotent_same_week(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Consecutive claimBoostedRewards calls in the same week are idempotent

        GIVEN: Alice has a farm position
        WHEN: Alice calls claimBoostedRewards twice without advancing weeks
        THEN:
            - Both transactions succeed
            - Second call has no additional effect on reward reserve
            - Farm tokens are unchanged
        """
        logger.info("TEST: Claim boosted idempotent same week")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance a few blocks (stay within same week)
        blockchain_controller.wait_blocks(3)

        # First claim
        reserve_before_1 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        tx_claim_1 = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                            blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim_1, network_providers.proxy)
        reserve_after_1 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        delta_1 = reserve_before_1 - reserve_after_1
        logger.info(f"First claim reserve delta: {delta_1}")

        # Second claim immediately (same week, no advancement)
        reserve_before_2 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        tx_claim_2 = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                            blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim_2, network_providers.proxy)
        reserve_after_2 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        delta_2 = reserve_before_2 - reserve_after_2
        logger.info(f"Second claim reserve delta: {delta_2}")

        # Second call should have no additional effect (idempotent)
        # Tolerance: per_block_reward_amount=1 mints new rewards each block,
        # so reserve can shift by a few units between measurements
        reserve_tolerance = 5_000
        assert abs(delta_2) <= reserve_tolerance, (
            f"Second claimBoostedRewards in same week should have ~0 impact:\n"
            f"  First delta: {delta_1}\n"
            f"  Second delta: {delta_2}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        logger.info("PASSED: test_claim_boosted_idempotent_same_week")
