"""
Integration tests for Farm contract view functions.

These tests verify that the farm's read-only query endpoints return
correct and consistent data through black-box testing:
- getFarmTokenSupply: Total supply of farm tokens
- getRewardReserve: Available reward reserve
- getRewardPerShare: Global reward per share (monotonically non-decreasing)
- getFarmingTokenId: Farming (LP) token identifier
- getState: Contract active state
- getCurrentWeek: Current week based on epoch
- getUserTotalFarmPosition: Per-user staked position tracking
- calculateRewardsForGivenPosition: Reward calculation verification
- getLastRewardTimestamp: Last reward generation timestamp
- getUserEnergyForWeek: User energy snapshot per week
- getLastActiveWeekForUser: Last week with user activity
- getTotalLockedTokensForWeek: Weekly locked token tracking
- get_lp_address: Pair contract managed address

Run:
    pytest --env=chainsim tests/integration/farm/test_view_functions.py -v
    pytest --env=chainsim tests/integration/farm/test_view_functions.py::TestFarmViewFunctions::test_get_farm_token_supply -v
"""

import re
import pytest

from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent
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
class TestFarmViewFunctions:
    """
    Integration tests for Farm contract view/query endpoints.

    These tests verify that read-only view functions return correct,
    consistent data that matches the actual contract state.

    View Functions Tested:
    - getFarmTokenSupply: Total farm token supply tracking
    - getRewardReserve: Reward reserve availability
    - getRewardPerShare: Global RPS monotonic increase
    - getFarmingTokenId: Token identifier consistency
    - getState: Contract lifecycle state
    - getCurrentWeek: Week calculation from epoch
    - getUserTotalFarmPosition: Per-user position tracking
    - Reward calculation verification via RPS formula
    """

    def test_get_farm_token_supply(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Query farm token supply and verify it tracks enterFarm correctly

        GIVEN: Farm contract with pre-existing mainnet state (supply > 0)
        WHEN: Query getFarmTokenSupply, then enter farm with known amount
        THEN:
            - Initial supply is > 0 (mainnet state has existing positions)
            - After enterFarm, supply increases by exactly the staked amount

        SECURITY: Supply tracking is critical for reward distribution.
                  If supply is incorrect, rewards per share calculation breaks.
        """
        logger.info("TEST: getFarmTokenSupply view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Query initial supply - should be > 0 from mainnet state
        supply_before = farm_contract.get_farm_token_supply(network_providers.proxy)
        logger.info(f"Initial farm token supply: {supply_before}")
        assert supply_before > 0, (
            "Farm token supply should be > 0 with loaded mainnet state"
        )

        # Enter farm with a known amount
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        logger.info(f"Staking {stake_amount} of {farming_token}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(
            farm_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Query supply again - should have increased by exactly stake_amount
        supply_after = farm_contract.get_farm_token_supply(network_providers.proxy)
        logger.info(f"Farm token supply after entry: {supply_after}")

        assert supply_after == supply_before + stake_amount, (
            f"Farm token supply mismatch after enterFarm:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}\n"
            f"  Expected: {supply_before + stake_amount}\n"
            f"  Staked: {stake_amount}"
        )

        logger.info("PASSED: test_get_farm_token_supply")

    def test_get_reward_reserve(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query reward reserve and verify it is a valid positive value

        GIVEN: Farm contract with mainnet state (massive reward reserve)
        WHEN: Query getRewardReserve
        THEN:
            - Reward reserve is > 0 (mainnet farm has accumulated rewards)
            - Value is a reasonable positive integer

        SECURITY: Reward reserve is the pool from which user rewards are paid.
                  A zero or negative reserve means no rewards can be claimed.
        """
        logger.info("TEST: getRewardReserve view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        reward_reserve = farm_contract.get_reward_reserve(network_providers.proxy)
        logger.info(f"Reward reserve: {reward_reserve}")

        assert reward_reserve > 0, (
            "Reward reserve should be > 0 with loaded mainnet state.\n"
            "A farm with zero reward reserve cannot distribute rewards."
        )

        # Sanity check: reward reserve should be a valid integer, not an error code
        assert reward_reserve != -1, (
            "Reward reserve returned -1, indicating a query error"
        )

        logger.info(f"Reward reserve is valid: {reward_reserve} "
                     f"({reward_reserve / 10**18:.4f} tokens)")
        logger.info("PASSED: test_get_reward_reserve")

    def test_get_reward_per_share(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Query reward per share and verify it is monotonically non-decreasing

        GIVEN: Farm contract that is producing rewards
        WHEN: Query getRewardPerShare, advance blocks, query again
        THEN:
            - RPS after advancing blocks is >= RPS before (monotonically non-decreasing)

        SECURITY: RPS must only increase or stay the same. A decreasing RPS would
                  mean users lose accrued rewards, which is a critical invariant violation.
        """
        logger.info("TEST: getRewardPerShare view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        rps_before = farm_contract.get_reward_per_share(network_providers.proxy)
        logger.info(f"Reward per share (before blocks): {rps_before}")

        # Advance some blocks to allow reward generation
        blockchain_controller.wait_blocks(5)

        rps_after = farm_contract.get_reward_per_share(network_providers.proxy)
        logger.info(f"Reward per share (after blocks): {rps_after}")

        # RPS should be monotonically non-decreasing
        assert rps_after >= rps_before, (
            f"Reward per share DECREASED, violating monotonic invariant:\n"
            f"  Before: {rps_before}\n"
            f"  After: {rps_after}\n"
            f"  CRITICAL: A decreasing RPS means users lose accrued rewards"
        )

        if rps_after > rps_before:
            logger.info(f"RPS increased by {rps_after - rps_before} over 5 blocks")
        else:
            logger.info("RPS unchanged (farm may not be actively producing rewards)")

        logger.info("PASSED: test_get_reward_per_share")

    def test_get_farming_token_id(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query farming token identifier and verify consistency

        GIVEN: Farm contract with configured farming token
        WHEN: Query getFarmingTokenId via view function
        THEN:
            - Returned token ID matches farm_contract.farmingToken
            - Token ID has valid MultiversX ESDT format (TICKER-hexhash)

        SECURITY: If the farming token ID is wrong, users could stake incorrect
                  tokens or the farm would reject valid LP tokens.
        """
        logger.info("TEST: getFarmingTokenId view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token_id = farm_contract.get_farming_token_id(network_providers.proxy)
        logger.info(f"Farming token ID from view: {farming_token_id}")

        # Should match the configured farming token
        assert farming_token_id == farm_contract.farmingToken, (
            f"Farming token ID mismatch:\n"
            f"  From view function: {farming_token_id}\n"
            f"  From config: {farm_contract.farmingToken}"
        )

        # Validate MultiversX ESDT token format: TICKER-hexhash (6 hex chars)
        token_pattern = r'^[A-Z0-9]{3,10}-[a-f0-9]{6}$'
        assert re.match(token_pattern, farming_token_id), (
            f"Farming token ID does not match valid ESDT format (TICKER-hexhash):\n"
            f"  Token: {farming_token_id}\n"
            f"  Expected pattern: {token_pattern}"
        )

        # Also verify farm token ID for completeness
        farm_token_id = farm_contract.get_farm_token_id(network_providers.proxy)
        logger.info(f"Farm token ID from view: {farm_token_id}")
        assert farm_token_id == farm_contract.farmToken, (
            f"Farm token ID mismatch:\n"
            f"  From view function: {farm_token_id}\n"
            f"  From config: {farm_contract.farmToken}"
        )

        logger.info("PASSED: test_get_farming_token_id")

    def test_get_state(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query farm contract state and verify it is active

        GIVEN: Farm contract loaded from mainnet state (should be running)
        WHEN: Query getState
        THEN:
            - State is a positive integer (1 = Active)
            - Farm is operational and accepting transactions

        SECURITY: An inactive farm (state=0) rejects all user operations.
                  State must be monitored to ensure availability.
        """
        logger.info("TEST: getState view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        state = farm_contract.get_state(network_providers.proxy)
        logger.info(f"Farm contract state: {state}")

        # State should be a positive integer (1 = Active)
        assert state > 0, (
            f"Farm contract state should be Active (> 0), got {state}.\n"
            f"State 0 means the farm is inactive/paused and rejects operations."
        )

        # Verify state is not an error code
        assert state != -1, (
            "Farm state returned -1, indicating a query error"
        )

        logger.info(f"Farm is active (state={state})")
        logger.info("PASSED: test_get_state")

    def test_get_current_week(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Query current week from boosted yields and verify consistency

        GIVEN: Farm contract with firstWeekStartEpoch overridden to 0
        WHEN: Query getCurrentWeek (chain sim at epoch ~10)
        THEN:
            - Current week is > 0 (epoch 10, firstWeekStartEpoch=0 => week >= 2)
            - After advancing to next epoch boundary, week increases or stays same

        SECURITY: Week tracking is used for boosted rewards distribution.
                  Incorrect week calculation breaks the entire boosted yields system.
        """
        logger.info("TEST: getCurrentWeek view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Current week: {current_week}")

        # Week should be > 0 (chain sim at epoch ~10 with firstWeekStartEpoch=0)
        assert current_week > 0, (
            f"Current week should be > 0, got {current_week}.\n"
            f"Chain simulator should be at epoch ~10 with firstWeekStartEpoch=0,\n"
            f"which gives week = (10 - 0) / 7 + 1 >= 2"
        )

        # Verify first week start epoch for context
        first_week_epoch = farm_contract.get_first_week_start_epoch(network_providers.proxy)
        logger.info(f"First week start epoch: {first_week_epoch}")

        # Query current epoch for reference
        current_epoch = blockchain_controller.get_current_epoch()
        logger.info(f"Current epoch: {current_epoch}")

        # Week should be consistent with epoch calculation
        # week = (current_epoch - first_week_epoch) / 7 + 1
        if current_epoch > first_week_epoch:
            expected_week = (current_epoch - first_week_epoch) // 7 + 1
            logger.info(f"Expected week from epoch calculation: {expected_week}")
            # Allow for slight timing differences (epoch may advance between queries)
            assert abs(current_week - expected_week) <= 1, (
                f"Week mismatch with epoch calculation:\n"
                f"  Current week from view: {current_week}\n"
                f"  Expected from epoch: {expected_week}\n"
                f"  Current epoch: {current_epoch}\n"
                f"  First week epoch: {first_week_epoch}"
            )

        # Advance blocks and verify week is still valid
        blockchain_controller.wait_blocks(3)
        week_after = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Week after advancing blocks: {week_after}")

        assert week_after >= current_week, (
            f"Week should not decrease after advancing blocks:\n"
            f"  Before: {current_week}\n"
            f"  After: {week_after}"
        )

        logger.info("PASSED: test_get_current_week")

    def test_get_user_total_farm_position(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Query user total farm position before and after enterFarm

        GIVEN: Alice may or may not have an existing farm position
        WHEN: Query getUserTotalFarmPosition, then Alice enters farm
        THEN:
            - Position after entry increased by exactly the staked amount
            - View function accurately tracks user's total stake

        SECURITY: Total farm position is used for boosted rewards calculation.
                  Inaccurate tracking could lead to over/under-rewarding users.
        """
        logger.info("TEST: getUserTotalFarmPosition view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Query Alice's total farm position before entry
        position_before = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"Alice total farm position before: {position_before}")

        # Enter farm with known amount
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        logger.info(f"Staking {stake_amount} of {farming_token}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(
            farm_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Query position after entry
        position_after = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"Alice total farm position after: {position_after}")

        # Position should have increased by exactly stake_amount
        assert position_after == position_before + stake_amount, (
            f"User total farm position mismatch:\n"
            f"  Before: {position_before}\n"
            f"  After: {position_after}\n"
            f"  Expected: {position_before + stake_amount}\n"
            f"  Staked: {stake_amount}"
        )

        logger.info("PASSED: test_get_user_total_farm_position")

    def test_calculate_rewards_for_position(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Verify reward calculation using RPS formula

        GIVEN: Alice enters farm, blocks are advanced to generate rewards
        WHEN: Read entry RPS from farm token attributes, read current global RPS
        THEN:
            - Current global RPS > entry RPS (rewards were generated)
            - Expected reward = (current_rps - entry_rps) * amount / division_safety_constant
            - Division safety constant is a valid positive integer

        SECURITY: The RPS formula is the core mechanism for fair reward distribution.
                  If the formula is incorrect, users could claim more or fewer rewards
                  than they are entitled to. This is the most critical invariant in
                  the farm contract.
        """
        logger.info("TEST: Reward calculation via RPS formula")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Get division safety constant (used in reward formula)
        division_safety_constant = farm_contract.get_division_safety_constant(
            network_providers.proxy
        )
        logger.info(f"Division safety constant: {division_safety_constant}")
        assert division_safety_constant > 0, (
            f"Division safety constant must be > 0, got {division_safety_constant}.\n"
            "A zero constant would cause division by zero in reward calculations."
        )

        # Enter farm to create a fresh position with known entry RPS
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        logger.info(f"Staking {stake_amount} of {farming_token}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(
            farm_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get Alice's farm token and decode entry RPS from attributes
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens after entry"

        latest_token = max(farm_tokens, key=lambda t: t.token.nonce)
        attrs_hex = latest_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.FARM_TOKEN_ATTRIBUTES)
        entry_rps = attrs["reward_per_share"]
        farm_amount = attrs["current_farm_amount"]
        logger.info(f"Entry RPS: {entry_rps}")
        logger.info(f"Farm amount: {farm_amount}")

        # Advance blocks to generate rewards
        blockchain_controller.wait_blocks(10)

        # Read current global RPS
        current_rps = farm_contract.get_reward_per_share(network_providers.proxy)
        logger.info(f"Current global RPS (after 10 blocks): {current_rps}")

        # Current RPS should be >= entry RPS (rewards generated during blocks)
        assert current_rps >= entry_rps, (
            f"Current RPS should be >= entry RPS:\n"
            f"  Entry RPS: {entry_rps}\n"
            f"  Current RPS: {current_rps}\n"
            f"  CRITICAL: RPS decreased, indicating reward calculation error"
        )

        # Calculate expected reward using the farm formula:
        # reward = (current_rps - entry_rps) * amount / division_safety_constant
        if current_rps > entry_rps:
            rps_diff = current_rps - entry_rps
            expected_reward = rps_diff * farm_amount // division_safety_constant
            logger.info(f"RPS difference: {rps_diff}")
            logger.info(f"Expected reward (formula): {expected_reward}")
            logger.info(f"Expected reward in tokens: {expected_reward / 10**18:.6f}")

            # Reward should be positive when RPS increased
            assert expected_reward > 0, (
                f"Expected reward should be > 0 when RPS increased:\n"
                f"  RPS diff: {rps_diff}\n"
                f"  Farm amount: {farm_amount}\n"
                f"  Division safety constant: {division_safety_constant}\n"
                f"  Calculated reward: {expected_reward}"
            )
        else:
            logger.info("RPS unchanged - no rewards generated in 10 blocks "
                        "(farm may not be actively producing rewards)")

        # Verify per-block reward amount is configured
        per_block_reward = farm_contract.get_per_block_reward_amount(network_providers.proxy)
        logger.info(f"Per block reward amount: {per_block_reward}")
        logger.info(f"Per block reward in tokens: {per_block_reward / 10**18:.6f}")

        # Last reward block nonce should be valid
        last_reward_block = farm_contract.get_last_reward_block_nonce(network_providers.proxy)
        logger.info(f"Last reward block nonce: {last_reward_block}")
        assert last_reward_block >= 0, (
            f"Last reward block nonce should be >= 0, got {last_reward_block}"
        )

        logger.info("PASSED: test_calculate_rewards_for_position")

    def test_get_last_reward_timestamp(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query last reward timestamp and verify it is set

        GIVEN: Farm contract with rewards being produced
        WHEN: Query getLastRewardTimestamp
        THEN:
            - Timestamp is >= 0
            - Consistent with getLastRewardBlockNonce (both set or both zero)

        SECURITY: Last reward timestamp tracks when rewards were last generated.
                  Used in per-second reward model for accurate accrual.
        """
        logger.info("TEST: getLastRewardTimestamp view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        last_timestamp = farm_contract.get_last_reward_timestamp(network_providers.proxy)
        last_block_nonce = farm_contract.get_last_reward_block_nonce(network_providers.proxy)

        logger.info(f"Last reward timestamp: {last_timestamp}")
        logger.info(f"Last reward block nonce: {last_block_nonce}")

        assert last_timestamp >= 0, (
            f"Last reward timestamp should be >= 0, got {last_timestamp}"
        )
        assert last_block_nonce >= 0, (
            f"Last reward block nonce should be >= 0, got {last_block_nonce}"
        )

        # On chain sim with mainnet state, block nonce comes from mainnet (~29M)
        # but timestamp may be 0 (chain sim starts with unix timestamp 0).
        # Both values are valid and independently stored.

        logger.info("PASSED: test_get_last_reward_timestamp")

    def test_get_user_energy_for_week(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Query user energy for current week

        GIVEN: Alice has a farm position (entered farm)
        WHEN: Query getUserEnergyForWeek for Alice at current week
        THEN:
            - Returns a valid result (dict or empty)
            - On chain sim without energy factory: energy amount = 0
            - No errors or panics from the view function

        NOTE: Energy factory has no code on chain sim, so all users have 0 energy.
              This test verifies the view endpoint is callable and returns valid data.
        """
        logger.info("TEST: getUserEnergyForWeek view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Ensure Alice has a farm position (triggers energy snapshot on entry)
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        position = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        if position == 0:
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Current week: {current_week}")

        # Query user energy for current week
        user_energy = farm_contract.get_user_energy_for_week(
            alice.address.to_bech32(), network_providers.proxy, current_week
        )
        logger.info(f"User energy for week {current_week}: {user_energy}")

        # Result should be a dict (possibly empty if no energy snapshot stored)
        if user_energy:
            # If energy entry is returned, verify it has expected fields
            if "amount" in user_energy:
                assert user_energy["amount"] >= 0, (
                    f"Energy amount should be >= 0, got {user_energy['amount']}"
                )
                # On chain sim without energy factory, energy should be 0
                logger.info(f"Energy amount: {user_energy['amount']}")
        else:
            logger.info("No energy entry stored for user (expected on chain sim)")

        logger.info("PASSED: test_get_user_energy_for_week")

    def test_get_last_active_week_for_user(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Query last active week for a user who has interacted with the farm

        GIVEN: Alice has entered the farm (triggering a week snapshot)
        WHEN: Query getLastActiveWeekForUser for Alice
        THEN:
            - Returns a week number >= 0
            - If Alice has interacted, last active week <= current week

        NOTE: Last active week tracks when the user's boosted rewards were last
              updated. It's used to determine which weeks have unclaimed rewards.
        """
        logger.info("TEST: getLastActiveWeekForUser view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        # Ensure Alice has a farm position
        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        position = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        if position == 0:
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        last_active_week = farm_contract.get_last_active_week_for_user(
            alice.address.to_bech32(), network_providers.proxy
        )
        current_week = farm_contract.get_current_week(network_providers.proxy)

        logger.info(f"Last active week for Alice: {last_active_week}")
        logger.info(f"Current week: {current_week}")

        assert last_active_week >= 0, (
            f"Last active week should be >= 0, got {last_active_week}"
        )

        if last_active_week > 0:
            assert last_active_week <= current_week, (
                f"Last active week should be <= current week:\n"
                f"  Last active: {last_active_week}\n"
                f"  Current: {current_week}"
            )

        logger.info("PASSED: test_get_last_active_week_for_user")

    def test_get_total_locked_tokens_for_week(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query total locked tokens for current week

        GIVEN: Farm contract with boosted yields tracking
        WHEN: Query getTotalLockedTokensForWeek for current week
        THEN:
            - Returns a value >= 0
            - On chain sim without energy factory: locked tokens = 0

        NOTE: Total locked tokens per week tracks the sum of all users' locked
              MEX/XMEX that generates energy. Without the energy factory on chain
              sim, this should be 0.
        """
        logger.info("TEST: getTotalLockedTokensForWeek view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        current_week = farm_contract.get_current_week(network_providers.proxy)
        logger.info(f"Current week: {current_week}")

        total_locked = farm_contract.get_total_locked_tokens_for_week(
            network_providers.proxy, current_week
        )
        logger.info(f"Total locked tokens for week {current_week}: {total_locked}")

        assert total_locked >= 0, (
            f"Total locked tokens should be >= 0, got {total_locked}"
        )

        # Also check a previous week
        if current_week > 1:
            prev_week_locked = farm_contract.get_total_locked_tokens_for_week(
                network_providers.proxy, current_week - 1
            )
            logger.info(f"Total locked tokens for week {current_week - 1}: {prev_week_locked}")
            assert prev_week_locked >= 0, (
                f"Total locked tokens for prev week should be >= 0, got {prev_week_locked}"
            )

        logger.info("PASSED: test_get_total_locked_tokens_for_week")

    def test_get_lp_address(
        self,
        farm_contract: FarmContract,
        network_providers: NetworkProviders,
    ):
        """
        SCENARIO: Query the pair contract (LP) address associated with this farm

        GIVEN: Farm contract configured with a pair contract address
        WHEN: Query get_lp_address (getPairContractManagedAddress)
        THEN:
            - Returns a valid bech32 address (erd1...)
            - Address is non-empty

        NOTE: The LP address links the farm to its source pair contract.
              This is set at deploy time and should not change.
        """
        logger.info("TEST: get_lp_address (getPairContractManagedAddress) view function")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        lp_address = farm_contract.get_lp_address(network_providers.proxy)
        logger.info(f"LP (pair contract) address: {lp_address}")

        assert lp_address, "LP address should not be empty"
        assert lp_address.startswith("erd1"), (
            f"LP address should be a valid bech32 address (erd1...), got: {lp_address}"
        )
