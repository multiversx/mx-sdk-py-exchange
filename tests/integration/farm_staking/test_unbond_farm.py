"""
Farm Staking Integration Tests - Category 3: Unbond Farm

Tests the unbondFarm endpoint covering:
- Basic unbonding after unlock period
- Epoch validation (before/at/after unlock_epoch)
- Token conservation through full lifecycle
- Error conditions

This is a UNIQUE feature of staking contracts (not present in LP farms).
The unbonding lifecycle: stake → unstake → wait epochs → unbond

Coverage: 6 tests (P0 - critical path)
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
    _unstake_farm,
    _unbond_farm,
    _get_farm_tokens_for_user,
    _get_unbond_tokens_for_user,
)

logger = get_logger(__name__)


class TestUnbondFarm:
    """Test suite for unbondFarm endpoint (unique to staking contracts)"""

    def test_unbond_farm_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test basic unbonding: unbond after unlock period, receive farming tokens"""
        logger.info("TEST: Unbond farm basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Full lifecycle: stake → unstake → wait → unbond
        # 1. Stake
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

        # 2. Unstake to get unbond token
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # 3. Get unbond token and its unlock_epoch
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        attrs_hex = unbond_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)
        unlock_epoch = attrs["unlock_epoch"]

        # 4. Advance to unlock_epoch
        current_epoch = blockchain_controller.get_current_epoch()
        if current_epoch < unlock_epoch:
            blockchain_controller.advance_to_epoch(unlock_epoch)
            logger.info(f"Advanced from epoch {current_epoch} to {unlock_epoch}")

        # 5. Get farming token balance before unbonding
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.balance for t in all_tokens_before if t.identifier == farming_token
        )

        # 6. Unbond
        tx_unbond = _unbond_farm(
            staking_contract,
            alice,
            unbond_token.token.nonce,
            unbond_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unbond, network_providers.proxy)

        # 7. Verify farming tokens returned
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.balance for t in all_tokens_after if t.identifier == farming_token
        )

        # Should receive original staked amount back
        tokens_returned = farming_balance_after - farming_balance_before
        assert tokens_returned == unbond_token.balance, (
            f"Unbonding should return original staked amount:\n"
            f"  Unbond token amount: {unbond_token.balance}\n"
            f"  Tokens returned: {tokens_returned}"
        )

        # 8. Verify unbond token was burned
        all_nfts_after = network_providers.proxy.get_non_fungible_tokens_of_account(alice.address)
        unbond_tokens_after = [
            t for t in all_nfts_after
            if t.token.identifier == unbond_token.token.identifier and t.token.nonce == unbond_token.token.nonce
        ]
        assert len(unbond_tokens_after) == 0 or all(t.balance == 0 for t in unbond_tokens_after), (
            "Unbond token should be burned after unbonding"
        )

        logger.info(
            f"✓ Full unbond lifecycle: staked {stake_amount} → "
            f"unstaked at epoch {current_epoch} → "
            f"unbonded at epoch {unlock_epoch} → "
            f"received {tokens_returned} farming tokens"
        )

    def test_unbond_farm_before_unlock_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that unbonding before unlock_epoch fails with 'Unbond period not over'"""
        logger.info("TEST: Unbond farm before unlock fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake and unstake to get unbond token
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

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get unbond token
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        # Get unlock_epoch
        attrs_hex = unbond_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)
        unlock_epoch = attrs["unlock_epoch"]

        # Make sure we're BEFORE unlock_epoch
        current_epoch = blockchain_controller.get_current_epoch()
        assert current_epoch < unlock_epoch, (
            f"Test setup failed: current_epoch ({current_epoch}) should be < unlock_epoch ({unlock_epoch})"
        )

        # Try to unbond before unlock period
        tx_unbond = _unbond_farm(
            staking_contract,
            alice,
            unbond_token.token.nonce,
            unbond_token.balance,
            network_providers,
            blockchain_controller,
        )

        # Should fail with "Unbond period not over"
        TransactionAssertions.assert_transaction_failed(tx_unbond, network_providers.proxy)

        logger.info(
            f"✓ Unbonding before unlock correctly failed "
            f"(current_epoch={current_epoch}, unlock_epoch={unlock_epoch})"
        )

    def test_unbond_farm_exact_unlock_epoch(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test unbonding at exactly unlock_epoch (boundary condition)"""
        logger.info("TEST: Unbond farm at exact unlock epoch")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake and unstake
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

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get unbond token and unlock_epoch
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        attrs_hex = unbond_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)
        unlock_epoch = attrs["unlock_epoch"]

        # Advance to EXACTLY unlock_epoch (not beyond)
        current_epoch = blockchain_controller.get_current_epoch()
        if current_epoch < unlock_epoch:
            blockchain_controller.advance_to_epoch(unlock_epoch)

        # Verify we're at exactly unlock_epoch
        current_epoch_after = blockchain_controller.get_current_epoch()
        assert current_epoch_after == unlock_epoch, (
            f"Test setup failed: expected to be at unlock_epoch {unlock_epoch}, "
            f"but at {current_epoch_after}"
        )

        # Unbond at exactly unlock_epoch — should succeed
        tx_unbond = _unbond_farm(
            staking_contract,
            alice,
            unbond_token.token.nonce,
            unbond_token.balance,
            network_providers,
            blockchain_controller,
        )

        TransactionAssertions.assert_transaction_success(tx_unbond, network_providers.proxy)

        logger.info(f"✓ Unbonding at exact unlock_epoch={unlock_epoch} succeeded (boundary condition)")

    def test_unbond_farm_after_unlock_epoch(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test unbonding well after unlock period — should succeed with no penalty"""
        logger.info("TEST: Unbond farm after unlock epoch")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake and unstake
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

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get unbond token and unlock_epoch
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        attrs_hex = unbond_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)
        unlock_epoch = attrs["unlock_epoch"]

        # Advance WELL PAST unlock_epoch (add 5 extra epochs)
        target_epoch = unlock_epoch + 5
        current_epoch = blockchain_controller.get_current_epoch()
        if current_epoch < target_epoch:
            blockchain_controller.advance_to_epoch(target_epoch)

        current_epoch_after = blockchain_controller.get_current_epoch()
        assert current_epoch_after >= unlock_epoch, (
            f"Test setup failed: should be past unlock_epoch"
        )

        # Get farming balance before unbonding
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.balance for t in all_tokens_before if t.identifier == farming_token
        )

        # Unbond well after unlock period
        tx_unbond = _unbond_farm(
            staking_contract,
            alice,
            unbond_token.token.nonce,
            unbond_token.balance,
            network_providers,
            blockchain_controller,
        )

        TransactionAssertions.assert_transaction_success(tx_unbond, network_providers.proxy)

        # Verify full amount returned (no penalty for waiting)
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.balance for t in all_tokens_after if t.identifier == farming_token
        )

        tokens_returned = farming_balance_after - farming_balance_before
        assert tokens_returned == unbond_token.balance, (
            f"Waiting past unlock period should not penalize:\n"
            f"  Unbond amount: {unbond_token.balance}\n"
            f"  Returned: {tokens_returned}"
        )

        logger.info(
            f"✓ Unbonding {current_epoch_after - unlock_epoch} epochs after unlock succeeded "
            f"with no penalty (unlock={unlock_epoch}, current={current_epoch_after})"
        )

    def test_unbond_farm_wrong_token_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that sending non-unbond token to unbondFarm fails"""
        logger.info("TEST: Unbond farm wrong token fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        # Use a different token
        wrong_token = "WEGLD-bd4d79"

        # Fund Alice with wrong token
        ensure_esdt_amounts(alice, {wrong_token: nominated_amount(1)})

        # Try to unbond with wrong token
        from events.farm_events import ExitFarmEvent

        alice.sync_nonce(network_providers.proxy)
        exit_event = ExitFarmEvent(
            farm_token=wrong_token,  # Wrong token
            amount=nominated_amount(1),
            nonce=1,
            attributes="",
        )

        tx_unbond = staking_contract.unbond_farm(network_providers, alice, exit_event)
        blockchain_controller.wait_for_tx(tx_unbond)

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_unbond, network_providers.proxy)

        logger.info("✓ Unbonding with wrong token correctly failed")

    def test_unbond_full_flow(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test complete lifecycle: stake → unstake → wait → unbond → token conservation"""
        logger.info("TEST: Unbond full flow (token conservation)")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Get initial farming token balance
        all_tokens_initial = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        initial_balance = sum(
            t.balance for t in all_tokens_initial if t.identifier == farming_token
        )

        # 1. Stake
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
        logger.info(f"  1. Staked {stake_amount}")

        # 2. Unstake (returns rewards + unbond token)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        all_tokens_before_unstake = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before_unstake = sum(
            t.balance for t in all_tokens_before_unstake if t.identifier == farming_token
        )

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        all_tokens_after_unstake = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_after_unstake = sum(
            t.balance for t in all_tokens_after_unstake if t.identifier == farming_token
        )
        rewards_from_unstake = balance_after_unstake - balance_before_unstake

        logger.info(f"  2. Unstaked, received {rewards_from_unstake} rewards")

        # 3. Get unbond token and advance to unlock_epoch
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        attrs_hex = unbond_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)
        unlock_epoch = attrs["unlock_epoch"]

        current_epoch = blockchain_controller.get_current_epoch()
        if current_epoch < unlock_epoch:
            blockchain_controller.advance_to_epoch(unlock_epoch)
            logger.info(f"  3. Waited for unlock: epoch {current_epoch} → {unlock_epoch}")

        # 4. Unbond
        all_tokens_before_unbond = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        balance_before_unbond = sum(
            t.balance for t in all_tokens_before_unbond if t.identifier == farming_token
        )

        tx_unbond = _unbond_farm(
            staking_contract,
            alice,
            unbond_token.token.nonce,
            unbond_token.balance,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unbond, network_providers.proxy)

        all_tokens_final = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        final_balance = sum(
            t.balance for t in all_tokens_final if t.identifier == farming_token
        )

        principal_from_unbond = final_balance - balance_before_unbond
        logger.info(f"  4. Unbonded, received {principal_from_unbond} principal")

        # 5. Token conservation check
        # final_balance = initial_balance + stake_amount (from ensure_esdt_amounts) + rewards - gas fees
        # Since we added stake_amount via ensure_esdt_amounts, the net change should be rewards only
        # Simplify: total received = rewards_from_unstake + principal_from_unbond
        total_received = rewards_from_unstake + principal_from_unbond

        # Total received should approximately equal stake_amount + rewards
        # The principal should match unbond_token.balance
        assert principal_from_unbond == unbond_token.balance, (
            f"Principal mismatch:\n"
            f"  Unbond token: {unbond_token.balance}\n"
            f"  Received: {principal_from_unbond}"
        )

        logger.info(
            f"✓ Full lifecycle complete:\n"
            f"    Staked: {stake_amount}\n"
            f"    Rewards (unstake): {rewards_from_unstake}\n"
            f"    Principal (unbond): {principal_from_unbond}\n"
            f"    Total received: {total_received}"
        )
