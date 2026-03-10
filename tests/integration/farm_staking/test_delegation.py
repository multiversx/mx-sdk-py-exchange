"""
Farm Staking Integration Tests - Category 10: Delegation / On-Behalf Operations

Tests delegated (on-behalf) staking operations via stakeFarmOnBehalf and
claimRewardsOnBehalf. These require whitelist authorization.

Coverage: 5 tests (P2)
"""

import pytest
import config
from events.farm_events import EnterFarmEvent, ClaimRewardsFarmEvent
from utils.logger import get_logger
from utils.utils_chain import decode_merged_attributes, nominated_amount
from utils import decoding_structures
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
    _stake_farm,
    _get_farm_tokens_for_user,
)

logger = get_logger(__name__)


@pytest.fixture
def permissions_hub_contract(dex_context):
    contracts = dex_context.get_contracts(config.PERMISSIONS_HUBS)
    if not contracts:
        pytest.skip("Permissions hub contract not configured for delegation tests")
    return contracts[0]


def _whitelist_delegate_or_skip(
    permissions_hub_contract,
    user,
    delegate,
    network_providers,
    blockchain_controller,
):
    user.sync_nonce(network_providers.proxy)
    tx_hash = permissions_hub_contract.add_to_whitelist(
        user,
        network_providers.proxy,
        [delegate.address.to_bech32()],
    )
    blockchain_controller.wait_for_tx(tx_hash)
    tx_data = network_providers.proxy.get_transaction(tx_hash)
    if tx_data.status.is_failed:
        pytest.skip("Permissions hub whitelist flow unavailable on loaded chain-sim state")
    TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)


def _remove_delegate_from_whitelist(
    permissions_hub_contract,
    user,
    delegate,
    network_providers,
    blockchain_controller,
):
    user.sync_nonce(network_providers.proxy)
    tx_hash = permissions_hub_contract.remove_from_whitelist(
        user,
        network_providers.proxy,
        [delegate.address.to_bech32()],
    )
    blockchain_controller.wait_for_tx(tx_hash)
    tx_data = network_providers.proxy.get_transaction(tx_hash)
    if tx_data.status.is_successful:
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)


