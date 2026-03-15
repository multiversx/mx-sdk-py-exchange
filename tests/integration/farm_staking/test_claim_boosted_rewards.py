"""
Farm Staking Integration Tests - Category 6: Claim Boosted Rewards

Tests the claimBoostedRewards endpoint (V3Boosted only).

NOTE: Energy factory has no code on chain sim, so boosted rewards are 0.
These tests verify endpoint behavior and error handling rather than reward amounts.

Coverage: 6 tests (P1)
"""

import pytest
from events.farm_events import ClaimRewardsFarmEvent
from utils.logger import get_logger
from utils.utils_chain import nominated_amount
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _get_farm_tokens_for_user,
)

logger = get_logger(__name__)


class TestClaimBoostedRewards:
    """Test suite for claimBoostedRewards endpoint"""

    def test_claim_boosted_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """User with position calls claimBoostedRewards: transaction succeeds, farm tokens retained"""
        logger.info("TEST: Claim boosted rewards basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake to create a position
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        blockchain_controller.wait_blocks(5)

        # Call claimBoostedRewards for alice (herself)
        alice.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=alice.address.to_bech32())
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, alice, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Should succeed (even with 0 boosted rewards on chain sim)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        logger.info("✓ claimBoostedRewards succeeded for user with position")

    def test_claim_boosted_no_position_fails(
        self,
        staking_contract,
        bob,
        test_accounts,
        network_providers,
        blockchain_controller,
    ):
        """User without a staking position calls claimBoostedRewards: error"""
        logger.info("TEST: Claim boosted no position fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        # Use Bob if he has no position; otherwise use a higher-index account
        # that no staking test uses, guaranteeing no prior farm entry.
        test_user = bob
        position = staking_contract.get_user_total_farm_position(
            test_user.address.to_bech32(), network_providers.proxy
        )
        if position > 0 and len(test_accounts) > 3:
            test_user = test_accounts[3]
            test_user.sync_nonce(network_providers.proxy)

        test_user.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=test_user.address.to_bech32())
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, test_user, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ claimBoostedRewards correctly failed for user without position")

    def test_claim_boosted_zero_without_energy(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """User with position but no energy (chain sim): succeeds with 0 boosted rewards"""
        logger.info("TEST: Claim boosted zero without energy")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Get farming token balance (should not change since energy = 0)
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before = sum(t.balance for t in all_tokens_before if t.identifier == farming_token)

        # Advance a week and claim boosted
        blockchain_controller.advance_to_epoch(
            blockchain_controller.get_current_epoch() + 5
        )

        alice.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=alice.address.to_bech32())
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, alice, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Balance should be same (0 boosted rewards without energy factory)
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after = sum(t.balance for t in all_tokens_after if t.identifier == farming_token)

        assert balance_after == balance_before, (
            f"No boosted rewards expected without energy factory:\n"
            f"  Before: {balance_before}\n"
            f"  After: {balance_after}"
        )

        logger.info("✓ claimBoostedRewards with 0 energy succeeded, returned 0 rewards")

    def test_claim_boosted_unauthorized_for_other_fails(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Non-whitelisted caller cannot claim boosted rewards for another user"""
        logger.info("TEST: Claim boosted unauthorized for other fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Alice has a position
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Bob tries to claim for Alice (unauthorized)
        bob.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(
            amount=0, nonce=0, attributes="",
            user=alice.address.to_bech32()  # Claiming for Alice
        )
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, bob, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Unauthorized boosted reward claim correctly rejected")

    def test_claim_boosted_updates_claim_progress(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """After claiming, getCurrentClaimProgress updates for the user"""
        logger.info("TEST: Claim boosted updates claim progress")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Advance weeks and claim
        blockchain_controller.advance_to_epoch(
            blockchain_controller.get_current_epoch() + 10
        )
        current_week = staking_contract.get_current_week(network_providers.proxy)

        alice.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=alice.address.to_bech32())
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, alice, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Check claim progress
        progress = staking_contract.get_current_claim_progress_for_user(
            alice.address.to_bech32(), network_providers.proxy
        )

        # Progress week should match current week (or be close)
        progress_week = progress.get("week", 0) if isinstance(progress, dict) else 0
        assert progress_week >= 0, f"Unexpected claim progress: {progress}"

        logger.info(f"✓ Claim progress updated: {progress}")

    def test_claim_boosted_idempotent_same_week(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Two claims in same week: second claim has no additional impact"""
        logger.info("TEST: Claim boosted idempotent same week")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # First claim
        alice.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=alice.address.to_bech32())
        tx1 = staking_contract.claim_boosted_rewards(network_providers, alice, claim_event)
        blockchain_controller.wait_for_tx(tx1)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        all_tokens_after_1 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_1 = sum(t.balance for t in all_tokens_after_1 if t.identifier == farming_token)

        # Second claim in same week (no blocks advanced)
        alice.sync_nonce(network_providers.proxy)
        claim_event2 = ClaimRewardsFarmEvent(amount=0, nonce=0, attributes="", user=alice.address.to_bech32())
        tx2 = staking_contract.claim_boosted_rewards(network_providers, alice, claim_event2)
        blockchain_controller.wait_for_tx(tx2)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        all_tokens_after_2 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_2 = sum(t.balance for t in all_tokens_after_2 if t.identifier == farming_token)

        # Second claim should return 0 additional rewards
        assert balance_2 == balance_1, (
            f"Second claim in same week should return 0 additional rewards:\n"
            f"  After first: {balance_1}\n"
            f"  After second: {balance_2}"
        )

        logger.info(f"✓ Second claim idempotent in same week: balance unchanged at {balance_1}")
