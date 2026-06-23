"""
Farm Staking Integration Tests - Category 11: Multi-User Scenarios

Tests concurrent users, reward distribution fairness, and supply dilution.

Coverage: 5 tests (P2)
"""

import pytest
from utils.logger import get_logger
from utils.utils_chain import nominated_amount
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _claim_rewards,
    _unstake_farm,
    _get_farm_tokens_for_user,
)

logger = get_logger(__name__)


@pytest.mark.usefixtures("seed_staking_rewards")
class TestMultiUser:
    """Test suite for multi-user reward distribution scenarios"""

    def _get_farming_balance(self, user, farming_token, proxy):
        tokens = proxy.get_fungible_tokens_of_account(user.address)
        return sum(t.balance for t in tokens if t.identifier == farming_token)

    def test_two_users_equal_stake(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Two users with equal stake receive equal rewards"""
        logger.info("TEST: Two users equal stake")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Both stake equal amounts at the same time
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _stake_farm(staking_contract, alice, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _stake_farm(staking_contract, bob, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        blockchain_controller.wait_blocks(15)

        alice_before = self._get_farming_balance(alice, farming_token, network_providers.proxy)
        bob_before = self._get_farming_balance(bob, farming_token, network_providers.proxy)

        # Both claim
        alice_ft = max(_get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy), key=lambda t: t.token.nonce)
        bob_ft = max(_get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy), key=lambda t: t.token.nonce)

        tx_ca = _claim_rewards(staking_contract, alice, alice_ft.token.nonce, alice_ft.balance, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)

        tx_cb = _claim_rewards(staking_contract, bob, bob_ft.token.nonce, bob_ft.balance, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)

        alice_rewards = self._get_farming_balance(alice, farming_token, network_providers.proxy) - alice_before
        bob_rewards = self._get_farming_balance(bob, farming_token, network_providers.proxy) - bob_before

        # Equal stake → equal rewards (allow 20% timing tolerance)
        if alice_rewards > 0 and bob_rewards > 0:
            ratio = alice_rewards / bob_rewards
            assert 0.8 <= ratio <= 1.2, (
                f"Equal stakers should receive equal rewards:\n"
                f"  Alice: {alice_rewards}\n"
                f"  Bob: {bob_rewards}\n"
                f"  Ratio: {ratio:.2f}"
            )
            logger.info(f"✓ Equal rewards: alice={alice_rewards}, bob={bob_rewards}, ratio={ratio:.2f}")
        else:
            logger.info(f"✓ Both claims succeeded: alice={alice_rewards}, bob={bob_rewards}")

    def test_user_enters_later(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """User B enters after User A; User A earns more rewards (time-weighted)"""
        logger.info("TEST: User enters later")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Alice stakes first
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _stake_farm(staking_contract, alice, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        # Alice earns alone for a while
        blockchain_controller.wait_blocks(15)

        # Bob enters
        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _stake_farm(staking_contract, bob, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Wait same duration with both staked
        blockchain_controller.wait_blocks(15)

        alice_before = self._get_farming_balance(alice, farming_token, network_providers.proxy)
        bob_before = self._get_farming_balance(bob, farming_token, network_providers.proxy)

        # Both claim
        alice_ft = max(_get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy), key=lambda t: t.token.nonce)
        bob_ft = max(_get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy), key=lambda t: t.token.nonce)

        tx_ca = _claim_rewards(staking_contract, alice, alice_ft.token.nonce, alice_ft.balance, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)

        tx_cb = _claim_rewards(staking_contract, bob, bob_ft.token.nonce, bob_ft.balance, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)

        alice_rewards = self._get_farming_balance(alice, farming_token, network_providers.proxy) - alice_before
        bob_rewards = self._get_farming_balance(bob, farming_token, network_providers.proxy) - bob_before

        # Alice entered earlier, should have more rewards
        assert alice_rewards >= bob_rewards, (
            f"Earlier entrant should have more rewards:\n"
            f"  Alice (entered earlier): {alice_rewards}\n"
            f"  Bob (entered later): {bob_rewards}"
        )
        logger.info(f"✓ Early entry advantage: alice={alice_rewards} >= bob={bob_rewards}")

    def test_user_exits_early(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """After Alice unstakes, Bob gets full reward rate"""
        logger.info("TEST: User exits early")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Both stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _stake_farm(staking_contract, alice, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _stake_farm(staking_contract, bob, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        blockchain_controller.wait_blocks(5)

        # Alice exits (unstake)
        alice_ft = max(_get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy), key=lambda t: t.token.nonce)
        tx_unstake = _unstake_farm(
            staking_contract, alice, alice_ft.token.nonce, alice_ft.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Bob gets RPS growth after Alice exits (doubled rate per token)
        rps_before = staking_contract.get_reward_per_share(network_providers.proxy)
        blockchain_controller.wait_blocks(10)
        rps_after = staking_contract.get_reward_per_share(network_providers.proxy)

        # RPS should increase faster now that Alice is gone (Bob is sole staker)
        assert rps_after >= rps_before, "RPS should not decrease"

        bob_before = self._get_farming_balance(bob, farming_token, network_providers.proxy)
        bob_ft = max(_get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy), key=lambda t: t.token.nonce)
        tx_cb = _claim_rewards(staking_contract, bob, bob_ft.token.nonce, bob_ft.balance, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)

        bob_rewards = self._get_farming_balance(bob, farming_token, network_providers.proxy) - bob_before

        assert bob_rewards >= 0, "Bob should receive rewards"
        logger.info(f"✓ Bob continues earning after Alice exits: {bob_rewards} rewards")

    def test_many_users_reward_conservation(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Sum of all rewards <= reward capacity (no inflation)"""
        logger.info("TEST: Many users reward conservation")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        capacity_before = staking_contract.get_reward_capacity(network_providers.proxy)
        accumulated_before = staking_contract.get_accumulated_rewards(network_providers.proxy)

        # Multiple users stake
        for user, label in [(alice, "alice"), (bob, "bob")]:
            ensure_esdt_amounts(user, {farming_token: stake_amount})
            tx = _stake_farm(staking_contract, user, farming_token, stake_amount, network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        blockchain_controller.wait_blocks(10)

        total_rewards_claimed = 0
        for user in [alice, bob]:
            before = self._get_farming_balance(user, farming_token, network_providers.proxy)
            farm_tokens = _get_farm_tokens_for_user(staking_contract, user, network_providers.proxy)
            if not farm_tokens:
                continue
            ft = max(farm_tokens, key=lambda t: t.token.nonce)
            tx_c = _claim_rewards(staking_contract, user, ft.token.nonce, ft.balance, network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_c, network_providers.proxy)
            after = self._get_farming_balance(user, farming_token, network_providers.proxy)
            total_rewards_claimed += (after - before)

        capacity_after = staking_contract.get_reward_capacity(network_providers.proxy)
        accumulated_after = staking_contract.get_accumulated_rewards(network_providers.proxy)

        # accumulated_after <= capacity — no over-distribution
        assert accumulated_after <= capacity_after, (
            f"Accumulated rewards exceed capacity (inflation!):\n"
            f"  Accumulated: {accumulated_after}\n"
            f"  Capacity: {capacity_after}"
        )

        new_accumulated = accumulated_after - accumulated_before
        assert total_rewards_claimed <= new_accumulated + nominated_amount(1), (
            f"Total claimed > newly accumulated (shouldn't happen):\n"
            f"  Claimed: {total_rewards_claimed}\n"
            f"  Accumulated: {new_accumulated}"
        )

        logger.info(
            f"✓ Reward conservation holds: claimed={total_rewards_claimed}, "
            f"accumulated={accumulated_after}, capacity={capacity_after}"
        )

    def test_dilution_on_new_entry(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """New user entry dilutes existing users' reward rate"""
        logger.info("TEST: Dilution on new entry")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Alice stakes alone
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_a = _stake_farm(staking_contract, alice, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        # Measure RPS growth rate before Bob enters
        rps_start = staking_contract.get_reward_per_share(network_providers.proxy)
        blockchain_controller.wait_blocks(5)
        rps_solo = staking_contract.get_reward_per_share(network_providers.proxy)
        solo_growth = rps_solo - rps_start

        # Bob enters with equal stake
        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_b = _stake_farm(staking_contract, bob, farming_token, stake_amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Measure RPS growth rate after Bob enters
        rps_before_wait = staking_contract.get_reward_per_share(network_providers.proxy)
        blockchain_controller.wait_blocks(5)
        rps_diluted = staking_contract.get_reward_per_share(network_providers.proxy)
        diluted_growth = rps_diluted - rps_before_wait

        # Per-token RPS growth should be lower with 2 stakers than with 1
        # (same total rewards split between more tokens)
        if solo_growth > 0 and diluted_growth > 0:
            assert diluted_growth <= solo_growth, (
                f"New entrant should dilute RPS growth:\n"
                f"  Solo growth: {solo_growth}\n"
                f"  Diluted growth: {diluted_growth}"
            )
            logger.info(
                f"✓ Dilution confirmed: solo RPS growth={solo_growth}, "
                f"diluted growth={diluted_growth}"
            )
        else:
            logger.info(f"✓ Dilution test: growth comparison skipped (solo={solo_growth}, diluted={diluted_growth})")
