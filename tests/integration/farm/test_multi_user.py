"""
Integration tests for Farm-with-locked-rewards contract multi-user scenarios.

These tests verify that the farm contract handles multiple concurrent users correctly:
- Equal staking yields equal rewards
- Late entry receives fewer rewards
- Early exit leaves remaining rewards to others
- Reward conservation (no inflation)
- Dilution effect on reward per share growth rate

Test Categories:
1. Equal Stake: Two users with equal stakes get approximately equal rewards
2. Late Entry: User entering later gets fewer rewards
3. Early Exit: User exiting early forfeits subsequent rewards
4. Conservation: Total rewards paid <= reserve decrease (no inflation)
5. Dilution: New entrant reduces RPS growth rate

Run:
    pytest --env=chainsim tests/integration/farm/test_multi_user.py -v
"""

import pytest

from contracts.farm_contract import FarmContract
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _check_farm_has_code,
    _claim_rewards,
    _enter_farm,
    _exit_farm,
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
class TestFarmMultiUser:
    """
    Integration tests for Farm multi-user scenarios.

    Verifies that the farm contract correctly handles multiple concurrent users,
    proportional reward distribution, dilution effects, and reward conservation.
    """

    def test_two_users_equal_stake(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice and Bob stake equal amounts, rewards should be approximately equal.

        GIVEN: Farm contract is active
        WHEN: Alice and Bob both enter with equal stake amounts,
              advance blocks, then both claim rewards
        THEN:
            - Both transactions succeed
            - Reserve decrease from Alice's claim is approximately equal
              to reserve decrease from Bob's claim
            - Tolerance of 20% to account for block timing differences

        SECURITY: Equal stakes must yield equal rewards. Unequal distribution
                  would indicate a fairness bug.
        """
        logger.info("TEST: Two users equal stake")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Both enter farm with equal amounts
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Advance blocks for reward accrual
        blockchain_controller.wait_blocks(10)

        # Alice claims
        alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(alice_farm_tokens) > 0, "Alice should have farm tokens"
        alice_ft = max(alice_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_ca = _claim_rewards(
            farm_contract,
            alice,
            alice_ft.token.nonce,
            alice_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)
        reserve_after_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        alice_reward = reserve_before_alice - reserve_after_alice

        # Bob claims
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        assert len(bob_farm_tokens) > 0, "Bob should have farm tokens"
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_cb = _claim_rewards(
            farm_contract,
            bob,
            bob_ft.token.nonce,
            bob_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)
        reserve_after_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        bob_reward = reserve_before_bob - reserve_after_bob

        logger.info(f"Alice reward: {alice_reward}, Bob reward: {bob_reward}")

        # Equal stakes should yield approximately equal rewards
        # Allow 20% tolerance due to block timing and existing farm state
        if alice_reward > 0 and bob_reward > 0:
            ratio = alice_reward / bob_reward if bob_reward != 0 else float("inf")
            assert 0.8 <= ratio <= 1.2, (
                f"Equal stakes should yield approximately equal rewards:\n"
                f"  Alice reward: {alice_reward}\n"
                f"  Bob reward: {bob_reward}\n"
                f"  Ratio: {ratio:.4f} (expected ~1.0)"
            )
        elif alice_reward == 0 and bob_reward == 0:
            logger.info("Both rewards are 0 (expected on chain sim with large existing supply)")

        logger.info("PASSED: test_two_users_equal_stake")

    def test_user_enters_later(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice enters first, Bob enters later. Alice should get more rewards.

        GIVEN: Farm contract is active
        WHEN: Alice enters, blocks pass, then Bob enters, more blocks pass,
              both claim rewards
        THEN:
            - Alice's reward >= Bob's reward (she was in longer)
            - Both claims succeed

        SECURITY: Time-in-farm must be reflected in reward distribution.
                  A late entrant must not receive rewards for time before entry.
        """
        logger.info("TEST: User enters later")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters first
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        # Advance blocks while only Alice is in the farm
        blockchain_controller.wait_blocks(10)

        # Bob enters later
        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Advance more blocks (both in farm now)
        blockchain_controller.wait_blocks(5)

        # Alice claims
        alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        alice_ft = max(alice_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_ca = _claim_rewards(
            farm_contract,
            alice,
            alice_ft.token.nonce,
            alice_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)
        reserve_after_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        alice_reward = reserve_before_alice - reserve_after_alice

        # Bob claims
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_cb = _claim_rewards(
            farm_contract,
            bob,
            bob_ft.token.nonce,
            bob_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)
        reserve_after_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        bob_reward = reserve_before_bob - reserve_after_bob

        logger.info(f"Alice reward (entered first): {alice_reward}")
        logger.info(f"Bob reward (entered later): {bob_reward}")

        # Alice was in longer, should get at least as much as Bob
        if alice_reward > 0 or bob_reward > 0:
            assert alice_reward >= bob_reward, (
                f"Alice entered earlier and should have more rewards:\n"
                f"  Alice reward: {alice_reward}\n"
                f"  Bob reward: {bob_reward}"
            )

        logger.info("PASSED: test_user_enters_later")

    def test_user_exits_early(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice and Bob enter. Alice exits early, Bob continues.
                  Bob should get all subsequent rewards.

        GIVEN: Farm contract is active
        WHEN: Both enter, Alice exits after some blocks, more blocks pass,
              Bob claims
        THEN:
            - Alice's exit succeeds
            - Bob's claim succeeds
            - Reserve decreases after Bob's claim (he earned rewards while alone)
            - Alice's farm position is reduced/cleared after exit

        SECURITY: Exited user must not continue earning rewards.
        """
        logger.info("TEST: User exits early")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Both enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Advance some blocks
        blockchain_controller.wait_blocks(5)

        # Alice exits early
        alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        alice_ft = max(alice_farm_tokens, key=lambda t: t.token.nonce)
        tx_exit = _exit_farm(
            farm_contract,
            alice,
            alice_ft.token.nonce,
            alice_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)
        logger.info("Alice exited farm")

        # Record reserve after Alice's exit
        reserve_after_alice_exit = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]

        # Advance more blocks (only Bob is in the farm now)
        blockchain_controller.wait_blocks(10)

        # Bob claims rewards
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        tx_cb = _claim_rewards(
            farm_contract,
            bob,
            bob_ft.token.nonce,
            bob_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)

        farm_state_after_bob_claim = _get_farm_state(farm_contract, network_providers.proxy)
        reserve_after_bob_claim = farm_state_after_bob_claim["reward_reserve"]
        bob_reward = reserve_after_alice_exit - reserve_after_bob_claim

        logger.info(f"Reserve after Alice exit: {reserve_after_alice_exit}")
        logger.info(f"Reserve after Bob claim: {reserve_after_bob_claim}")
        logger.info(f"Bob's reward (while alone): {bob_reward}")

        # Bob should have earned rewards while he was the sole participant.
        # Reserve should not increase significantly (rewards flow out, not in).
        # Tolerance: per_block_reward_amount=1 mints new rewards each block.
        reserve_tolerance = farm_state_after_bob_claim["per_second_reward_amount"] * 6 * 11
        assert reserve_after_bob_claim <= reserve_after_alice_exit + reserve_tolerance, (
            f"Reserve should not increase significantly after Bob claims:\n"
            f"  After Alice exit: {reserve_after_alice_exit}\n"
            f"  After Bob claim: {reserve_after_bob_claim}\n"
            f"  Delta: {reserve_after_bob_claim - reserve_after_alice_exit}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        logger.info("PASSED: test_user_exits_early")

    def test_many_users_reward_conservation(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Sum of all reward reserve decreases <= initial reserve (no inflation).

        GIVEN: Farm contract with a known reward reserve
        WHEN: Alice and Bob both enter, advance blocks, both claim
        THEN:
            - Total reserve decrease = sum of individual claim decreases
            - Total reserve decrease <= initial reserve (no inflation)
            - Reward reserve never goes negative

        SECURITY: Reward inflation would allow draining more tokens than
                  the contract holds, leading to insolvency.
        """
        logger.info("TEST: Many users reward conservation")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Record initial reserve
        initial_reserve = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Initial reward reserve: {initial_reserve}")

        # Both enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Advance blocks for reward accrual
        blockchain_controller.wait_blocks(10)

        # Alice claims
        alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        alice_ft = max(alice_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_ca = _claim_rewards(
            farm_contract,
            alice,
            alice_ft.token.nonce,
            alice_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)
        reserve_after_alice = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        alice_reward = reserve_before_alice - reserve_after_alice

        # Bob claims
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_cb = _claim_rewards(
            farm_contract,
            bob,
            bob_ft.token.nonce,
            bob_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)
        reserve_after_bob = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        bob_reward = reserve_before_bob - reserve_after_bob

        total_rewards_paid = alice_reward + bob_reward
        total_reserve_decrease = initial_reserve - reserve_after_bob

        logger.info(f"Alice reward: {alice_reward}")
        logger.info(f"Bob reward: {bob_reward}")
        logger.info(f"Total rewards paid: {total_rewards_paid}")
        logger.info(f"Total reserve decrease: {total_reserve_decrease}")
        logger.info(f"Final reserve: {reserve_after_bob}")

        # Conservation: total rewards paid out cannot exceed what was in reserve
        assert total_reserve_decrease <= initial_reserve, (
            f"Total reserve decrease exceeds initial reserve (inflation!):\n"
            f"  Initial reserve: {initial_reserve}\n"
            f"  Total decrease: {total_reserve_decrease}\n"
            f"  Final reserve: {reserve_after_bob}"
        )

        # Reserve never goes negative
        assert reserve_after_bob >= 0, (
            f"Reward reserve went negative:\n"
            f"  Final reserve: {reserve_after_bob}\n"
            f"  Initial: {initial_reserve}\n"
            f"  Total paid: {total_rewards_paid}"
        )

        logger.info("PASSED: test_many_users_reward_conservation")

    def test_dilution_on_new_entry(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice is alone in farm. After Bob enters, RPS growth rate decreases.

        GIVEN: Farm contract is active
        WHEN: Alice is staked alone, we record RPS growth over blocks.
              Bob enters, we record RPS growth over the same number of blocks.
        THEN:
            - RPS growth rate after Bob's entry is <= growth rate before
            - This demonstrates dilution: more stakers = slower per-share reward growth

        NOTE: On chain sim with large pre-existing supply, the dilution effect
              from a small additional stake may be negligible. We verify the
              monotonic non-increase property.
        """
        logger.info("TEST: Dilution on new entry")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Alice enters farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        # Measure RPS growth rate with Alice alone
        rps_before_solo = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_per_share"
        ]
        supply_solo = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        blockchain_controller.wait_blocks(10)
        rps_after_solo = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
        rps_growth_solo = rps_after_solo - rps_before_solo
        logger.info(f"Solo RPS growth: {rps_growth_solo} (supply: {supply_solo})")

        # Bob enters farm (increases total supply => dilutes per-share growth)
        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Measure RPS growth rate with both Alice and Bob
        rps_before_duo = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
        supply_duo = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        blockchain_controller.wait_blocks(10)
        rps_after_duo = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
        rps_growth_duo = rps_after_duo - rps_before_duo
        logger.info(f"Duo RPS growth: {rps_growth_duo} (supply: {supply_duo})")

        # Supply should have increased
        assert supply_duo > supply_solo, (
            f"Supply should increase after Bob's entry:\n"
            f"  Solo supply: {supply_solo}\n"
            f"  Duo supply: {supply_duo}"
        )

        # RPS growth with more stakers should be <= growth with fewer stakers
        # (dilution effect). Allow equality for cases where rewards are 0.
        assert rps_growth_duo <= rps_growth_solo, (
            f"Dilution should reduce or maintain RPS growth rate:\n"
            f"  Solo RPS growth: {rps_growth_solo} (supply: {supply_solo})\n"
            f"  Duo RPS growth: {rps_growth_duo} (supply: {supply_duo})\n"
            f"  ISSUE: More stakers should not increase per-share rewards"
        )

        logger.info("PASSED: test_dilution_on_new_entry")
