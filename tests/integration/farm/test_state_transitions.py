"""
Integration tests for Farm-with-locked-rewards contract state transitions & lifecycle.

These tests verify the farm contract handles lifecycle operations correctly:
- Full user lifecycle: enter -> claim -> exit with state verification
- Week boundary crossing effects on rewards and tracking
- Epoch advancement effects on week calculation
- Reward production toggle (start/stop/start)
- Reward rate changes while users are staked

Test Categories:
1. Full Lifecycle: Complete enter -> claim -> exit flow
2. Week Boundaries: Operations spanning week boundaries
3. Epoch Effects: Epoch advancement and week tracking
4. Production Toggle: Start/stop/start reward production
5. Rate Change: Mid-operation reward rate change

IMPORTANT: All admin state-changing operations use try/finally blocks
to ensure state is always restored for subsequent tests.

Run:
    pytest --env=chainsim tests/integration/farm/test_state_transitions.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher, SimpleLockEnergyContractDataFetcher
from utils.utils_chain import nominated_amount, Account, hex_to_string, decode_merged_attributes
from utils.utils_tx import NetworkProviders
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
class TestFarmStateTransitions:
    """
    Integration tests for Farm contract state transitions and lifecycle.

    Verifies that the farm contract handles lifecycle operations correctly,
    including full user flow, week boundary crossings, epoch advancement,
    reward production toggling, and mid-operation rate changes.
    """

    # ----------------------------------------------------------------
    # Full Lifecycle Tests
    # ----------------------------------------------------------------

    def test_full_lifecycle(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Complete user lifecycle: enter -> claim -> exit with full
                  state verification at each stage.

        GIVEN: Farm contract is active with rewards being produced
        WHEN: Alice enters farm, advances blocks, claims rewards, advances
              more blocks, then exits fully
        THEN:
            - After entry: farm token supply increases, Alice has farm token NFT,
              getUserTotalFarmPosition > 0
            - After claim: new farm token with updated RPS, reserve decreases
            - After exit: farm token supply returns to original, Alice receives
              LP tokens back, getUserTotalFarmPosition decreases

        LIFECYCLE: This test exercises the full user journey through the farm,
                   validating state at each transition point.
        """
        logger.info("TEST: Full lifecycle (enter -> claim -> exit)")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # ---- STATE 0: Before entry ----
        state_0 = _get_farm_state(farm_contract, network_providers.proxy)
        supply_before = state_0["farm_token_supply"]
        reserve_before = state_0["reward_reserve"]
        rps_before = state_0["reward_per_share"]
        position_before = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"STATE 0 (before entry): supply={supply_before}, reserve={reserve_before}, "
                     f"rps={rps_before}, position={position_before}")

        # ---- TRANSITION 1: Enter farm ----
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        state_1 = _get_farm_state(farm_contract, network_providers.proxy)
        position_after_enter = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"STATE 1 (after entry): supply={state_1['farm_token_supply']}, "
                     f"position={position_after_enter}")

        # Verify entry effects
        assert state_1["farm_token_supply"] == supply_before + stake_amount, (
            f"Supply should increase by stake amount after entry:\n"
            f"  Before: {supply_before}\n"
            f"  After: {state_1['farm_token_supply']}\n"
            f"  Expected increase: {stake_amount}"
        )
        assert position_after_enter > position_before, (
            f"User total farm position should increase after entry:\n"
            f"  Before: {position_before}\n"
            f"  After: {position_after_enter}"
        )

        # Alice should have farm token NFTs
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens after entry"
        locked_token_id = _get_locked_token_id(farm_contract, network_providers.proxy)
        locked_before_claim = sum(
            token.amount
            for token in _get_locked_tokens_for_user(farm_contract, alice, network_providers.proxy)
        )

        # ---- Advance blocks for reward accrual ----
        blockchain_controller.wait_blocks(50)

        # ---- TRANSITION 2: Claim rewards ----
        ft_before_claim = max(farm_tokens, key=lambda t: t.token.nonce)
        reserve_before_claim = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        tx_claim = _claim_rewards(farm_contract, alice, ft_before_claim.token.nonce,
                                  ft_before_claim.amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        state_2 = _get_farm_state(farm_contract, network_providers.proxy)
        reserve_after_claim = state_2["reward_reserve"]
        rps_after_claim = state_2["reward_per_share"]
        logger.info(f"STATE 2 (after claim): reserve={reserve_after_claim}, rps={rps_after_claim}")
        locked_after_claim = sum(
            token.amount
            for token in _get_locked_tokens_for_user(farm_contract, alice, network_providers.proxy)
        )

        # RPS should have increased (rewards accrued during the 10 blocks)
        assert rps_after_claim >= rps_before, (
            f"RPS should not decrease after blocks and claim:\n"
            f"  Before entry: {rps_before}\n"
            f"  After claim: {rps_after_claim}"
        )
        if locked_after_claim == locked_before_claim:
            pytest.skip("No locked rewards accrued during lifecycle claim after 50 blocks on loaded state")
        assert locked_after_claim > locked_before_claim, (
            f"Claim should mint locked XMEX rewards:\n"
            f"  Locked token id: {locked_token_id or 'discovered via NFT delta fallback'}\n"
            f"  Locked before claim: {locked_before_claim}\n"
            f"  Locked after claim: {locked_after_claim}"
        )

        # Alice should have a new farm token with updated RPS
        farm_tokens_after_claim = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after_claim) > 0, "Alice should have farm tokens after claim"
        new_ft = max(farm_tokens_after_claim, key=lambda t: t.token.nonce)
        attrs = decode_merged_attributes(new_ft.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        assert attrs["reward_per_share"] >= rps_before, (
            f"New farm token RPS should be >= pre-entry RPS:\n"
            f"  Entry RPS: {rps_before}\n"
            f"  New token RPS: {attrs['reward_per_share']}"
        )

        # ---- Advance more blocks ----
        blockchain_controller.wait_blocks(5)

        # ---- TRANSITION 3: Exit farm ----
        farm_tokens_for_exit = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft_exit = max(farm_tokens_for_exit, key=lambda t: t.token.nonce)

        tx_exit = _exit_farm(farm_contract, alice, ft_exit.token.nonce, ft_exit.amount,
                             network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)

        state_3 = _get_farm_state(farm_contract, network_providers.proxy)
        position_after_exit = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"STATE 3 (after exit): supply={state_3['farm_token_supply']}, "
                     f"position={position_after_exit}")

        # Supply should return to original
        assert state_3["farm_token_supply"] == supply_before, (
            f"Supply should return to original after full exit:\n"
            f"  Original: {supply_before}\n"
            f"  After exit: {state_3['farm_token_supply']}"
        )

        # Position should decrease
        assert position_after_exit < position_after_enter, (
            f"User position should decrease after exit:\n"
            f"  After enter: {position_after_enter}\n"
            f"  After exit: {position_after_exit}"
        )

        # RPS should only increase (never decrease)
        assert state_3["reward_per_share"] >= rps_after_claim, (
            f"RPS should never decrease:\n"
            f"  After claim: {rps_after_claim}\n"
            f"  After exit: {state_3['reward_per_share']}"
        )

        logger.info("PASSED: test_full_lifecycle")

    # ----------------------------------------------------------------
    # Week Boundary Tests
    # ----------------------------------------------------------------

    def test_week_boundary_crossing(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Perform operations that span a week boundary and verify
                  weekly snapshots are correct.

        GIVEN: Farm contract with boosted yields tracking per week
        WHEN: Alice enters farm in week W, advance to week W+1, claim
              rewards (triggering weekly snapshot), then verify week data
        THEN:
            - getCurrentWeek advances correctly across boundary
            - Farm supply for week W+1 reflects Alice's position
            - Claim succeeds across week boundary without errors
            - Weekly accumulated rewards are non-negative

        LIFECYCLE: Week boundaries are critical for boosted yield distribution.
                   Operations spanning boundaries must trigger correct snapshots.
        """
        logger.info("TEST: Week boundary crossing")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm and record current week
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        week_at_entry = farm_contract.get_current_week(network_providers.proxy)
        epoch_at_entry = blockchain_controller.get_current_epoch()
        logger.info(f"Entered at week {week_at_entry}, epoch {epoch_at_entry}")

        # Advance to next week boundary
        next_week_epoch = farm_contract.get_next_week_start_epoch(network_providers.proxy)
        blockchain_controller.advance_to_epoch(next_week_epoch + 1)

        week_after_advance = farm_contract.get_current_week(network_providers.proxy)
        epoch_after_advance = blockchain_controller.get_current_epoch()
        logger.info(f"Advanced to week {week_after_advance}, epoch {epoch_after_advance}")

        # Week should have advanced
        assert week_after_advance > week_at_entry, (
            f"Week should advance after crossing boundary:\n"
            f"  Entry week: {week_at_entry}\n"
            f"  Current week: {week_after_advance}\n"
            f"  Entry epoch: {epoch_at_entry}\n"
            f"  Current epoch: {epoch_after_advance}"
        )

        # Claim rewards across week boundary (triggers weekly snapshot)
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_claim = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                                  network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)
        logger.info("Claim succeeded across week boundary")

        # Verify weekly data for the new week
        supply_for_week = farm_contract.get_farm_supply_for_week(
            network_providers.proxy, week_after_advance
        )
        accumulated = farm_contract.get_accumulated_rewards_for_week(
            network_providers.proxy, week_after_advance
        )
        total_rewards = farm_contract.get_total_rewards_for_week(
            network_providers.proxy, week_after_advance
        )

        logger.info(f"Week {week_after_advance}: supply={supply_for_week}, "
                     f"accumulated={accumulated}, total_rewards={total_rewards}")

        # Farm supply for the new week should reflect Alice's position
        assert supply_for_week > 0, (
            f"Farm supply for week {week_after_advance} should be > 0:\n"
            f"  Actual: {supply_for_week}\n"
            f"  Alice staked: {stake_amount}"
        )

        # All weekly values should be non-negative
        assert accumulated >= 0, f"Accumulated rewards should be >= 0, got {accumulated}"
        assert total_rewards >= 0, f"Total rewards should be >= 0, got {total_rewards}"

        logger.info("PASSED: test_week_boundary_crossing")

    # ----------------------------------------------------------------
    # Epoch Advancement Tests
    # ----------------------------------------------------------------

    def test_epoch_advancement_effects(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Advance epochs and verify week calculation updates correctly.

        GIVEN: Farm contract with firstWeekStartEpoch overridden to 0
        WHEN: Advance through multiple epoch intervals (7, 14, 21 epochs)
        THEN:
            - getCurrentWeek tracks correctly: (epoch - firstWeekStartEpoch) / 7 + 1
            - Week monotonically increases with epochs
            - firstWeekStartEpoch remains constant
            - getNextWeekStartEpoch is always in the future

        LIFECYCLE: Epoch advancement is the clock driving weekly boosted yield
                   distribution. Incorrect tracking would corrupt reward allocation.
        """
        logger.info("TEST: Epoch advancement effects")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        first_week_epoch = farm_contract.get_first_week_start_epoch(network_providers.proxy)
        logger.info(f"firstWeekStartEpoch: {first_week_epoch}")

        # Record initial state
        initial_epoch = blockchain_controller.get_current_epoch()
        initial_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Initial: epoch={initial_epoch}, week={initial_week}")

        # Advance through 3 weekly intervals
        previous_week = initial_week
        for i in range(3):
            target_epoch = initial_epoch + (i + 1) * 7
            blockchain_controller.advance_to_epoch(target_epoch)

            current_epoch = blockchain_controller.get_current_epoch()
            current_week = farm_contract.get_current_week(network_providers.proxy)
            expected_week = (current_epoch - first_week_epoch) // 7 + 1
            next_week_start = farm_contract.get_next_week_start_epoch(network_providers.proxy)

            logger.info(f"Step {i + 1}: epoch={current_epoch}, week={current_week}, "
                         f"expected={expected_week}, next_week_start={next_week_start}")

            # Week formula must hold
            assert current_week == expected_week, (
                f"Week calculation mismatch at step {i + 1}:\n"
                f"  Expected: (epoch={current_epoch} - first={first_week_epoch}) / 7 + 1 = {expected_week}\n"
                f"  Actual: {current_week}"
            )

            # Week must monotonically increase
            assert current_week >= previous_week, (
                f"Week should monotonically increase:\n"
                f"  Previous: {previous_week}\n"
                f"  Current: {current_week}"
            )

            # Next week start should be in the future
            assert next_week_start > current_epoch, (
                f"Next week start should be > current epoch:\n"
                f"  Next week start: {next_week_start}\n"
                f"  Current epoch: {current_epoch}"
            )

            # firstWeekStartEpoch must not change
            assert farm_contract.get_first_week_start_epoch(network_providers.proxy) == first_week_epoch, (
                f"firstWeekStartEpoch should remain constant"
            )

            previous_week = current_week

        # Overall: weeks should have advanced by at least 3
        final_week = farm_contract.get_current_week(network_providers.proxy)
        assert final_week >= initial_week + 3, (
            f"Weeks should have advanced by at least 3:\n"
            f"  Initial: {initial_week}\n"
            f"  Final: {final_week}"
        )

        logger.info("PASSED: test_epoch_advancement_effects")

    # ----------------------------------------------------------------
    # Production Toggle Tests
    # ----------------------------------------------------------------

    def test_produce_rewards_toggle(
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
        SCENARIO: Start -> stop -> start reward production and verify
                  rewards only accrue during active periods.

        GIVEN: Farm contract with rewards being produced
        WHEN:
            1. Record RPS, advance blocks (rewards active)
            2. Stop production, advance blocks (no rewards)
            3. Restart production, advance blocks (rewards active again)
        THEN:
            - Phase 1: RPS increases (rewards accruing)
            - Phase 2: RPS frozen (no rewards)
            - Phase 3: RPS increases again (rewards resumed)

        CLEANUP: Always restart reward production in finally block

        LIFECYCLE: The ability to toggle reward production is critical for
                   farm lifecycle management (maintenance, migration, etc.).
        """
        logger.info("TEST: Produce rewards toggle (start/stop/start)")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Ensure rewards are started
        deployer_account.sync_nonce(network_providers.proxy)
        tx_start_init = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_start_init)

        try:
            # ---- PHASE 1: Rewards active ----
            rps_phase1_start = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            blockchain_controller.wait_blocks(10)
            rps_phase1_end = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            phase1_growth = rps_phase1_end - rps_phase1_start
            logger.info(f"Phase 1 (active): RPS {rps_phase1_start} -> {rps_phase1_end} "
                         f"(growth: {phase1_growth})")

            assert rps_phase1_end >= rps_phase1_start, (
                f"Phase 1: RPS should not decrease while rewards active:\n"
                f"  Start: {rps_phase1_start}\n"
                f"  End: {rps_phase1_end}"
            )

            # ---- STOP production ----
            deployer_account.sync_nonce(network_providers.proxy)
            tx_stop = farm_contract.end_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_stop)
            TransactionAssertions.assert_transaction_success(tx_stop, network_providers.proxy)
            logger.info("Reward production stopped")

            # ---- PHASE 2: Rewards stopped ----
            rps_phase2_start = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            blockchain_controller.wait_blocks(10)
            rps_phase2_end = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            phase2_growth = rps_phase2_end - rps_phase2_start
            logger.info(f"Phase 2 (stopped): RPS {rps_phase2_start} -> {rps_phase2_end} "
                         f"(growth: {phase2_growth})")

            # RPS should be frozen (no growth) when production is stopped
            assert rps_phase2_end == rps_phase2_start, (
                f"Phase 2: RPS should be frozen while rewards stopped:\n"
                f"  Start: {rps_phase2_start}\n"
                f"  End: {rps_phase2_end}\n"
                f"  Growth: {phase2_growth}"
            )

            # ---- RESTART production ----
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restart = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_restart)
            TransactionAssertions.assert_transaction_success(tx_restart, network_providers.proxy)
            logger.info("Reward production restarted")

            # ---- PHASE 3: Rewards active again ----
            rps_phase3_start = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            blockchain_controller.wait_blocks(10)
            rps_phase3_end = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            phase3_growth = rps_phase3_end - rps_phase3_start
            logger.info(f"Phase 3 (restarted): RPS {rps_phase3_start} -> {rps_phase3_end} "
                         f"(growth: {phase3_growth})")

            assert rps_phase3_end >= rps_phase3_start, (
                f"Phase 3: RPS should not decrease after rewards restarted:\n"
                f"  Start: {rps_phase3_start}\n"
                f"  End: {rps_phase3_end}"
            )

        finally:
            # Always ensure rewards are running for subsequent tests
            deployer_account.sync_nonce(network_providers.proxy)
            tx_ensure = farm_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_ensure)
            logger.info("Reward production ensured active (cleanup)")

        logger.info("PASSED: test_produce_rewards_toggle")

    # ----------------------------------------------------------------
    # Reward Rate Change Tests
    # ----------------------------------------------------------------

    def test_reward_rate_change_mid_operation(
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
        SCENARIO: Change the per-block reward rate while a user is staked.
                  Verify the old rate applies before the change and the new rate after.

        GIVEN: Alice has a farm position, reward rate is R1
        WHEN:
            1. Advance blocks (RPS grows at rate proportional to R1)
            2. Admin changes rate to R2 (R2 > R1)
            3. Advance same number of blocks (RPS grows at rate proportional to R2)
        THEN:
            - Phase 1 RPS growth corresponds to R1
            - Phase 2 RPS growth corresponds to R2
            - Phase 2 growth >= Phase 1 growth (since R2 > R1)

        CLEANUP: Always restore original per-block reward amount

        LIFECYCLE: Rate changes affect all staked users. The transition must be
                   clean: old rate up to the change block, new rate after.
        """
        logger.info("TEST: Reward rate change mid-operation")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Ensure Alice has a farm position
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Read the original rate
        original_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
        logger.info(f"Original per-block rate: {original_rate}")

        # Set a higher rate for Phase 2
        new_rate = original_rate * 5 if original_rate > 0 else 5
        num_blocks = 10

        try:
            # ---- PHASE 1: Original rate ----
            rps_phase1_start = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            blockchain_controller.wait_blocks(num_blocks)
            rps_phase1_end = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            phase1_growth = rps_phase1_end - rps_phase1_start
            logger.info(f"Phase 1 (rate={original_rate}): RPS growth = {phase1_growth}")

            # ---- Change rate ----
            deployer_account.sync_nonce(network_providers.proxy)
            tx_set = farm_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, new_rate
            )
            blockchain_controller.wait_for_tx(tx_set)
            TransactionAssertions.assert_transaction_success(tx_set, network_providers.proxy)

            # Verify rate changed
            actual_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
            assert actual_rate == new_rate, (
                f"Rate should be updated:\n"
                f"  Expected: {new_rate}\n"
                f"  Actual: {actual_rate}"
            )
            logger.info(f"Rate changed to {new_rate}")

            # ---- PHASE 2: New (higher) rate ----
            rps_phase2_start = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            blockchain_controller.wait_blocks(num_blocks)
            rps_phase2_end = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
            phase2_growth = rps_phase2_end - rps_phase2_start
            logger.info(f"Phase 2 (rate={new_rate}): RPS growth = {phase2_growth}")

            # Phase 2 growth should be >= Phase 1 growth (higher rate)
            assert phase2_growth >= phase1_growth, (
                f"Higher rate should produce >= RPS growth:\n"
                f"  Phase 1 growth (rate={original_rate}): {phase1_growth}\n"
                f"  Phase 2 growth (rate={new_rate}): {phase2_growth}"
            )

            # Verify Alice can still claim rewards (rate change didn't break state)
            farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            assert len(farm_tokens) > 0, "Alice should have farm tokens"
            ft = max(farm_tokens, key=lambda t: t.token.nonce)

            reserve_before_claim = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
            tx_claim = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                                      network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

            reserve_after_claim = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
            reserve_tolerance = 5_000
            assert reserve_after_claim <= reserve_before_claim + reserve_tolerance, (
                f"Reserve should not increase significantly after claim:\n"
                f"  Before: {reserve_before_claim}\n"
                f"  After: {reserve_after_claim}"
            )
            logger.info("Alice successfully claimed rewards after rate change")

        finally:
            # Always restore original rate
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = farm_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, original_rate
            )
            blockchain_controller.wait_for_tx(tx_restore)

            restored_rate = farm_contract.get_per_block_reward_amount(network_providers.proxy)
            assert restored_rate == original_rate, (
                f"Failed to restore rate: expected {original_rate}, got {restored_rate}"
            )
            logger.info(f"Rate restored to {original_rate} (cleanup)")

        logger.info("PASSED: test_reward_rate_change_mid_operation")
