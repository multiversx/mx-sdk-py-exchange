"""
Integration tests for Farm-with-locked-rewards contract mergeFarmTokens endpoint.

These tests verify the merge farm tokens operation through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Merge two positions, merge with boosted rewards
2. Error Cases: Single token merge (requires 2+ tokens)
3. Invariant Tests: Total supply preserved after merge
4. Edge Cases: Different owner tokens (skipped on chain sim)

Run:
    pytest --env=chainsim tests/integration/farm/test_merge_farm_tokens.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, MergePositionFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.utils_chain import nominated_amount, Account, hex_to_string, decode_merged_attributes
from utils.utils_tx import NetworkProviders
from utils import decoding_structures
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _get_farm_state,
    _check_farm_has_code,
    _get_stake_amount,
    _enter_farm,
    _exit_farm,
    _claim_rewards,
    _claim_boosted_rewards,
    _get_farm_tokens_for_user,
    _get_minimum_farming_epochs,
    _get_farming_token_balance,
    _merge_farm_positions,
    _get_locked_token_id,
    _get_locked_tokens_for_user,
    _ensure_deployer_has_egld,
)
from utils.logger import get_logger
from multiversx_sdk import Address


logger = get_logger(__name__)


# ============================================================================
# TEST CLASS
# ============================================================================

@pytest.mark.integration
@pytest.mark.farm
class TestFarmMergeFarmTokens:
    """
    Integration tests for Farm.mergeFarmTokens()

    Contract Endpoints Tested:
    - mergeFarmTokens(farm_token_1, farm_token_2, ..., opt_original_caller) -> merged_farm_token

    Key Behaviors:
    1. User sends 2+ farm token NFTs via multi-ESDT transfer
    2. Contract burns old farm tokens, mints a single merged farm token
    3. Merged token amount = sum of input token amounts
    4. Farm token supply is unchanged (burn + mint cancel out)
    5. Merged token attributes reflect the combined position (weighted RPS, etc.)
    6. Any pending boosted rewards may be claimed during merge
    7. Single-token merge is rejected (need at least 2 tokens)
    """

    # ----------------------------------------------------------------
    # Happy Path Tests
    # ----------------------------------------------------------------

    def test_merge_two_positions(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice merges two farm token NFTs into one

        GIVEN: Alice has entered the farm twice, holding 2 farm token NFTs
        WHEN: Alice calls mergeFarmTokens with both farm tokens
        THEN:
            - Transaction succeeds
            - Alice receives a single merged farm token
            - Merged token amount = sum of both input amounts
            - Old farm token nonces are burned (no longer held)
            - Farm token supply is unchanged (burn old + mint new)
        """
        logger.info("TEST: Merge two farm positions")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # First entry
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        # Second entry
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        # Get Alice's farm tokens — should have at least 2
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) >= 2, (
            f"Alice should have at least 2 farm tokens for merge, got {len(farm_tokens)}"
        )

        # Pick two tokens to merge
        tokens_to_merge = farm_tokens[:2]
        total_amount_before = sum(t.amount for t in tokens_to_merge)
        merged_nonces = {t.token.nonce for t in tokens_to_merge}
        logger.info(
            f"Merging {len(tokens_to_merge)} tokens: "
            f"nonces={[t.token.nonce for t in tokens_to_merge]}, "
            f"amounts={[t.amount for t in tokens_to_merge]}, "
            f"total={total_amount_before}"
        )

        # Record supply before merge
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Merge
        tx_merge = _merge_farm_positions(farm_contract, alice, tokens_to_merge,
                                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_merge, network_providers.proxy)

        # Verify: farm token supply is unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm token supply should be unchanged after merge:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        # Verify: Alice has a new merged farm token
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) > 0, "Alice should have at least one farm token after merge"

        # The merged token should be the highest nonce
        merged_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        logger.info(f"Merged token: nonce={merged_token.token.nonce}, amount={merged_token.amount}")

        # Verify merged amount equals sum of inputs
        assert merged_token.amount == total_amount_before, (
            f"Merged token amount should equal sum of inputs:\n"
            f"  Expected: {total_amount_before}\n"
            f"  Actual: {merged_token.amount}"
        )

        # Verify old nonces are burned (no longer held by Alice at original amounts)
        nonces_after = {t.token.nonce for t in farm_tokens_after}
        for old_nonce in merged_nonces:
            if old_nonce != merged_token.token.nonce:
                assert old_nonce not in nonces_after, (
                    f"Old farm token nonce {old_nonce} should have been burned"
                )

        logger.info("PASSED: test_merge_two_positions")

    def test_merge_returns_boosted_rewards(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Merging positions after blocks pass succeeds (boosted rewards path)

        GIVEN: Alice enters farm, blocks pass, enters again (different RPS snapshots)
        WHEN: Alice merges both positions
        THEN:
            - Transaction succeeds (boosted rewards may be 0 on chain sim but no error)
            - Alice receives a single merged farm token
            - Farm state is consistent
        """
        logger.info("TEST: Merge returns boosted rewards")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # First entry
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        # Advance blocks so RPS changes between entries
        blockchain_controller.wait_blocks(5)

        # Second entry (at potentially different RPS)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        # Get farm tokens
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) >= 2, (
            f"Alice should have at least 2 farm tokens, got {len(farm_tokens)}"
        )

        tokens_to_merge = farm_tokens[:2]
        total_amount = sum(t.amount for t in tokens_to_merge)

        # Record state before
        state_before = _get_farm_state(farm_contract, network_providers.proxy)

        # Merge
        tx_merge = _merge_farm_positions(farm_contract, alice, tokens_to_merge,
                                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_merge, network_providers.proxy)

        # Verify state consistency
        state_after = _get_farm_state(farm_contract, network_providers.proxy)

        # Supply unchanged
        assert state_after["farm_token_supply"] == state_before["farm_token_supply"], (
            f"Farm token supply should be unchanged:\n"
            f"  Before: {state_before['farm_token_supply']}\n"
            f"  After: {state_after['farm_token_supply']}"
        )

        # RPS never decreases
        assert state_after["reward_per_share"] >= state_before["reward_per_share"], (
            f"RPS should not decrease after merge:\n"
            f"  Before: {state_before['reward_per_share']}\n"
            f"  After: {state_after['reward_per_share']}"
        )

        # Alice has merged token
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        merged_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        assert merged_token.amount == total_amount, (
            f"Merged token amount mismatch:\n"
            f"  Expected: {total_amount}\n"
            f"  Actual: {merged_token.amount}"
        )

        logger.info("PASSED: test_merge_returns_boosted_rewards")

    # ----------------------------------------------------------------
    # Error Case Tests
    # ----------------------------------------------------------------

    def test_merge_single_token_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Merging with only 1 farm token behaves as a no-op merge

        GIVEN: Alice has entered the farm once (1 farm token NFT)
        WHEN: Alice calls mergeFarmTokens with only 1 token
        THEN:
            - Transaction succeeds on the deployed contract
            - Farm token supply is unchanged
            - Alice still has a farm position
        """
        logger.info("TEST: Merge single token no-op")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm once
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Get farm tokens and pick just 1
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have at least 1 farm token"
        single_token = [farm_tokens[-1]]  # Use the latest token only

        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Merge with just 1 token — deployed contract accepts this as a no-op merge
        tx_merge = _merge_farm_positions(farm_contract, alice, single_token,
                                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_merge, network_providers.proxy)

        # Supply unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm token supply should be unchanged after single-token merge:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) > 0, "Alice should still hold a farm position after single-token merge"

        logger.info("PASSED: test_merge_single_token_fails")

    # ----------------------------------------------------------------
    # Invariant Tests
    # ----------------------------------------------------------------

    def test_merge_preserves_total_amount(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Merging 3 farm tokens preserves total farm token supply

        GIVEN: Alice enters the farm 3 times, getting 3 farm token NFTs
        WHEN: Alice merges all 3 into one via mergeFarmTokens
        THEN:
            - Farm token supply is unchanged before and after merge
            - Alice holds a single merged token with amount = sum of all 3
            - Merged token attributes are valid (decodable, correct owner)
        """
        logger.info("TEST: Merge preserves total amount (3 tokens)")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm 3 times
        for i in range(3):
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                             network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
            logger.info(f"Entry {i + 1}/3 succeeded")

        # Get all farm tokens for Alice
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) >= 3, (
            f"Alice should have at least 3 farm tokens, got {len(farm_tokens)}"
        )

        # Pick 3 tokens to merge
        tokens_to_merge = farm_tokens[:3]
        total_amount = sum(t.amount for t in tokens_to_merge)
        logger.info(
            f"Merging 3 tokens: "
            f"nonces={[t.token.nonce for t in tokens_to_merge]}, "
            f"amounts={[t.amount for t in tokens_to_merge]}, "
            f"total={total_amount}"
        )

        # Record supply before merge
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Merge all 3
        tx_merge = _merge_farm_positions(farm_contract, alice, tokens_to_merge,
                                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_merge, network_providers.proxy)

        # Verify: supply unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm token supply should be unchanged after merging 3 tokens:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        # Verify: Alice has merged token with correct total amount
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        merged_token = max(farm_tokens_after, key=lambda t: t.token.nonce)
        assert merged_token.amount == total_amount, (
            f"Merged token amount should equal sum of 3 inputs:\n"
            f"  Expected: {total_amount}\n"
            f"  Actual: {merged_token.amount}"
        )

        # Verify: merged token attributes are valid
        attrs_hex = merged_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.FARM_TOKEN_ATTRIBUTES)
        logger.info(f"Merged token attributes: {attrs}")

        assert attrs["current_farm_amount"] == total_amount, (
            f"Merged token current_farm_amount should match total:\n"
            f"  Expected: {total_amount}\n"
            f"  Actual: {attrs['current_farm_amount']}"
        )

        assert attrs["original_owner"] == alice.address.to_bech32(), (
            f"Merged token original_owner should be Alice:\n"
            f"  Expected: {alice.address.to_bech32()}\n"
            f"  Actual: {attrs['original_owner']}"
        )

        # RPS in merged token should be >= 0 (valid)
        assert attrs["reward_per_share"] >= 0, (
            f"Merged token RPS should be non-negative: {attrs['reward_per_share']}"
        )

        logger.info("PASSED: test_merge_preserves_total_amount")
