"""
Farm Staking Integration Tests - Category 2: Unstake Farm

Tests the unstakeFarm endpoint covering:
- Basic unstaking functionality (full and partial)
- Rewards returned immediately (as farming token)
- Unbond token creation and attributes
- APR-capped rewards validation
- Position cleanup and supply tracking
- Error conditions

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
    _unstake_farm,
    _get_farm_tokens_for_user,
    _get_unbond_tokens_for_user,
)

logger = get_logger(__name__)


class TestUnstakeFarm:
    """Test suite for unstakeFarm endpoint"""

    def test_unstake_farm_basic(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test full unstaking: unstake full position, receive rewards + unbond token"""
        logger.info("TEST: Unstake farm basic")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake first
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
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        farm_nonce = farm_token.token.nonce
        farm_amount = farm_token.amount

        # Wait some time for rewards to accumulate
        blockchain_controller.wait_blocks(5)

        # Get farming token balance before unstaking
        all_tokens = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.amount for t in all_tokens if t.token.identifier == farming_token
        )

        blockchain_controller.wait_blocks(5)

        # Unstake full position
        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_nonce,
            farm_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Verify rewards received (farming token balance should increase)
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.amount for t in all_tokens_after if t.token.identifier == farming_token
        )

        assert farming_balance_after > farming_balance_before, (
            f"Farming token balance should increase after rewards accrue:\n"
            f"  Before: {farming_balance_before}\n"
            f"  After: {farming_balance_after}"
        )

        # Verify unbond token created
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)

        # Should have at least one unbond token (may have other farm tokens from other tests)
        assert len(unbond_tokens) > 0, "Expected unbond token to be created"

        logger.info(f"✓ Unstaked {farm_amount}, received rewards + unbond token")

    def test_unstake_farm_partial(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test partial unstaking: unstake partial amount, remaining farm token has correct amount"""
        logger.info("TEST: Unstake farm partial")

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
        unbond_tokens_before = _get_unbond_tokens_for_user(
            staking_contract, alice, network_providers.proxy
        )
        position_before_unstake = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(),
            network_providers.proxy,
        )
        farm_token = max(farm_tokens_before, key=lambda t: t.token.nonce)
        farm_nonce = farm_token.token.nonce
        farm_amount = farm_token.amount

        # Unstake half
        unstake_amount = farm_amount // 2
        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_nonce,
            unstake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        position_after_unstake = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(),
            network_providers.proxy,
        )
        actual_position_delta = position_before_unstake - position_after_unstake
        tolerance = stake_amount // 100  # 1% tolerance for tx processing rewards

        assert abs(actual_position_delta - unstake_amount) <= tolerance, (
            f"Farm position should decrease by unstaked amount:\n"
            f"  Position before: {position_before_unstake}\n"
            f"  Position after: {position_after_unstake}\n"
            f"  Unstaked: {unstake_amount}\n"
            f"  Actual decrease: {actual_position_delta}\n"
            f"  Tolerance: {tolerance}"
        )

        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        previous_unbond_nonces = {t.token.nonce for t in unbond_tokens_before}
        new_unbond_tokens = [t for t in unbond_tokens if t.token.nonce not in previous_unbond_nonces]
        assert new_unbond_tokens, "Expected a new unbond token after partial unstake"
        unbond_token = max(new_unbond_tokens, key=lambda t: t.token.nonce)
        assert abs(unbond_token.amount - unstake_amount) <= tolerance, (
            f"Unbond token amount incorrect after partial unstake:\n"
            f"  Expected: {unstake_amount}\n"
            f"  Actual: {unbond_token.amount}\n"
            f"  Tolerance: {tolerance}"
        )

        logger.info(
            f"✓ Partial unstake: {farm_amount} → unstaked {unstake_amount}, "
            f"position delta ~{actual_position_delta}"
        )

    def test_unstake_farm_rewards_returned_immediately(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that rewards are sent as farming token immediately on unstake"""
        logger.info("TEST: Unstake farm rewards returned immediately")

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

        # Get farm token and wait for rewards
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        blockchain_controller.wait_blocks(10)  # Wait longer for more rewards

        # Get farming token balance before unstaking
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.amount for t in all_tokens_before if t.token.identifier == farming_token
        )

        # Unstake
        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get farming token balance after unstaking
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.amount for t in all_tokens_after if t.token.identifier == farming_token
        )

        # Verify reward token == farming token (same-token staking)
        assert farming_balance_after > farming_balance_before, (
            f"Expected rewards to be returned as farming token:\n"
            f"  Farming token: {farming_token}\n"
            f"  Balance before: {farming_balance_before}\n"
            f"  Balance after: {farming_balance_after}\n"
            f"  Increase: {farming_balance_after - farming_balance_before}"
        )

        rewards = farming_balance_after - farming_balance_before
        logger.info(f"✓ Rewards ({rewards} {farming_token}) returned immediately on unstake")

    def test_unstake_farm_creates_unbond_token(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that unbond token is created with correct unlock_epoch attribute"""
        logger.info("TEST: Unstake farm creates unbond token")

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

        # Get current epoch and min_unbond_epochs
        current_epoch = blockchain_controller.get_current_epoch()
        min_unbond_epochs = staking_contract.get_min_unbond_epochs(network_providers.proxy)

        # Get farm token and unstake
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get unbond token and verify attributes
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)

        # Find the newest unbond token
        latest_unbond = max(unbond_tokens, key=lambda t: t.token.nonce)

        # Decode attributes
        attrs_hex = latest_unbond.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES)

        # Verify unlock_epoch = current_epoch + min_unbond_epochs
        expected_unlock_epoch = current_epoch + min_unbond_epochs
        assert attrs["unlock_epoch"] == expected_unlock_epoch, (
            f"Unbond token unlock_epoch incorrect:\n"
            f"  Current epoch: {current_epoch}\n"
            f"  Min unbond epochs: {min_unbond_epochs}\n"
            f"  Expected unlock_epoch: {expected_unlock_epoch}\n"
            f"  Actual unlock_epoch: {attrs['unlock_epoch']}"
        )

        logger.info(
            f"✓ Unbond token created: unlock_epoch={attrs['unlock_epoch']} "
            f"(current={current_epoch} + min={min_unbond_epochs})"
        )

    def test_unstake_farm_apr_capped_rewards(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that rewards don't exceed APR cap (actual_rewards <= apr_bounded_amount)"""
        logger.info("TEST: Unstake farm APR capped rewards")

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

        # Get farm token
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Wait for rewards
        blocks_to_wait = 20
        blockchain_controller.wait_blocks(blocks_to_wait)

        # Get farming balance before unstaking
        all_tokens_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_before = sum(
            t.amount for t in all_tokens_before if t.token.identifier == farming_token
        )

        # Unstake
        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Calculate actual rewards received
        all_tokens_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        farming_balance_after = sum(
            t.amount for t in all_tokens_after if t.token.identifier == farming_token
        )
        actual_rewards = farming_balance_after - farming_balance_before

        # Calculate APR-bounded maximum
        # Formula: max_rewards = stake_amount * max_apr / 10_000 / 31_536_000 * elapsed_seconds
        # Approximate elapsed_seconds = blocks * 6
        elapsed_seconds = blocks_to_wait * 6
        SECONDS_IN_YEAR = 31_536_000
        MAX_PERCENT = 10_000

        apr_bounded_max = (stake_amount * max_apr * elapsed_seconds) // (MAX_PERCENT * SECONDS_IN_YEAR)

        # Actual rewards should not significantly exceed APR cap
        # Allow some tolerance for block processing time
        tolerance = apr_bounded_max // 10  # 10% tolerance
        assert actual_rewards <= apr_bounded_max + tolerance, (
            f"Rewards exceed APR cap:\n"
            f"  Stake amount: {stake_amount}\n"
            f"  Max APR: {max_apr} (basis points)\n"
            f"  Elapsed seconds: ~{elapsed_seconds}\n"
            f"  APR-bounded max: {apr_bounded_max}\n"
            f"  Actual rewards: {actual_rewards}\n"
            f"  Tolerance: {tolerance}"
        )

        logger.info(
            f"✓ Rewards within APR cap: {actual_rewards} <= {apr_bounded_max + tolerance} "
            f"(max_apr={max_apr})"
        )

    def test_unstake_farm_zero_amount_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that unstaking 0 farm tokens fails"""
        logger.info("TEST: Unstake farm zero amount fails")

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
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Try to unstake 0
        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            0,  # Zero amount
            network_providers,
            blockchain_controller,
        )

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_unstake, network_providers.proxy)

        logger.info("✓ Unstaking 0 tokens correctly failed")

    def test_unstake_farm_wrong_token_fails(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that sending non-farm token to unstakeFarm fails"""
        logger.info("TEST: Unstake farm wrong token fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        # Use a different token
        wrong_token = "WEGLD-bd4d79"

        # Fund Alice with wrong token
        ensure_esdt_amounts(alice, {wrong_token: nominated_amount(1)})

        # Try to unstake wrong token (use arbitrary nonce)
        from events.farm_events import ExitFarmEvent

        alice.sync_nonce(network_providers.proxy)
        exit_event = ExitFarmEvent(
            farm_token=wrong_token,  # Wrong token
            amount=nominated_amount(1),
            nonce=1,
            attributes="",
        )

        tx_unstake = staking_contract.unstake_farm(network_providers, alice, exit_event)
        blockchain_controller.wait_for_tx(tx_unstake)

        # Should fail
        TransactionAssertions.assert_transaction_failed(tx_unstake, network_providers.proxy)

        logger.info("✓ Unstaking wrong token correctly failed")

    def test_unstake_farm_when_paused_fails(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that unstaking when contract is paused fails"""
        logger.info("TEST: Unstake farm when paused fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        from tests.integration.farm_staking import _ensure_deployer_has_egld

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake first
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
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Ensure deployer has EGLD
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Pause the contract
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = staking_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Contract paused")

        try:
            # Verify paused
            state = staking_contract.get_state(network_providers.proxy)
            assert state == 0, f"Expected state=0 (paused), got {state}"

            # Try to unstake while paused
            tx_unstake = _unstake_farm(
                staking_contract,
                alice,
                farm_token.token.nonce,
                farm_token.amount,
                network_providers,
                blockchain_controller,
            )

            # Should fail
            TransactionAssertions.assert_transaction_failed(tx_unstake, network_providers.proxy)

            logger.info("✓ Unstaking while paused correctly failed")

        finally:
            # ALWAYS resume
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = staking_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Contract resumed (cleanup)")

    def test_unstake_farm_clears_position_on_full_exit(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that full unstake clears getUserTotalFarmPosition"""
        logger.info("TEST: Unstake farm clears position on full exit")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Record alice's total position before staking (accumulated from prior tests)
        position_pre_stake = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )

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

        # Verify position increased by at least stake_amount
        position_after_stake = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        tolerance = stake_amount // 1000  # 0.1% tolerance
        assert position_after_stake >= position_pre_stake + stake_amount - tolerance, (
            f"Position should increase after staking:\n"
            f"  Pre-stake: {position_pre_stake}\n"
            f"  After stake: {position_after_stake}\n"
            f"  Staked: {stake_amount}"
        )

        # Get the newly staked farm token and unstake it fully
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            farm_token.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Verify position returned to pre-stake level (delta cleared)
        position_after_unstake = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        assert position_after_unstake <= position_pre_stake + tolerance, (
            f"Expected position delta to be cleared after full unstake:\n"
            f"  Pre-stake: {position_pre_stake}\n"
            f"  After unstake: {position_after_unstake}\n"
            f"  Tolerance: {tolerance}"
        )

        logger.info(
            f"✓ Position cleared: {position_pre_stake} → {position_after_unstake} "
            f"(after temporary rise to {position_after_stake})"
        )

    def test_unstake_farm_supply_decreases(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Test that getFarmTokenSupply decreases by unstaked amount"""
        logger.info("TEST: Unstake farm supply decreases")

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

        # Get supply before unstaking
        supply_before = staking_contract.get_farm_token_supply(network_providers.proxy)

        # Get farm token and unstake
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        unstake_amount = farm_token.amount

        tx_unstake = _unstake_farm(
            staking_contract,
            alice,
            farm_token.token.nonce,
            unstake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Get supply after
        supply_after = staking_contract.get_farm_token_supply(network_providers.proxy)

        # Supply should decrease by unstaked amount
        expected_supply = supply_before - unstake_amount
        tolerance = stake_amount // 100  # 1% tolerance for tx processing

        assert abs(supply_after - expected_supply) <= tolerance, (
            f"Supply not updated correctly:\n"
            f"  Before: {supply_before}\n"
            f"  Unstaked: {unstake_amount}\n"
            f"  Expected: {expected_supply}\n"
            f"  Actual: {supply_after}\n"
            f"  Tolerance: {tolerance}"
        )

        logger.info(f"✓ Supply decreased: {supply_before} → {supply_after}")
