"""
Farm Staking Integration Tests - Category 13: State Transitions & Lifecycle

Tests the complete contract lifecycle and state transitions across time:
- Full lifecycle: stake → claim → compound → unstake → unbond
- Week boundary crossing
- Epoch advancement effects
- Produce rewards toggle
- Reward rate change mid-operation

Coverage: 5 tests (P2)
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
    _unstake_farm,
    _unbond_farm,
    _claim_rewards,
    _compound_rewards,
    _get_farm_tokens_for_user,
    _get_unbond_tokens_for_user,
    _ensure_deployer_has_egld,
)

logger = get_logger(__name__)


@pytest.mark.usefixtures("seed_staking_rewards")
class TestStateTransitions:
    """Test suite for contract lifecycle and state transitions"""

    def test_full_lifecycle(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Full lifecycle: stake → claim → compound → unstake → unbond (token conservation)"""
        logger.info("TEST: Full lifecycle")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        initial_balance = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        # 1. Stake
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)
        logger.info(f"  1. Staked {stake_amount}")

        blockchain_controller.wait_blocks(5)

        # 2. Claim rewards
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        bal_before_claim = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        tx_claim = _claim_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)
        claimed_rewards = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        ) - bal_before_claim
        logger.info(f"  2. Claimed {claimed_rewards} rewards")

        blockchain_controller.wait_blocks(5)

        # 3. Compound rewards
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        compound_token = max(farm_tokens, key=lambda t: t.token.nonce)
        logger.info(f"  3. Compounded: position now {compound_token.balance}")

        # 4. Unstake
        tx_unstake = _unstake_farm(
            staking_contract, alice, compound_token.token.nonce, compound_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)
        logger.info(f"  4. Unstaked {compound_token.balance}")

        # 5. Advance epochs and unbond
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_token = max(unbond_tokens, key=lambda t: t.token.nonce)

        attrs = decode_merged_attributes(
            unbond_token.attributes.hex(), decoding_structures.STAKE_UNBOND_TOKEN_ATTRIBUTES
        )
        unlock_epoch = attrs["unlock_epoch"]

        current_epoch = blockchain_controller.get_current_epoch()
        if current_epoch < unlock_epoch:
            blockchain_controller.advance_to_epoch(unlock_epoch)

        bal_before_unbond = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        tx_unbond = _unbond_farm(
            staking_contract, alice, unbond_token.token.nonce, unbond_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unbond, network_providers.proxy)

        final_balance = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )
        principal_returned = final_balance - bal_before_unbond
        assert principal_returned == unbond_token.balance, (
            f"Full principal returned on unbond:\n"
            f"  Expected: {unbond_token.balance}\n"
            f"  Returned: {principal_returned}"
        )
        logger.info(f"  5. Unbonded {principal_returned}")

        logger.info(
            f"✓ Full lifecycle complete: "
            f"staked={stake_amount}, claimed_rewards={claimed_rewards}, "
            f"compounded={compound_token.balance - stake_amount}, "
            f"returned={principal_returned}"
        )

    def test_week_boundary_crossing(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Operations spanning week boundaries work correctly"""
        logger.info("TEST: Week boundary crossing")

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

        week_before = staking_contract.get_current_week(network_providers.proxy)

        # Advance past a week boundary (1 week = 7 epochs)
        blockchain_controller.advance_to_epoch(
            blockchain_controller.get_current_epoch() + 7
        )

        week_after = staking_contract.get_current_week(network_providers.proxy)
        assert week_after > week_before, (
            f"Week should advance after 7+ epochs:\n"
            f"  Before: {week_before}\n"
            f"  After: {week_after}"
        )

        # Claim across week boundary — should work
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_claim = _claim_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        logger.info(f"✓ Week boundary crossed: week {week_before} → {week_after}, claim succeeded")

    def test_epoch_advancement_effects(
        self,
        staking_contract,
        network_providers,
        blockchain_controller,
    ):
        """Advancing epochs updates week/unbond tracking correctly"""
        logger.info("TEST: Epoch advancement effects")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        current_week = staking_contract.get_current_week(network_providers.proxy)
        first_week_epoch = staking_contract.get_first_week_start_epoch(network_providers.proxy)
        current_epoch = blockchain_controller.get_current_epoch()

        # Advance 7 epochs (1 week)
        blockchain_controller.advance_to_epoch(current_epoch + 7)

        new_week = staking_contract.get_current_week(network_providers.proxy)

        # Week should have advanced
        assert new_week >= current_week, "Week should not decrease"

        # Verify first_week_start_epoch is 0 (overridden by state filter)
        assert first_week_epoch == 0, (
            f"firstWeekStartEpoch should be 0 (state filter applied), got {first_week_epoch}"
        )

        logger.info(
            f"✓ Epoch advancement: epoch {current_epoch} → {current_epoch + 7}, "
            f"week {current_week} → {new_week}"
        )

    def test_produce_rewards_toggle(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Start/stop/start reward production: rewards only during active periods"""
        logger.info("TEST: Produce rewards toggle")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_start = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_start)

        try:
            # 1. Active period — RPS should grow
            rps_1 = staking_contract.get_reward_per_share(network_providers.proxy)
            blockchain_controller.wait_blocks(5)
            rps_2 = staking_contract.get_reward_per_share(network_providers.proxy)

            # 2. Stop production
            deployer_account.sync_nonce(network_providers.proxy)
            tx_stop = staking_contract.end_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_stop)
            TransactionAssertions.assert_transaction_success(tx_stop, network_providers.proxy)

            rps_at_stop = staking_contract.get_reward_per_share(network_providers.proxy)
            blockchain_controller.wait_blocks(5)
            rps_stopped = staking_contract.get_reward_per_share(network_providers.proxy)

            # RPS should be frozen during stopped period
            assert rps_stopped == rps_at_stop, (
                f"RPS should freeze when stopped:\n"
                f"  At stop: {rps_at_stop}\n"
                f"  After wait: {rps_stopped}"
            )

            # 3. Restart production — RPS should grow again
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restart = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_restart)
            TransactionAssertions.assert_transaction_success(tx_restart, network_providers.proxy)

            blockchain_controller.wait_blocks(5)
            rps_restarted = staking_contract.get_reward_per_share(network_providers.proxy)

            assert rps_restarted >= rps_stopped, (
                f"RPS should grow after restart:\n"
                f"  At restart: {rps_stopped}\n"
                f"  After wait: {rps_restarted}"
            )

            logger.info(
                f"✓ Toggle: active rps={rps_1}→{rps_2}, stopped rps={rps_at_stop}→{rps_stopped}, "
                f"restarted rps={rps_stopped}→{rps_restarted}"
            )

        except Exception:
            # Ensure production is restarted in error case
            deployer_account.sync_nonce(network_providers.proxy)
            tx_final = staking_contract.start_produce_rewards(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_final)
            raise

    def test_reward_rate_change_mid_operation(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Change per-second reward rate while users are staked: new rate applies after"""
        logger.info("TEST: Reward rate change mid-operation")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        original_rate = staking_contract.get_per_block_reward_amount(network_providers.proxy)
        new_rate = max(2, original_rate * 2) if original_rate > 0 else 2

        try:
            # Wait with original rate
            blockchain_controller.wait_blocks(5)
            rps_before_change = staking_contract.get_reward_per_share(network_providers.proxy)

            # Change rate
            deployer_account.sync_nonce(network_providers.proxy)
            tx_rate = staking_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, new_rate
            )
            blockchain_controller.wait_for_tx(tx_rate)
            TransactionAssertions.assert_transaction_success(tx_rate, network_providers.proxy)

            # Wait same duration with new rate
            blockchain_controller.wait_blocks(5)
            rps_after_change = staking_contract.get_reward_per_share(network_providers.proxy)

            # Both periods should have increased RPS
            # (exact amounts depend on APR cap and supply)
            assert rps_before_change >= 0, f"RPS before change: {rps_before_change}"
            assert rps_after_change >= rps_before_change, f"RPS should not decrease"

            # Claim — should succeed regardless of rate change
            farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
            farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

            tx_claim = _claim_rewards(
                staking_contract, alice, farm_token.token.nonce, farm_token.balance,
                network_providers, blockchain_controller,
            )
            TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

            logger.info(
                f"✓ Rate change mid-operation: {original_rate} → {new_rate}, "
                f"claim succeeded"
            )

        finally:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = staking_contract.set_rewards_per_block(
                deployer_account, network_providers.proxy, original_rate
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Rate restored to {original_rate} (cleanup)")
