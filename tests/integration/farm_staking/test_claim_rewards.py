"""
Farm Staking Integration Tests - Category 4: Claim Rewards

Tests the claimRewards endpoint covering:
- Basic reward claiming (receive farming token + new farm token)
- Proportional rewards (multiple users)
- Consecutive claims (no double-counting)
- Zero accrued rewards (claim immediately after staking)
- Farm token RPS updates
- Accumulated rewards accounting
- Error conditions
- APR-bounded rewards

Coverage: 8 tests (P0 - critical path)
"""

import pytest
from multiversx_sdk import Address
from utils.logger import get_logger
from utils.utils_chain import nominated_amount, decode_merged_attributes
from utils.utils_tx import ESDTToken, multi_esdt_endpoint_call
from utils import decoding_structures
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _get_staking_state,
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _claim_rewards,
    _get_farm_tokens_for_user,
)

logger = get_logger(__name__)


@pytest.mark.usefixtures("seed_staking_rewards")
class TestClaimRewards:
    """Test suite for claimRewards endpoint"""

    def test_claim_rewards_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test basic reward claiming: receive farming token + new farm token with updated RPS"""
        logger.info("TEST: Claim rewards basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
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

        # Get farm token
        farm_tokens_before = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        farm_token = max(farm_tokens_before, key=lambda t: t.token.nonce)
        old_nonce = farm_token.token.nonce

        # Wait for rewards to accumulate
        blockchain_controller.wait_blocks(10)

        # Get farming token balance before claiming
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.balance for t in all_tokens_before if t.identifier == farming_token
        )

        # Claim rewards
        tx_claim = _claim_rewards(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Verify rewards received (farming token balance increased)
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.balance for t in all_tokens_after if t.identifier == farming_token
        )

        rewards = farming_balance_after - farming_balance_before
        assert rewards > 0, (
            f"Expected rewards > 0:\n"
            f"  Before: {farming_balance_before}\n"
            f"  After: {farming_balance_after}"
        )

        # Verify new farm token with updated RPS
        farm_tokens_after = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        new_farm_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        new_nonce = new_farm_token.token.nonce

        # New token should have different nonce (old burned, new minted)
        assert new_nonce != old_nonce, (
            f"Expected new farm token nonce:\n"
            f"  Old: {old_nonce}\n"
            f"  New: {new_nonce}"
        )

        logger.info(
            f"✓ Claimed {rewards} {farming_token} rewards, "
            f"farm token updated: nonce {old_nonce} → {new_nonce}"
        )

    def test_claim_rewards_proportional(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that two users receive rewards proportional to their staked amounts"""
        logger.info("TEST: Claim rewards proportional")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        base_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        alice_amount = base_amount * 2  # Alice stakes 2x
        bob_amount = base_amount

        # Both stake
        ensure_esdt_amounts(alice, {farming_token: alice_amount})
        tx_alice = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            alice_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_alice, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: bob_amount})
        tx_bob = _stake_farm(
            staking_contract,
            bob,
            farming_token,
            bob_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_bob, network_providers.proxy)

        # Wait for rewards
        blockchain_controller.wait_blocks(15)

        # Get balances before claiming
        alice_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        alice_balance_before = sum(t.balance for t in alice_tokens_before if t.identifier == farming_token)

        bob_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(bob.address)
        bob_balance_before = sum(t.balance for t in bob_tokens_before if t.identifier == farming_token)

        # Both claim
        alice_farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        alice_farm_token = max(alice_farm_tokens, key=lambda t: t.token.nonce)

        bob_farm_tokens = _get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy)
        bob_farm_token = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        tx_claim_alice = _claim_rewards(
            staking_contract,
            alice,
            alice_farm_token.token.nonce,
            alice_farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim_alice, network_providers.proxy)

        tx_claim_bob = _claim_rewards(
            staking_contract,
            bob,
            bob_farm_token.token.nonce,
            bob_farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim_bob, network_providers.proxy)

        # Calculate rewards
        alice_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        alice_balance_after = sum(t.balance for t in alice_tokens_after if t.identifier == farming_token)
        alice_rewards = alice_balance_after - alice_balance_before

        bob_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(bob.address)
        bob_balance_after = sum(t.balance for t in bob_tokens_after if t.identifier == farming_token)
        bob_rewards = bob_balance_after - bob_balance_before

        # Alice staked 2x, should get ~2x rewards (allowing 20% tolerance for timing)
        ratio = alice_rewards / bob_rewards if bob_rewards > 0 else 0
        expected_ratio = alice_amount / bob_amount  # Should be 2.0

        assert 1.6 <= ratio <= 2.4, (
            f"Rewards not proportional to stake:\n"
            f"  Alice staked: {alice_amount} (2x)\n"
            f"  Bob staked: {bob_amount} (1x)\n"
            f"  Alice rewards: {alice_rewards}\n"
            f"  Bob rewards: {bob_rewards}\n"
            f"  Actual ratio: {ratio:.2f}\n"
            f"  Expected ratio: ~{expected_ratio:.2f}\n"
            f"  Tolerance: 1.6-2.4"
        )

        logger.info(
            f"✓ Proportional rewards: Alice ({alice_amount}) got {alice_rewards}, "
            f"Bob ({bob_amount}) got {bob_rewards}, ratio={ratio:.2f}"
        )

    def test_claim_rewards_consecutive(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test claiming twice: second claim reflects only new rewards (no double-counting)"""
        logger.info("TEST: Claim rewards consecutive")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
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

        # Wait and claim first time
        blockchain_controller.wait_blocks(10)

        farm_tokens_1 = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token_1 = max(farm_tokens_1, key=lambda t: t.token.nonce)

        all_tokens_before_1 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before_1 = sum(t.balance for t in all_tokens_before_1 if t.identifier == farming_token)

        tx_claim_1 = _claim_rewards(
            staking_contract,
            alice,
            farm_token_1.token.nonce,
            farm_token_1.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim_1, network_providers.proxy)

        all_tokens_after_1 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after_1 = sum(t.balance for t in all_tokens_after_1 if t.identifier == farming_token)
        rewards_1 = balance_after_1 - balance_before_1

        logger.info(f"  First claim: {rewards_1} rewards")

        # Wait again and claim second time
        blockchain_controller.wait_blocks(10)

        farm_tokens_2 = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token_2 = max(farm_tokens_2, key=lambda t: t.token.nonce)

        all_tokens_before_2 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before_2 = sum(t.balance for t in all_tokens_before_2 if t.identifier == farming_token)

        tx_claim_2 = _claim_rewards(
            staking_contract,
            alice,
            farm_token_2.token.nonce,
            farm_token_2.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim_2, network_providers.proxy)

        all_tokens_after_2 = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after_2 = sum(t.balance for t in all_tokens_after_2 if t.identifier == farming_token)
        rewards_2 = balance_after_2 - balance_before_2

        logger.info(f"  Second claim: {rewards_2} rewards")

        # Both claims should have positive rewards (waited same time)
        assert rewards_1 > 0, "First claim should have rewards"
        assert rewards_2 > 0, "Second claim should have rewards"

        # Second claim should be similar to first (same wait time, no double-counting)
        # Allow 50% tolerance due to RPS changes and timing
        ratio = rewards_2 / rewards_1 if rewards_1 > 0 else 0
        assert 0.5 <= ratio <= 1.5, (
            f"Second claim rewards suspiciously different:\n"
            f"  First claim: {rewards_1}\n"
            f"  Second claim: {rewards_2}\n"
            f"  Ratio: {ratio:.2f} (expected ~1.0)"
        )

        logger.info(f"✓ Consecutive claims: first={rewards_1}, second={rewards_2}, no double-counting")

    def test_claim_rewards_zero_accrued(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test claiming immediately after staking (no time passed) — should succeed with zero/minimal rewards"""
        logger.info("TEST: Claim rewards zero accrued")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
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

        # Claim IMMEDIATELY (no wait)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before = sum(t.balance for t in all_tokens_before if t.identifier == farming_token)

        tx_claim = _claim_rewards(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )

        # Should succeed (not error)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after = sum(t.balance for t in all_tokens_after if t.identifier == farming_token)
        rewards = balance_after - balance_before

        # Rewards should be zero or very small (minimal time passed during tx processing)
        max_expected = stake_amount // 100  # 1% tolerance
        assert rewards <= max_expected, (
            f"Immediate claim should have minimal rewards:\n"
            f"  Rewards: {rewards}\n"
            f"  Max expected: {max_expected}"
        )

        logger.info(f"✓ Immediate claim succeeded with {rewards} rewards (no error)")

    def test_claim_rewards_updates_farm_token_rps(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that new farm token has current RPS as attribute"""
        logger.info("TEST: Claim rewards updates farm token RPS")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
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

        # Wait for RPS to increase
        blockchain_controller.wait_blocks(10)

        # Get global RPS before claiming
        global_rps_before = staking_contract.get_reward_per_share(network_providers.proxy)

        # Claim
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_claim = _claim_rewards(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Get global RPS after claiming
        global_rps_after = staking_contract.get_reward_per_share(network_providers.proxy)

        # Get new farm token and check RPS attribute
        farm_tokens_after = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        new_farm_token = max(farm_tokens_after, key=lambda t: t.token.nonce)

        attrs_hex = new_farm_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES)
        token_rps = attrs["reward_per_share"]

        # Token RPS should be between before and after (snapshot at claim time)
        assert global_rps_before <= token_rps <= global_rps_after, (
            f"Token RPS should be current global RPS:\n"
            f"  Global RPS before: {global_rps_before}\n"
            f"  Token RPS: {token_rps}\n"
            f"  Global RPS after: {global_rps_after}"
        )

        logger.info(
            f"✓ Farm token RPS updated: {token_rps} "
            f"(global range: {global_rps_before}-{global_rps_after})"
        )

    def test_claim_rewards_reduces_accumulated(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that getAccumulatedRewards increases after claim (accounting consistency)"""
        logger.info("TEST: Claim rewards reduces accumulated")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get accumulated rewards before
        accumulated_before = staking_contract.get_accumulated_rewards(network_providers.proxy)

        # Stake and wait
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

        blockchain_controller.wait_blocks(10)

        # Claim
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_claim = _claim_rewards(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Get accumulated rewards after
        accumulated_after = staking_contract.get_accumulated_rewards(network_providers.proxy)

        # Accumulated should increase (more rewards distributed)
        assert accumulated_after >= accumulated_before, (
            f"Accumulated rewards should increase:\n"
            f"  Before: {accumulated_before}\n"
            f"  After: {accumulated_after}"
        )

        increase = accumulated_after - accumulated_before
        logger.info(f"✓ Accumulated rewards increased by {increase}")

    def test_claim_rewards_wrong_token_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that sending non-farm token to claimRewards fails"""
        logger.info("TEST: Claim rewards wrong token fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        # Use a different token
        wrong_token = "WEGLD-bd4d79"

        # Fund Alice
        ensure_esdt_amounts(alice, {wrong_token: nominated_amount(1)})

        # Try to claim with a real wrong-token transfer payload
        alice.sync_nonce(network_providers.proxy)
        tx_hash = multi_esdt_endpoint_call(
            "claimRewards wrong token",
            network_providers.proxy,
            50_000_000,
            alice,
            Address.new_from_bech32(staking_contract.address),
            "claimRewards",
            [[ESDTToken(wrong_token, 0, nominated_amount(1))]],
        )
        blockchain_controller.wait_for_tx(tx_hash)

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Claiming with wrong token correctly failed")

    def test_claim_rewards_apr_bounded(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that claimed rewards respect APR cap"""
        logger.info("TEST: Claim rewards APR bounded")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get max_apr for calculations
        max_apr = staking_contract.get_max_apr(network_providers.proxy)

        # Stake
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

        # Wait for rewards
        blocks_to_wait = 20
        blockchain_controller.wait_blocks(blocks_to_wait)

        # Get balance before claiming
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before = sum(t.balance for t in all_tokens_before if t.identifier == farming_token)

        # Claim
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_claim = _claim_rewards(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Calculate actual rewards
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after = sum(t.balance for t in all_tokens_after if t.identifier == farming_token)
        actual_rewards = balance_after - balance_before

        # Calculate APR-bounded maximum
        elapsed_seconds = blocks_to_wait * 6
        SECONDS_IN_YEAR = 31_536_000
        MAX_PERCENT = 10_000

        apr_bounded_max = (stake_amount * max_apr * elapsed_seconds) // (MAX_PERCENT * SECONDS_IN_YEAR)

        # Actual rewards should not significantly exceed APR cap
        tolerance = apr_bounded_max // 10  # 10% tolerance
        assert actual_rewards <= apr_bounded_max + tolerance, (
            f"Claimed rewards exceed APR cap:\n"
            f"  Stake amount: {stake_amount}\n"
            f"  Max APR: {max_apr} (basis points)\n"
            f"  Elapsed seconds: ~{elapsed_seconds}\n"
            f"  APR-bounded max: {apr_bounded_max}\n"
            f"  Actual rewards: {actual_rewards}\n"
            f"  Tolerance: {tolerance}"
        )

        logger.info(
            f"✓ Claimed rewards within APR cap: {actual_rewards} <= {apr_bounded_max + tolerance} "
            f"(max_apr={max_apr})"
        )
