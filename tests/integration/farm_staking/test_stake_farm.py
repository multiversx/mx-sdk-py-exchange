"""
Farm Staking Integration Tests - Category 1: Stake Farm

Tests the stakeFarm endpoint covering:
- Basic staking functionality
- Position tracking and updates
- Multiple positions (separate NFTs vs merged)
- Token attributes validation
- Supply tracking
- Error conditions (zero amount, wrong token, paused contract)

Coverage: 10 tests (P0 - critical path)
"""

import pytest
from utils.logger import get_logger
from utils.utils_chain import nominated_amount, decode_merged_attributes
from utils import decoding_structures
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _get_staking_state,
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _get_farm_tokens_for_user,
    _ensure_deployer_has_egld,
)

logger = get_logger(__name__)


class TestStakeFarm:
    """Test suite for stakeFarm endpoint"""

    def test_stake_farm_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test basic staking: stake farming tokens, receive farm token NFT"""
        logger.info("TEST: Stake farm basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Fund Alice with farming tokens
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        # Get Alice's farm tokens before staking
        farm_tokens_before = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )

        # Stake farming tokens
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )

        # Assert transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify farm token minted
        farm_tokens_after = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        assert len(farm_tokens_after) == len(farm_tokens_before) + 1, (
            f"Expected 1 new farm token. "
            f"Before: {len(farm_tokens_before)}, After: {len(farm_tokens_after)}"
        )

        # Verify farm token amount
        new_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        assert new_token.balance == stake_amount, (
            f"Farm token amount mismatch:\n"
            f"  Expected: {stake_amount}\n"
            f"  Actual: {new_token.balance}"
        )

        logger.info(f"✓ Staked {stake_amount} {farming_token}, received farm token nonce {new_token.token.nonce}")

    def test_stake_farm_updates_total_position(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that getUserTotalFarmPosition increases after staking"""
        logger.info("TEST: Stake farm updates total position")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get total position before
        position_before = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )

        # Fund and stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get total position after
        position_after = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )

        assert position_after == position_before + stake_amount, (
            f"Total position not updated correctly:\n"
            f"  Before: {position_before}\n"
            f"  After: {position_after}\n"
            f"  Expected: {position_before + stake_amount}\n"
            f"  Staked: {stake_amount}"
        )

        logger.info(f"✓ Total position increased from {position_before} to {position_after}")

    def test_stake_farm_multiple_positions(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test staking twice without merging, should get separate nonces"""
        logger.info("TEST: Stake farm multiple positions")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # First stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        farm_tokens_after_first = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        first_nonce = max(farm_tokens_after_first, key=lambda t: t.token.nonce).token.nonce

        # Second stake (without sending existing farm token = no merge)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2 = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        farm_tokens_after_second = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )

        # Should have 2 separate farm tokens
        assert len(farm_tokens_after_second) >= len(farm_tokens_after_first) + 1, (
            f"Expected separate farm token positions. "
            f"After first: {len(farm_tokens_after_first)}, After second: {len(farm_tokens_after_second)}"
        )

        second_nonce = max(farm_tokens_after_second, key=lambda t: t.token.nonce).token.nonce
        assert second_nonce != first_nonce, (
            f"Expected different nonces for separate positions. "
            f"First: {first_nonce}, Second: {second_nonce}"
        )

        logger.info(f"✓ Created separate positions: nonce {first_nonce} and nonce {second_nonce}")

    def test_stake_farm_with_existing_farm_token(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test staking with farming tokens + existing farm token (merge position)"""
        logger.info("TEST: Stake farm with existing farm token (merge)")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # First stake to get a farm token
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        farm_tokens_before_merge = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        existing_token = max(farm_tokens_before_merge, key=lambda t: t.token.nonce)
        existing_nonce = existing_token.token.nonce
        existing_amount = existing_token.balance

        # Second stake WITH existing farm token (merge)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
            farm_nonce=existing_nonce,
            farm_amount=existing_amount,
        )
        TransactionAssertions.assert_transaction_success(tx2_hash, network_providers.proxy)

        farm_tokens_after_merge = _get_farm_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )

        # New merged token should have combined amount
        new_token = max(farm_tokens_after_merge, key=lambda t: t.token.nonce)
        expected_amount = existing_amount + stake_amount

        assert new_token.balance == expected_amount, (
            f"Merged farm token amount incorrect:\n"
            f"  Existing: {existing_amount}\n"
            f"  Added: {stake_amount}\n"
            f"  Expected: {expected_amount}\n"
            f"  Actual: {new_token.balance}"
        )

        # Old token should be burned (nonce not in list or balance 0)
        old_token_exists = any(
            t.token.nonce == existing_nonce and t.balance > 0
            for t in farm_tokens_after_merge
        )
        assert not old_token_exists, f"Old farm token nonce {existing_nonce} should be burned"

        logger.info(f"✓ Merged positions: {existing_amount} + {stake_amount} = {new_token.balance}")

    def test_stake_farm_token_attributes(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that farm token attributes are correct after staking"""
        logger.info("TEST: Stake farm token attributes")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get current global RPS before staking
        state_before = _get_staking_state(staking_contract, network_providers.proxy)
        global_rps_before = state_before["reward_per_share"]

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get farm token attributes
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        latest_token = max(farm_tokens, key=lambda t: t.token.nonce)

        attrs_hex = latest_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES)

        # Verify attributes
        assert attrs["reward_per_share"] >= global_rps_before, (
            f"Token RPS should be >= global RPS at entry:\n"
            f"  Token RPS: {attrs['reward_per_share']}\n"
            f"  Global RPS: {global_rps_before}"
        )

        assert attrs["current_farm_amount"] == stake_amount, (
            f"Token current_farm_amount incorrect:\n"
            f"  Expected: {stake_amount}\n"
            f"  Actual: {attrs['current_farm_amount']}"
        )

        assert attrs["compounded_reward"] == 0, (
            f"Initial stake should have compounded_reward = 0:\n"
            f"  Actual: {attrs['compounded_reward']}"
        )

        assert attrs["original_owner"] == alice.address.to_bech32(), (
            f"Token original_owner incorrect:\n"
            f"  Expected: {alice.address.to_bech32()}\n"
            f"  Actual: {attrs['original_owner']}"
        )

        logger.info(
            f"✓ Token attributes: RPS={attrs['reward_per_share']}, "
            f"amount={attrs['current_farm_amount']}, compounded={attrs['compounded_reward']}"
        )

    def test_stake_farm_preserves_reward_per_share(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that RPS at entry matches current global RPS (snapshot accuracy)"""
        logger.info("TEST: Stake farm preserves reward per share")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get global RPS immediately before staking
        global_rps_before = staking_contract.get_reward_per_share(network_providers.proxy)

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get farm token RPS
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        latest_token = max(farm_tokens, key=lambda t: t.token.nonce)
        attrs_hex = latest_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES)
        token_rps = attrs["reward_per_share"]

        # Get global RPS after staking
        global_rps_after = staking_contract.get_reward_per_share(network_providers.proxy)

        # Token RPS should be between before and after (since some time passed during tx)
        assert global_rps_before <= token_rps <= global_rps_after, (
            f"Token RPS snapshot out of range:\n"
            f"  Global RPS before: {global_rps_before}\n"
            f"  Token RPS: {token_rps}\n"
            f"  Global RPS after: {global_rps_after}"
        )

        logger.info(f"✓ Token RPS {token_rps} within range [{global_rps_before}, {global_rps_after}]")

    def test_stake_farm_increases_supply(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that getFarmTokenSupply increases by staked amount"""
        logger.info("TEST: Stake farm increases supply")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get supply before
        supply_before = staking_contract.get_farm_token_supply(network_providers.proxy)

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get supply after
        supply_after = staking_contract.get_farm_token_supply(network_providers.proxy)

        assert supply_after == supply_before + stake_amount, (
            f"Farm token supply not updated correctly:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}\n"
            f"  Expected: {supply_before + stake_amount}\n"
            f"  Staked: {stake_amount}"
        )

        logger.info(f"✓ Supply increased from {supply_before} to {supply_after}")

    def test_stake_farm_zero_amount_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that staking 0 tokens fails with payment validation error"""
        logger.info("TEST: Stake farm zero amount fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token

        # Fund Alice (even though we'll send 0)
        ensure_esdt_amounts(alice, {farming_token: nominated_amount(1)})

        # Try to stake 0
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            farming_token,
            0,  # Zero amount
            network_providers,
            blockchain_controller,
        )

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Staking 0 tokens correctly failed")

    def test_stake_farm_wrong_token_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that sending non-farming token to stakeFarm fails"""
        logger.info("TEST: Stake farm wrong token fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        # Use a different token (WEGLD if available)
        wrong_token = "WEGLD-bd4d79"
        stake_amount = nominated_amount(1)

        # Fund Alice with wrong token
        ensure_esdt_amounts(alice, {wrong_token: stake_amount})

        # Try to stake wrong token
        tx_hash = _stake_farm(
            staking_contract,
            alice,
            wrong_token,  # Wrong token
            stake_amount,
            network_providers,
            blockchain_controller,
        )

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Staking wrong token correctly failed")

    def test_stake_farm_when_paused_fails(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that staking when contract is paused fails"""
        logger.info("TEST: Stake farm when paused fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Fund Alice BEFORE pausing
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        # Ensure deployer has EGLD for admin operations
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Pause the contract
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Contract paused")

        try:
            # Verify contract is paused
            state = staking_contract.get_state(network_providers.proxy)
            assert state == 0, f"Expected state=0 (paused), got {state}"

            # Try to stake while paused
            tx_stake = _stake_farm(
                staking_contract,
                alice,
                farming_token,
                stake_amount,
                network_providers,
                blockchain_controller,
            )

            # Should fail
            TransactionAssertions.assert_transaction_failed(tx_stake, network_providers.proxy)

            logger.info("✓ Staking while paused correctly failed")

        finally:
            # ALWAYS resume (even if test failed)
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = staking_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Contract resumed (cleanup)")
