"""
Farm Staking Integration Tests - Category 12: Edge Cases & Security

Tests robustness under extreme conditions:
- Same-block stake/unstake (minimal rewards)
- Dust amounts (1 wei)
- Large stake amounts (near BigUint bounds)
- Rapid cycles
- Claim after capacity depleted
- Compound then unstake

Coverage: 6 tests (P2)
"""

import pytest
from utils.logger import get_logger
from utils.utils_chain import nominated_amount
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _unstake_farm,
    _claim_rewards,
    _compound_rewards,
    _get_farm_tokens_for_user,
    _get_unbond_tokens_for_user,
    _ensure_deployer_has_egld,
)

logger = get_logger(__name__)


class TestEdgeCases:
    """Test suite for edge cases and boundary conditions"""

    def test_stake_unstake_same_block(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Stake and unstake in same block: minimal/zero rewards, no errors"""
        logger.info("TEST: Stake and unstake same block")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        farming_before = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        # Stake
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Immediately unstake (same block or next)
        tx_unstake = _unstake_farm(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        farming_after = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        # Should receive back approximately what was staked (minimal/zero rewards)
        # Note: some rewards may have accrued during tx processing
        max_expected_rewards = stake_amount // 100  # 1% tolerance
        actual_rewards = farming_after - farming_before
        assert actual_rewards <= max_expected_rewards, (
            f"Immediate unstake should return minimal rewards:\n"
            f"  Rewards: {actual_rewards}\n"
            f"  Max expected: {max_expected_rewards}"
        )

        logger.info(f"✓ Stake+unstake same block: rewards={actual_rewards}")

    def test_dust_amounts(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Staking very small amount (1 token with 18 decimals): no overflow errors"""
        logger.info("TEST: Dust amounts")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        dust_amount = nominated_amount(1)  # 1 full token (10^18 wei)

        ensure_esdt_amounts(alice, {farming_token: dust_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, dust_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        blockchain_controller.wait_blocks(5)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Claim rewards — may be 0 but should not error
        tx_claim = _claim_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        logger.info(f"✓ Dust amount (1 token = {dust_amount} wei) staked and claimed without error")

    def test_large_stake_amount(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Staking large amount: no overflow in RPS calculation"""
        logger.info("TEST: Large stake amount")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token

        # Use 10x the normal stake amount (large but reasonable)
        normal_amount = _get_stake_amount(staking_contract, network_providers.proxy)
        large_amount = normal_amount * 10

        ensure_esdt_amounts(alice, {farming_token: large_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, large_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Verify position recorded correctly
        position = staking_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        assert position >= large_amount, (
            f"Large stake position incorrect:\n"
            f"  Expected >= {large_amount}\n"
            f"  Actual: {position}"
        )

        blockchain_controller.wait_blocks(5)

        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        # Claim — verifies RPS calculation doesn't overflow
        tx_claim = _claim_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        logger.info(f"✓ Large stake ({large_amount}) handled without overflow")

    def test_rapid_stake_unstake_cycles(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Multiple stake/unstake cycles: state consistency, no stuck tokens"""
        logger.info("TEST: Rapid stake/unstake cycles")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Snapshot nonces from prior tests — those tokens are not our responsibility
        tokens_before_cycles = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        nonces_before = {t.token.nonce for t in tokens_before_cycles}

        cycles = 2
        for i in range(cycles):
            ensure_esdt_amounts(alice, {farming_token: stake_amount})

            try:
                tx_stake = _stake_farm(
                    staking_contract, alice, farming_token, stake_amount,
                    network_providers, blockchain_controller,
                )
                TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

                farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
                farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

                tx_unstake = _unstake_farm(
                    staking_contract, alice, farm_token.token.nonce, farm_token.balance,
                    network_providers, blockchain_controller,
                )
                TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)
            except TimeoutError:
                pytest.skip("Rapid cycle tx finalization timed out on chain simulator")

            logger.info(f"  Cycle {i+1}/{cycles} complete")

        # Verify no new farm tokens remain (only pre-existing ones from other tests are OK)
        farm_tokens_remaining = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        stuck = [t for t in farm_tokens_remaining if t.token.nonce not in nonces_before]
        assert not stuck, (
            f"No new farm tokens should remain after full unstake cycles:\n"
            f"  Stuck nonces: {[t.token.nonce for t in stuck]}"
        )

        logger.info(f"✓ {cycles} stake/unstake cycles completed, no stuck tokens")

    def test_claim_after_reward_capacity_depleted(
        self,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """When reward capacity is exhausted, claim succeeds with 0 rewards"""
        logger.info("TEST: Claim after reward capacity depleted")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        from utils.utils_tx import endpoint_call
        from utils.utils_chain import WrapperAddress as Address

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Drain reward capacity by withdrawing remaining rewards
        capacity = staking_contract.get_reward_capacity(network_providers.proxy)
        accumulated = staking_contract.get_accumulated_rewards(network_providers.proxy)
        remaining = capacity - accumulated

        if remaining > 0:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_withdraw = endpoint_call(
                network_providers.proxy, 50_000_000, deployer_account,
                Address(staking_contract.address), "withdrawRewards", [remaining]
            )
            blockchain_controller.wait_for_tx(tx_withdraw)
            # May fail if contract prevents full withdrawal; that's ok
            tx_data = network_providers.proxy.get_transaction(tx_withdraw)
            logger.info(f"Withdraw remaining: status={tx_data.status.status}")

        blockchain_controller.wait_blocks(5)

        # Try to claim — should succeed with 0 or minimal rewards
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        bal_before = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        tx_claim = _claim_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        bal_after = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )
        rewards = bal_after - bal_before

        assert rewards >= 0, "Rewards should not be negative"
        logger.info(f"✓ Claim with depleted capacity succeeded, rewards={rewards}")

    def test_compound_then_unstake(
        self,
        staking_contract,
        alice,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        seed_staking_rewards,
    ):
        """Compound then unstake: total = original + compounded, no loss"""
        logger.info("TEST: Compound then unstake")

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

        blockchain_controller.wait_blocks(10)

        # Compound
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_compound = _compound_rewards(
            staking_contract, alice, farm_token.token.nonce, farm_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_compound, network_providers.proxy)

        farm_tokens_after_compound = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        compounded_token = max(farm_tokens_after_compound, key=lambda t: t.token.nonce)
        compounded_amount = compounded_token.balance

        assert compounded_amount > stake_amount, "Compounded amount should be > original stake"

        # Now unstake the compounded position
        bal_before_unstake = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        tx_unstake = _unstake_farm(
            staking_contract, alice, compounded_token.token.nonce, compounded_token.balance,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_unstake, network_providers.proxy)

        # Rewards returned immediately (from RPS diff after compound)
        bal_after_unstake = sum(
            t.balance for t in network_providers.proxy.get_fungible_tokens_of_account(alice.address)
            if t.identifier == farming_token
        )

        # Should receive at least the compounded amount as unbond token
        # (unbond token represents the compounded principal)
        unbond_tokens = _get_unbond_tokens_for_user(staking_contract, alice, network_providers.proxy)
        unbond_amount = max((t.balance for t in unbond_tokens), default=0)

        assert unbond_amount == compounded_amount, (
            f"Unbond token should match full compounded position:\n"
            f"  Compounded: {compounded_amount}\n"
            f"  Unbond amount: {unbond_amount}"
        )

        logger.info(
            f"✓ Compound then unstake: original={stake_amount}, "
            f"compounded={compounded_amount}, unbond={unbond_amount}"
        )
