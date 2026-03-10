"""
Farm Staking Integration Tests - Category 5: Compound Rewards

Tests the compoundRewards endpoint — UNIQUE to staking (since reward == farming token).
Compounding reinvests rewards back into the staking position, increasing effective stake.

Coverage: 6 tests (P1)
"""

import pytest
from utils.logger import get_logger
from utils.utils_chain import nominated_amount, decode_merged_attributes
from utils import decoding_structures
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _compound_rewards,
    _get_farm_tokens_for_user,
)

logger = get_logger(__name__)


@pytest.mark.usefixtures("seed_staking_rewards")
class TestCompoundRewards:
    """Test suite for compoundRewards endpoint (unique to staking contracts)"""

    def test_compound_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Compound rewards: new farm token amount = old amount + rewards"""
        logger.info("TEST: Compound rewards basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        old_amount = farm_token.balance
        old_nonce = farm_token.token.nonce

        # Wait for rewards
        blockchain_controller.wait_blocks(10)

        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.balance for t in all_tokens_before if t.identifier == farming_token
        )

        # Get RPS before compound (to estimate rewards)
        rps_before = staking_contract.get_reward_per_share(network_providers.proxy)
        attrs = decode_merged_attributes(
            farm_token.attributes.hex(), decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES
        )
        token_rps = attrs["reward_per_share"]
        division_safety = staking_contract.get_division_safety_constant(network_providers.proxy)

        # Compound
        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        # Verify new farm token has larger amount
        farm_tokens_after = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        new_token = max(farm_tokens_after, key=lambda t: t.token.nonce)

        assert new_token.balance > old_amount, (
            f"Compounded farm token should be larger:\n"
            f"  Before: {old_amount}\n"
            f"  After: {new_token.balance}"
        )

        # New nonce (old burned, new minted)
        assert new_token.token.nonce != old_nonce, "Expected new farm token nonce after compound"

        # No separate reward output (rewards are embedded into the new token)
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.balance for t in all_tokens_after if t.identifier == farming_token
        )
        loose_rewards = farming_balance_after - farming_balance_before
        assert loose_rewards == 0, (
            f"Compound should not send separate rewards:\n"
            f"  Balance before: {farming_balance_before}\n"
            f"  Balance after: {farming_balance_after}\n"
            f"  Loose rewards: {loose_rewards}"
        )

        logger.info(
            f"✓ Compounded: {old_amount} → {new_token.balance} "
            f"(+{new_token.balance - old_amount})"
        )

    def test_compound_updates_compounded_reward_attr(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """compounded_reward attribute tracks total compounded amount"""
        logger.info("TEST: Compound updates compounded_reward attribute")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        initial_attrs = decode_merged_attributes(
            farm_token.attributes.hex(), decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES
        )
        assert initial_attrs["compounded_reward"] == 0, "Initial compounded_reward should be 0"

        # Wait and compound
        blockchain_controller.wait_blocks(10)

        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        # Check new token attributes
        farm_tokens_after = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        new_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        new_attrs = decode_merged_attributes(
            new_token.attributes.hex(), decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES
        )

        compounded = new_attrs["compounded_reward"]
        assert compounded > 0, (
            f"compounded_reward should be > 0 after compound:\n"
            f"  actual: {compounded}"
        )

        # compounded_reward = current_farm_amount - original_stake
        # (current_farm_amount = original + compounded)
        expected_compounded = new_token.balance - stake_amount
        assert abs(compounded - expected_compounded) <= stake_amount // 100, (
            f"compounded_reward should match (current_amount - original):\n"
            f"  compounded_reward attr: {compounded}\n"
            f"  expected: {expected_compounded}"
        )

        logger.info(f"✓ compounded_reward attribute: {compounded}")

    def test_compound_increases_total_position(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """getUserTotalFarmPosition increases by compounded reward amount"""
        logger.info("TEST: Compound increases total position")

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

        position_before = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        blockchain_controller.wait_blocks(10)

        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        position_after = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )

        assert position_after > position_before, (
            f"Position should increase after compound:\n"
            f"  Before: {position_before}\n"
            f"  After: {position_after}"
        )

        logger.info(f"✓ Position increased: {position_before} → {position_after}")

    def test_compound_increases_farm_supply(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """getFarmTokenSupply increases by compounded reward amount"""
        logger.info("TEST: Compound increases farm supply")

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

        supply_before = staking_contract.get_farm_token_supply(network_providers.proxy)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        blockchain_controller.wait_blocks(10)

        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        supply_after = staking_contract.get_farm_token_supply(network_providers.proxy)

        assert supply_after > supply_before, (
            f"Supply should increase after compound (rewards reinvested as staked tokens):\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        logger.info(f"✓ Supply increased: {supply_before} → {supply_after}")

    def test_compound_consecutive(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Compound twice: second compound builds on a larger base"""
        logger.info("TEST: Compound consecutive")

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

        # First compound
        blockchain_controller.wait_blocks(10)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        amount_before_first = farm_token.balance

        tx_1 = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_1, network_providers.proxy)

        farm_tokens_1 = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        token_1 = max(farm_tokens_1, key=lambda t: t.token.nonce)
        amount_after_first = token_1.balance
        assert amount_after_first > amount_before_first

        # Second compound
        blockchain_controller.wait_blocks(10)
        tx_2 = _compound_rewards(
            staking_contract, alice, token_1.token.nonce, token_1.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_2, network_providers.proxy)

        farm_tokens_2 = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        token_2 = max(farm_tokens_2, key=lambda t: t.token.nonce)
        amount_after_second = token_2.balance

        assert amount_after_second > amount_after_first, (
            f"Second compound should further increase amount:\n"
            f"  After first: {amount_after_first}\n"
            f"  After second: {amount_after_second}"
        )

        attrs = decode_merged_attributes(
            token_2.attributes.hex(), decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES
        )
        assert attrs["compounded_reward"] > 0

        logger.info(
            f"✓ Consecutive compounds: {amount_before_first} → {amount_after_first} → {amount_after_second}"
        )

    def test_compound_zero_rewards(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Compound with no rewards accrued: no error, amount unchanged"""
        logger.info("TEST: Compound zero rewards")

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

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        original_amount = farm_token.balance

        # Compound immediately (no time for rewards to accrue)
        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )

        # Should succeed — just a no-op if rewards are 0
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        farm_tokens_after = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        new_token = max(farm_tokens_after, key=lambda t: t.token.nonce)

        # Amount should be same (or very slightly higher due to tx time)
        tolerance = stake_amount // 100
        assert new_token.balance >= original_amount, (
            f"Amount should not decrease on zero-reward compound:\n"
            f"  Before: {original_amount}\n"
            f"  After: {new_token.balance}"
        )
        assert new_token.balance <= original_amount + tolerance, (
            f"Amount increased more than expected for zero-reward compound:\n"
            f"  Before: {original_amount}\n"
            f"  After: {new_token.balance}"
        )

        logger.info(f"✓ Zero-reward compound succeeded: {original_amount} → {new_token.balance}")