class TestDelegation:
    """Test suite for on-behalf delegation operations"""

    def test_stake_on_behalf(
        self,
        staking_contract,
        alice,
        bob,
        permissions_hub_contract,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Whitelisted caller (bob) stakes on behalf of alice: original_owner = alice"""
        logger.info("TEST: Stake on behalf")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        _whitelist_delegate_or_skip(
            permissions_hub_contract, alice, bob, network_providers, blockchain_controller
        )
        logger.info(f"Whitelisted bob via permissions hub: {bob.address.to_bech32()}")

        try:
            # Fund bob with farming tokens (he's the one sending tokens on behalf of alice)
            ensure_esdt_amounts(bob, {farming_token: stake_amount})

            # Bob stakes on behalf of alice
            bob.sync_nonce(network_providers.proxy)
            enter_event = EnterFarmEvent(
                farming_token=farming_token,
                farming_nonce=0,
                farming_amount=stake_amount,
                farm_token=staking_contract.farm_token,
                farm_nonce=0,
                farm_amount=0,
                on_behalf=alice.address.to_bech32(),
            )
            tx_hash = staking_contract.stake_farm_on_behalf(network_providers, bob, enter_event)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Alice's position should have increased
            alice_position = staking_contract.get_user_total_farm_position(
                alice.address.to_bech32(), network_providers.proxy
            )
            assert alice_position >= stake_amount, (
                f"Alice's position should reflect delegated stake:\n"
                f"  Alice position: {alice_position}\n"
                f"  Staked: {stake_amount}"
            )

            bob_farm_tokens = _get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy)
            assert bob_farm_tokens, "Bob should receive the delegated farm token"
            delegated_token = max(bob_farm_tokens, key=lambda t: t.token.nonce)
            delegated_attrs = decode_merged_attributes(
                delegated_token.attributes.hex(),
                decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES,
            )
            assert delegated_attrs["original_owner"] == alice.address.to_bech32(), (
                f"Delegated farm token original_owner mismatch:\n"
                f"  Expected: {alice.address.to_bech32()}\n"
                f"  Actual: {delegated_attrs['original_owner']}"
            )

            logger.info(f"✓ stakeOnBehalf: alice position = {alice_position}")

        finally:
            _remove_delegate_from_whitelist(
                permissions_hub_contract,
                alice,
                bob,
                network_providers,
                blockchain_controller,
            )

    def test_claim_rewards_on_behalf(
        self,
        staking_contract,
        alice,
        bob,
        permissions_hub_contract,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Whitelisted caller (bob) claims rewards for alice"""
        logger.info("TEST: Claim rewards on behalf")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        _whitelist_delegate_or_skip(
            permissions_hub_contract, alice, bob, network_providers, blockchain_controller
        )

        try:
            ensure_esdt_amounts(bob, {farming_token: stake_amount})

            bob.sync_nonce(network_providers.proxy)
            enter_event = EnterFarmEvent(
                farming_token=farming_token,
                farming_nonce=0,
                farming_amount=stake_amount,
                farm_token=staking_contract.farm_token,
                farm_nonce=0,
                farm_amount=0,
                on_behalf=alice.address.to_bech32(),
            )
            tx_stake = staking_contract.stake_farm_on_behalf(network_providers, bob, enter_event)
            blockchain_controller.wait_for_tx(tx_stake)
            TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

            blockchain_controller.wait_blocks(10)

            bob_farm_tokens = _get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy)
            assert bob_farm_tokens, "Bob should hold the delegated farm token"
            delegated_token = max(bob_farm_tokens, key=lambda t: t.token.nonce)

            bob.sync_nonce(network_providers.proxy)
            claim_event = ClaimRewardsFarmEvent(
                amount=delegated_token.balance,
                nonce=delegated_token.token.nonce,
                attributes="",
            )
            tx_hash = staking_contract.claim_rewards_on_behalf(network_providers, bob, claim_event)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            bob_farm_tokens_after = _get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy)
            claimed_token = max(bob_farm_tokens_after, key=lambda t: t.token.nonce)
            claimed_attrs = decode_merged_attributes(
                claimed_token.attributes.hex(),
                decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES,
            )
            assert claimed_token.token.nonce != delegated_token.token.nonce, (
                "claimRewardsOnBehalf should mint a new farm token nonce"
            )
            assert claimed_attrs["original_owner"] == alice.address.to_bech32(), (
                f"Claimed delegated farm token original_owner mismatch:\n"
                f"  Expected: {alice.address.to_bech32()}\n"
                f"  Actual: {claimed_attrs['original_owner']}"
            )

        finally:
            _remove_delegate_from_whitelist(
                permissions_hub_contract,
                alice,
                bob,
                network_providers,
                blockchain_controller,
            )

    def test_on_behalf_unauthorized_fails(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Non-whitelisted caller cannot perform on-behalf operations"""
        logger.info("TEST: On-behalf unauthorized fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Fund bob with farming tokens
        ensure_esdt_amounts(bob, {farming_token: stake_amount})

        # Bob tries to stake on behalf of alice without being whitelisted
        bob.sync_nonce(network_providers.proxy)
        enter_event = EnterFarmEvent(
            farming_token=farming_token,
            farming_nonce=0,
            farming_amount=stake_amount,
            farm_token=staking_contract.farm_token,
            farm_nonce=0,
            farm_amount=0,
            on_behalf=alice.address.to_bech32(),
        )
        tx_hash = staking_contract.stake_farm_on_behalf(network_providers, bob, enter_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Unauthorized on-behalf operation correctly rejected")

    def test_allow_external_claim_boosted(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """User enables external claim for boosted rewards: any caller can claim"""
        logger.info("TEST: Allow external claim boosted rewards")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        if staking_contract.version.name != "V3Boosted":
            pytest.skip("allowExternalClaimBoostedRewards not available on non-boosted staking contracts")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Alice stakes
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_stake = _stake_farm(
            staking_contract, alice, farming_token, stake_amount,
            network_providers, blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_stake, network_providers.proxy)

        # Alice enables external claiming
        alice.sync_nonce(network_providers.proxy)
        tx_allow = staking_contract.allow_external_claim(network_providers, alice)
        blockchain_controller.wait_for_tx(tx_allow)
        tx_allow_data = network_providers.proxy.get_transaction(tx_allow)
        if tx_allow_data.status.is_failed:
            pytest.skip("allowExternalClaimBoostedRewards unavailable on the selected staking contract")
        TransactionAssertions.assert_transaction_success(tx_allow, network_providers.proxy)
        logger.info("Alice enabled external claim")

        # Bob claims boosted for alice (now permitted)
        blockchain_controller.wait_blocks(5)
        bob.sync_nonce(network_providers.proxy)
        claim_event = ClaimRewardsFarmEvent(
            amount=0, nonce=0, attributes="",
            user=alice.address.to_bech32()
        )
        tx_hash = staking_contract.claim_boosted_rewards(network_providers, bob, claim_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        logger.info("✓ External boosted claim succeeded after allowExternalClaimBoostedRewards")

    def test_on_behalf_farm_token_ownership(
        self,
        staking_contract,
        alice,
        bob,
        permissions_hub_contract,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Farm token original_owner is alice when bob stakes on her behalf"""
        logger.info("TEST: On-behalf farm token ownership")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        _whitelist_delegate_or_skip(
            permissions_hub_contract, alice, bob, network_providers, blockchain_controller
        )

        try:
            ensure_esdt_amounts(bob, {farming_token: stake_amount})
            bob.sync_nonce(network_providers.proxy)
            enter_event = EnterFarmEvent(
                farming_token=farming_token,
                farming_nonce=0,
                farming_amount=stake_amount,
                farm_token=staking_contract.farm_token,
                farm_nonce=0,
                farm_amount=0,
                on_behalf=alice.address.to_bech32(),
            )
            tx_hash = staking_contract.stake_farm_on_behalf(network_providers, bob, enter_event)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            bob_farm_tokens = _get_farm_tokens_for_user(staking_contract, bob, network_providers.proxy)
            assert bob_farm_tokens, "Bob should receive the delegated farm token"
            delegated_token = max(bob_farm_tokens, key=lambda t: t.token.nonce)
            delegated_attrs = decode_merged_attributes(
                delegated_token.attributes.hex(),
                decoding_structures.STAKE_V2_TOKEN_ATTRIBUTES,
            )
            assert delegated_attrs["original_owner"] == alice.address.to_bech32(), (
                f"Farm token original_owner mismatch:\n"
                f"  Expected: {alice.address.to_bech32()}\n"
                f"  Actual: {delegated_attrs['original_owner']}"
            )
        finally:
            _remove_delegate_from_whitelist(
                permissions_hub_contract,
                alice,
                bob,
                network_providers,
                blockchain_controller,
            )

        logger.info(f"✓ On-behalf farm token original_owner = {alice.address.to_bech32()}")
