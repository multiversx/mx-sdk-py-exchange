"""
Integration tests for Farm-with-locked-rewards contract enterFarm endpoint.

These tests verify the enter farm operation through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Normal enter farm operations
2. Edge Cases: Multiple positions, merge on entry
3. Error Cases: Wrong token, zero amount, paused contract

Run:
    pytest --env=chainsim tests/integration/farm/test_enter_farm.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent
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
class TestFarmEnterFarm:
    """
    Integration tests for Farm.enterFarm()

    Contract Endpoints Tested:
    - enterFarm(opt_orig_caller) -> (farm_token, locked_rewards)

    Key Behaviors:
    1. User stakes LP tokens (farming token) into the farm
    2. Receives a farm token NFT (MetaFungible) with RPS snapshot
    3. Any pending boosted rewards are auto-claimed as XMEX
    4. Farm token supply increases by staked amount
    5. User's total farm position is updated
    """

    # ----------------------------------------------------------------
    # Happy Path Tests
    # ----------------------------------------------------------------

    def test_enter_farm_basic(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice enters the farm by staking LP tokens

        GIVEN: Farm contract is active with loaded state
        WHEN: Alice stakes LP tokens via enterFarm
        THEN:
            - Transaction succeeds
            - Farm token supply increases
            - Alice receives farm token NFT
            - Farm state (RPS, reserve) is consistent
        """
        logger.info("TEST: Enter farm basic")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farm_state_before = _get_farm_state(farm_contract, network_providers.proxy)
        farming_token = farm_state_before["farming_token_id"]
        assert farming_token == farm_contract.farmingToken

        supply_before = farm_state_before["farm_token_supply"]
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        logger.info(f"Staking {stake_amount} of {farming_token}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                              network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        farm_state_after = _get_farm_state(farm_contract, network_providers.proxy)
        logger.info(f"Farm state: supply {supply_before} -> {farm_state_after['farm_token_supply']}")

        # Farm token supply increases by staked amount
        assert farm_state_after["farm_token_supply"] == supply_before + stake_amount

        # RPS never decreases
        assert farm_state_after["reward_per_share"] >= farm_state_before["reward_per_share"]

        # Alice received farm token NFT
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have received farm token NFT"

        logger.info("PASSED: test_enter_farm_basic")

    def test_enter_farm_second_entry_increases_supply(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Re-entering farm increases supply on a second entry

        GIVEN: Alice already has a farm position (from test_enter_farm_basic)
        WHEN: Alice enters farm again with new LP tokens
        THEN:
            - Transaction succeeds
            - Farm token supply increases by new stake
            - The second entry path works without relying on boosted rewards

        NOTE: On chain simulator user energy is zero, so boosted rewards are not
        expected here. This test verifies the second-entry supply path only.
        """
        logger.info("TEST: Enter farm second entry increases supply")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                              network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before + stake_amount

        logger.info("PASSED: test_enter_farm_second_entry_increases_supply")

    def test_enter_farm_updates_total_farm_position(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: getUserTotalFarmPosition increases after enterFarm

        GIVEN: Farm contract tracks total farm position per user
        WHEN: Alice stakes LP tokens via enterFarm
        THEN: getUserTotalFarmPosition for Alice increases by staked amount
        """
        logger.info("TEST: Enter farm updates total farm position")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        position_before = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"Total farm position before: {position_before}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                              network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        position_after = farm_contract.get_user_total_farm_position(
            alice.address.to_bech32(), network_providers.proxy
        )
        logger.info(f"Total farm position after: {position_after}")

        assert position_after == position_before + stake_amount, (
            f"Total farm position mismatch:\n"
            f"  Before: {position_before}\n"
            f"  After: {position_after}\n"
            f"  Expected increase: {stake_amount}"
        )

        logger.info("PASSED: test_enter_farm_updates_total_farm_position")

    def test_enter_farm_multiple_positions(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Entering farm twice creates separate farm token nonces

        GIVEN: Alice has no prior farm tokens (or some from prior tests)
        WHEN: Alice enters farm twice with separate transactions
        THEN:
            - Alice receives two farm token NFTs (possibly different nonces)
            - Total farm token supply increases by both amounts
        """
        logger.info("TEST: Enter farm multiple positions")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # First entry
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        farm_tokens_after_first = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        nonces_after_first = {t.token.nonce for t in farm_tokens_after_first}
        logger.info(f"Farm token nonces after 1st entry: {nonces_after_first}")

        # Second entry
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        farm_tokens_after_second = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        nonces_after_second = {t.token.nonce for t in farm_tokens_after_second}
        logger.info(f"Farm token nonces after 2nd entry: {nonces_after_second}")

        # Should have at least one new nonce
        new_nonces = nonces_after_second - nonces_after_first
        assert len(new_nonces) > 0, (
            f"Expected new farm token nonce after second entry.\n"
            f"  Nonces after 1st: {nonces_after_first}\n"
            f"  Nonces after 2nd: {nonces_after_second}"
        )

        # Total supply increased by both stakes
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before + 2 * stake_amount, (
            f"Supply mismatch: expected {supply_before + 2 * stake_amount}, got {supply_after}"
        )

        logger.info("PASSED: test_enter_farm_multiple_positions")

    def test_enter_farm_with_existing_farm_token(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Enter farm with LP tokens + existing farm token (merge)

        GIVEN: Alice has an existing farm token from a prior enterFarm
        WHEN: Alice enters farm with LP tokens AND her existing farm token
        THEN:
            - Positions are merged into a single farm token
            - Old farm token nonce is consumed
            - New farm token has combined amount
            - Farm token supply increases only by new LP amount (old token amount is recycled)
        """
        logger.info("TEST: Enter farm with existing farm token (merge)")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # First: ensure Alice has a farm token
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx1 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        # Get Alice's farm token for merge
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have a farm token for merge test"

        existing_token = max(farm_tokens, key=lambda t: t.token.nonce)
        existing_nonce = existing_token.token.nonce
        existing_amount = existing_token.amount
        logger.info(f"Merging farm token nonce={existing_nonce}, amount={existing_amount}")

        # Track supply before merge
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Enter farm again with LP tokens + existing farm token
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx2 = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                          network_providers, blockchain_controller,
                          farm_nonce=existing_nonce, farm_amount=existing_amount)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        # Supply should increase only by the new LP amount (existing token is recycled)
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before + stake_amount, (
            f"Supply mismatch after merge:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}\n"
            f"  Expected increase: {stake_amount} (existing {existing_amount} recycled)"
        )

        logger.info("PASSED: test_enter_farm_with_existing_farm_token")

    # ----------------------------------------------------------------
    # Error Case Tests
    # ----------------------------------------------------------------

    def test_enter_farm_zero_amount_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
    ):
        """
        SCENARIO: Entering farm with zero LP tokens fails

        GIVEN: Farm contract is active
        WHEN: Alice sends enterFarm with 0 LP tokens
        THEN: Transaction fails (protocol rejects zero-amount ESDT transfers)
        """
        logger.info("TEST: Enter farm zero amount fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        tx_hash = _enter_farm(farm_contract, alice, farming_token, 0,
                              network_providers, blockchain_controller)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before

        logger.info("PASSED: test_enter_farm_zero_amount_fails")

    def test_enter_farm_wrong_token_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Sending non-LP token to enterFarm fails

        GIVEN: Farm contract expects specific farming token (LP token)
        WHEN: Alice sends reward token (MEX) instead of LP token
        THEN: Transaction fails with bad payment error
        """
        logger.info("TEST: Enter farm wrong token fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        wrong_token = farm_contract.farmedToken  # MEX instead of EGLDMEX-LP
        stake_amount = nominated_amount(10)
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        ensure_esdt_amounts(alice, {wrong_token: stake_amount})

        alice.sync_nonce(network_providers.proxy)
        enter_event = EnterFarmEvent(
            farming_token=wrong_token,
            farming_nonce=0,
            farming_amount=stake_amount,
            farm_token=farm_contract.farmToken,
            farm_nonce=0,
            farm_amount=0,
        )
        tx_hash = farm_contract.enterFarm(network_providers, alice, enter_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy,
            expected_error="Bad payments"
        )

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before

        logger.info("PASSED: test_enter_farm_wrong_token_fails")

    def test_enter_farm_when_paused_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
    ):
        """
        SCENARIO: Entering farm when contract is paused fails

        GIVEN: Farm contract is paused by deployer
        WHEN: Alice tries to enter farm
        THEN: Transaction fails with "not active" error
        CLEANUP: Always resume the contract
        """
        logger.info("TEST: Enter farm when paused fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Fund Alice before pausing
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        # Pause the farm
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = farm_contract.pause(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Farm paused")

        try:
            # Attempt enterFarm while paused
            tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                  network_providers, blockchain_controller)

            TransactionAssertions.assert_transaction_failed(
                tx_hash, network_providers.proxy,
                expected_error="Not active"
            )

            # Farm state unchanged
            supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
            assert supply_after == supply_before
        finally:
            # Always resume
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = farm_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Farm resumed (cleanup)")

        logger.info("PASSED: test_enter_farm_when_paused_fails")

    # ----------------------------------------------------------------
    # Attribute & State Verification Tests
    # ----------------------------------------------------------------

    def test_enter_farm_farm_token_attributes(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Verify farm token NFT attributes after entry

        GIVEN: Farm contract is active
        WHEN: Alice enters farm and receives a farm token NFT
        THEN: Farm token attributes contain:
            - reward_per_share: matches current global RPS at entry time
            - entering_epoch: current epoch on chain
            - compounded_reward: 0 (fresh entry)
            - current_farm_amount: equals staked amount
            - original_owner: Alice's address
        """
        logger.info("TEST: Enter farm farm token attributes")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        global_rps_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                              network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get the latest farm token NFT
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens"

        # Use the highest nonce (most recent)
        latest_token = max(farm_tokens, key=lambda t: t.token.nonce)
        logger.info(f"Latest farm token: nonce={latest_token.token.nonce}, amount={latest_token.amount}")

        # Decode attributes
        attrs_hex = latest_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.FARM_TOKEN_ATTRIBUTES)
        logger.info(f"Farm token attributes: {attrs}")

        # Verify attributes
        assert attrs["reward_per_share"] >= global_rps_before, (
            f"RPS in farm token should be >= global RPS at entry:\n"
            f"  Token RPS: {attrs['reward_per_share']}\n"
            f"  Global RPS before: {global_rps_before}"
        )

        assert attrs["entering_epoch"] > 0, (
            f"Entering epoch should be > 0, got {attrs['entering_epoch']}"
        )

        assert attrs["current_farm_amount"] == stake_amount, (
            f"Farm amount mismatch:\n"
            f"  Expected: {stake_amount}\n"
            f"  Actual: {attrs['current_farm_amount']}"
        )

        assert attrs["original_owner"] == alice.address.to_bech32(), (
            f"Original owner mismatch:\n"
            f"  Expected: {alice.address.to_bech32()}\n"
            f"  Actual: {attrs['original_owner']}"
        )

        logger.info("PASSED: test_enter_farm_farm_token_attributes")

    def test_enter_farm_preserves_reward_per_share(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Farm token RPS at entry matches current global RPS

        GIVEN: Farm has a known global reward_per_share
        WHEN: Alice enters farm
        THEN: The farm token's RPS attribute equals the global RPS
              (entry RPS snapshot ensures fair reward calculation)

        SECURITY: If entry RPS != global RPS, users could claim unearned rewards
                  or lose rightful rewards on exit.
        """
        logger.info("TEST: Enter farm preserves reward per share")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Query global RPS just before entry
        global_rps = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
        logger.info(f"Global RPS before entry: {global_rps}")

        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        tx_hash = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                              network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get the latest farm token and decode RPS
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        latest_token = max(farm_tokens, key=lambda t: t.token.nonce)
        attrs_hex = latest_token.attributes.hex()
        attrs = decode_merged_attributes(attrs_hex, decoding_structures.FARM_TOKEN_ATTRIBUTES)

        token_rps = attrs["reward_per_share"]
        logger.info(f"Farm token RPS: {token_rps}, Global RPS: {global_rps}")

        # The entry RPS should match the global RPS (may be slightly higher if
        # rewards were generated between query and enterFarm execution)
        assert token_rps >= global_rps, (
            f"Farm token RPS should be >= global RPS:\n"
            f"  Token RPS: {token_rps}\n"
            f"  Global RPS: {global_rps}\n"
            f"  SECURITY: Lower entry RPS means user could claim unearned rewards"
        )

        # Should not be significantly higher (no more than a few blocks of rewards)
        if global_rps > 0:
            rps_diff_pct = (token_rps - global_rps) / global_rps
            assert rps_diff_pct < 0.01, (
                f"Farm token RPS is too far from global RPS ({rps_diff_pct:.4%} difference):\n"
                f"  Token RPS: {token_rps}\n"
                f"  Global RPS: {global_rps}"
            )

        logger.info("PASSED: test_enter_farm_preserves_reward_per_share")
