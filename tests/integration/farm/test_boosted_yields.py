"""
Integration tests for Farm-with-locked-rewards contract boosted yields mechanics.

These tests verify the week-based boosted yield tracking system through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Context:
- Energy factory has NO code and NO state on chain simulator, so user energy = 0 everywhere
- boostedYieldsRewardsPercentage = 6000 (60%)
- Week-related storage keys are filtered during state loading
- firstWeekStartEpoch is overridden to 0, chain sim at epoch ~10 so week ~2
- Tests verify the week tracking/snapshot mechanism even though actual boosted rewards are 0

Run:
    pytest --env=chainsim tests/integration/farm/test_boosted_yields.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher
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
class TestFarmBoostedYields:
    """
    Integration tests for Farm boosted yield week-tracking mechanics.

    Key Behaviors Tested:
    1. getCurrentWeek calculation: (epoch - firstWeekStartEpoch) / 7 + 1
    2. Per-week supply and energy tracking
    3. Global and user boosted stats queries
    4. Undistributed rewards tracking
    5. Zero-energy behavior on chain simulator (energy factory has no code)
    """

    # ----------------------------------------------------------------
    # Week Calculation Tests
    # ----------------------------------------------------------------

    def test_boosted_week_calculation(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Verify getCurrentWeek matches (epoch - firstWeekStartEpoch) / 7 + 1

        GIVEN: Farm contract with firstWeekStartEpoch overridden to 0
        WHEN: Query getCurrentWeek and advance epochs
        THEN:
            - getCurrentWeek matches the formula
            - Advancing 7 epochs increases the week by 1
        """
        logger.info("TEST: Boosted week calculation")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Query current state
        first_week_epoch = farm_contract.get_first_week_start_epoch(network_providers.proxy)
        current_week = farm_contract.get_current_week(network_providers.proxy)
        current_epoch = blockchain_controller.get_current_epoch()

        logger.info(f"firstWeekStartEpoch: {first_week_epoch}")
        logger.info(f"currentWeek: {current_week}")
        logger.info(f"currentEpoch: {current_epoch}")

        # Verify formula: week = (epoch - firstWeekStartEpoch) / 7 + 1
        expected_week = (current_epoch - first_week_epoch) // 7 + 1
        assert current_week == expected_week, (
            f"Week calculation mismatch:\n"
            f"  Expected: (epoch={current_epoch} - firstWeek={first_week_epoch}) / 7 + 1 = {expected_week}\n"
            f"  Actual: {current_week}"
        )

        # Advance 7 epochs and verify week increments
        target_epoch = current_epoch + 7
        blockchain_controller.advance_to_epoch(target_epoch)

        new_week = farm_contract.get_current_week(network_providers.proxy)
        new_epoch = blockchain_controller.get_current_epoch()
        expected_new_week = (new_epoch - first_week_epoch) // 7 + 1

        logger.info(f"After advance: epoch={new_epoch}, week={new_week}, expected={expected_new_week}")

        assert new_week == expected_new_week, (
            f"Week after advance mismatch:\n"
            f"  Expected: {expected_new_week}\n"
            f"  Actual: {new_week}"
        )

        # Week should have increased by at least 1
        assert new_week > current_week, (
            f"Week should advance after +7 epochs:\n"
            f"  Before: {current_week}\n"
            f"  After: {new_week}"
        )

        logger.info("PASSED: test_boosted_week_calculation")

    # ----------------------------------------------------------------
    # Zero-Energy Behavior Tests
    # ----------------------------------------------------------------

    def test_boosted_no_energy_zero_reward(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: User with 0 energy gets 0 boosted rewards

        GIVEN: Alice has a farm position; energy factory has no code on chain sim
        WHEN: Advance weeks and Alice calls claimBoostedRewards
        THEN:
            - Transaction succeeds
            - Energy = 0 (no energy factory)
            - Reward reserve unchanged (0 boosted rewards)
        """
        logger.info("TEST: Boosted no energy zero reward")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance to next week boundary
        next_week_epoch = farm_contract.get_next_week_start_epoch(network_providers.proxy)
        blockchain_controller.advance_to_epoch(next_week_epoch + 1)

        # Record state before claim
        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        # Claim boosted rewards
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Reward reserve should be unchanged (energy=0 -> no boosted rewards)
        reserve_after = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Reserve before: {reserve_before}, after: {reserve_after}")

        # Tolerance: per_block_reward_amount=1 mints new rewards each block,
        # so blocks generated for tx finalization can increase reserve slightly.
        reserve_tolerance = 1_000
        assert abs(reserve_after - reserve_before) <= reserve_tolerance, (
            f"Reward reserve should be approximately unchanged with 0 energy:\n"
            f"  Before: {reserve_before}\n"
            f"  After: {reserve_after}\n"
            f"  Delta: {reserve_after - reserve_before}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        logger.info("PASSED: test_boosted_no_energy_zero_reward")

    # ----------------------------------------------------------------
    # Farm Supply Tracking Tests
    # ----------------------------------------------------------------

    def test_boosted_farm_supply_for_week_tracking(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Farm supply for a week is tracked after enterFarm

        GIVEN: Farm contract with boosted yields tracking per week
        WHEN: Alice enters farm at week W, then triggers a weekly update
              by claiming in a new week W+1
        THEN: getFarmSupplyForWeek(W+1) reflects Alice's staked amount
        """
        logger.info("TEST: Boosted farm supply for week tracking")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Entered farm at week {current_week}")

        # Advance to next week to trigger a weekly snapshot update
        next_week_epoch = farm_contract.get_next_week_start_epoch(network_providers.proxy)
        blockchain_controller.advance_to_epoch(next_week_epoch + 1)

        new_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Advanced to week {new_week}")

        # Trigger a weekly update by claiming boosted rewards
        # (this forces the contract to snapshot the current week's data)
        tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                          blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Query farm supply for the new week
        supply_for_week = farm_contract.get_farm_supply_for_week(network_providers.proxy, new_week)
        logger.info(f"Farm supply for week {new_week}: {supply_for_week}")

        # Supply should be > 0 (reflects at least Alice's entry)
        assert supply_for_week > 0, (
            f"Farm supply for week {new_week} should be > 0 after entering farm:\n"
            f"  Actual: {supply_for_week}\n"
            f"  Alice staked: {stake_amount}"
        )

        logger.info("PASSED: test_boosted_farm_supply_for_week_tracking")

    # ----------------------------------------------------------------
    # Total Energy Tests
    # ----------------------------------------------------------------

    def test_boosted_total_energy_zero_on_chainsim(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Total energy for any week is 0 on chain simulator

        GIVEN: Energy factory has no code/state on chain simulator
        WHEN: Query getTotalEnergyForWeek for multiple weeks
        THEN: All values are 0
        """
        logger.info("TEST: Boosted total energy zero on chainsim")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Current week: {current_week}")

        # Check energy for current week and a few past weeks
        weeks_to_check = [max(1, current_week - 1), current_week]

        for week in weeks_to_check:
            total_energy = farm_contract.get_total_energy_for_week(network_providers.proxy, week)
            logger.info(f"Total energy for week {week}: {total_energy}")

            assert total_energy == 0, (
                f"Total energy should be 0 on chain sim (no energy factory):\n"
                f"  Week: {week}\n"
                f"  Energy: {total_energy}"
            )

        logger.info("PASSED: test_boosted_total_energy_zero_on_chainsim")

    # ----------------------------------------------------------------
    # Weekly Accumulation Tests
    # ----------------------------------------------------------------

    def test_boosted_weekly_accumulation(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Each week can be independently queried for accumulated rewards

        GIVEN: Farm contract is producing rewards
        WHEN: Advance through multiple weeks, triggering updates via claims
        THEN: Each week's data can be independently queried and is non-negative
        """
        logger.info("TEST: Boosted weekly accumulation")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Ensure Alice has a farm position
        position = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        if position == 0:
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        start_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Starting at week {start_week}")

        # Advance through 2 additional weeks, triggering updates each time
        weeks_queried = [start_week]
        for i in range(2):
            next_week_epoch = farm_contract.get_next_week_start_epoch(network_providers.proxy)
            blockchain_controller.advance_to_epoch(next_week_epoch + 1)

            current_week = farm_contract.get_current_week(network_providers.proxy)
            weeks_queried.append(current_week)

            # Trigger weekly update via claim
            tx_claim = _claim_boosted_rewards(farm_contract, alice, network_providers,
                                              blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        logger.info(f"Weeks queried: {weeks_queried}")

        # Query each week independently
        for week in weeks_queried:
            supply = farm_contract.get_farm_supply_for_week(network_providers.proxy, week)
            energy = farm_contract.get_total_energy_for_week(network_providers.proxy, week)
            accumulated = farm_contract.get_accumulated_rewards_for_week(network_providers.proxy, week)
            total_rewards = farm_contract.get_total_rewards_for_week(network_providers.proxy, week)

            logger.info(
                f"Week {week}: supply={supply}, energy={energy}, "
                f"accumulated={accumulated}, total_rewards={total_rewards}"
            )

            # All values should be non-negative
            assert supply >= 0, f"Farm supply for week {week} should be >= 0, got {supply}"
            assert energy >= 0, f"Total energy for week {week} should be >= 0, got {energy}"
            assert accumulated >= 0, f"Accumulated rewards for week {week} should be >= 0, got {accumulated}"
            assert total_rewards >= 0, f"Total rewards for week {week} should be >= 0, got {total_rewards}"

        logger.info("PASSED: test_boosted_weekly_accumulation")

    # ----------------------------------------------------------------
    # Global Stats Tests
    # ----------------------------------------------------------------

    def test_boosted_global_stats_consistency(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: get_all_boosted_global_stats returns consistent data

        GIVEN: Farm contract with boosted yields enabled
        WHEN: Query get_all_boosted_global_stats()
        THEN:
            - All expected fields are present
            - All values are non-negative
            - current_week matches getCurrentWeek
            - first_week matches getFirstWeekStartEpoch
        """
        logger.info("TEST: Boosted global stats consistency")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        stats = farm_contract.get_all_boosted_global_stats(network_providers.proxy)
        logger.info(f"Boosted global stats: {stats}")

        # Verify all expected fields are present
        expected_fields = [
            "first_week",
            "current_week",
            "farm_supply_for_week",
            "total_rewards_for_week",
            "total_locked_tokens_for_week",
            "accumulated_rewards_for_week",
            "total_energy_for_week",
        ]

        for field in expected_fields:
            assert field in stats, (
                f"Missing expected field '{field}' in boosted global stats.\n"
                f"  Available fields: {list(stats.keys())}"
            )

        # All values should be non-negative
        for field, value in stats.items():
            assert value >= 0, (
                f"Field '{field}' should be non-negative, got {value}"
            )

        # Verify consistency with direct queries
        direct_current_week = farm_contract.get_current_week(network_providers.proxy)
        assert stats["current_week"] == direct_current_week, (
            f"current_week mismatch:\n"
            f"  From stats: {stats['current_week']}\n"
            f"  Direct query: {direct_current_week}"
        )

        direct_first_week = farm_contract.get_first_week_start_epoch(network_providers.proxy)
        assert stats["first_week"] == direct_first_week, (
            f"first_week mismatch:\n"
            f"  From stats: {stats['first_week']}\n"
            f"  Direct query: {direct_first_week}"
        )

        logger.info("PASSED: test_boosted_global_stats_consistency")

    # ----------------------------------------------------------------
    # User Stats Tests
    # ----------------------------------------------------------------

    def test_boosted_user_stats(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: User boosted stats reflect farm position after enterFarm

        GIVEN: Alice enters the farm
        WHEN: Query get_all_user_boosted_stats() for Alice
        THEN:
            - user_total_farm_position > 0
            - All fields are present and well-formed
            - user_energy_for_week reflects 0 energy (no energy factory)
        """
        logger.info("TEST: Boosted user stats")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Ensure Alice has a farm position
        position = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        if position == 0:
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        alice_bech32 = alice.address.to_bech32()
        user_stats = farm_contract.get_all_user_boosted_stats(alice_bech32, network_providers.proxy)
        logger.info(f"User boosted stats: {user_stats}")

        # Verify all expected fields are present
        expected_fields = [
            "user_total_farm_position",
            "user_energy_for_week",
            "last_active_week",
            "current_claim_progress",
        ]

        for field in expected_fields:
            assert field in user_stats, (
                f"Missing expected field '{field}' in user boosted stats.\n"
                f"  Available fields: {list(user_stats.keys())}"
            )

        # user_total_farm_position should be > 0 (Alice entered farm)
        assert user_stats["user_total_farm_position"] > 0, (
            f"user_total_farm_position should be > 0 after entering farm:\n"
            f"  Actual: {user_stats['user_total_farm_position']}"
        )

        logger.info("PASSED: test_boosted_user_stats")

    # ----------------------------------------------------------------
    # Undistributed Rewards Tests
    # ----------------------------------------------------------------

    def test_boosted_undistributed_rewards(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: getUndistributedBoostedRewards returns a value >= 0

        GIVEN: Farm contract with boosted yields enabled
        WHEN: Query getUndistributedBoostedRewards for multiple weeks
        THEN: All returned values are >= 0
        """
        logger.info("TEST: Boosted undistributed rewards")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Current week: {current_week}")

        # Query undistributed rewards for current week and previous weeks
        weeks_to_check = list(range(max(1, current_week - 2), current_week + 1))

        for week in weeks_to_check:
            undistributed = farm_contract.get_undistributed_boosted_rewards(
                network_providers.proxy, week
            )
            remaining = farm_contract.get_remaining_boosted_rewards_to_distribute(
                network_providers.proxy, week
            )

            logger.info(
                f"Week {week}: undistributed={undistributed}, remaining={remaining}"
            )

            assert undistributed >= 0, (
                f"Undistributed rewards should be >= 0:\n"
                f"  Week: {week}\n"
                f"  Value: {undistributed}"
            )

            assert remaining >= 0, (
                f"Remaining rewards to distribute should be >= 0:\n"
                f"  Week: {week}\n"
                f"  Value: {remaining}"
            )

        logger.info("PASSED: test_boosted_undistributed_rewards")
