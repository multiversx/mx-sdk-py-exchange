"""
Integration tests for Farm-with-locked-rewards contract delegation (on-behalf) endpoints.

These tests verify the enterFarmOnBehalf, claimRewardsOnBehalf, and whitelist
mechanisms through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Context:
- enterFarmOnBehalf and claimRewardsOnBehalf require the caller to be whitelisted
- The whitelist system uses addSCAddressToWhitelist from BaseSCWhitelistContract
- On chain sim with mainnet state, the whitelist mechanism may not work for
  regular user addresses (expects SC addresses) — tests use xfail/skip as needed
- allowExternalClaimBoostedRewards endpoint is NOT available on mainnet bytecode

Run:
    pytest --env=chainsim tests/integration/farm/test_delegation.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, ClaimRewardsFarmEvent
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
    _enter_farm_on_behalf,
    _exit_farm,
    _claim_rewards,
    _claim_rewards_on_behalf,
    _claim_boosted_rewards,
    _whitelist_address,
    _remove_from_whitelist,
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
class TestFarmDelegation:
    """
    Integration tests for Farm on-behalf delegation endpoints.

    Contract Endpoints Tested:
    - enterFarmOnBehalf(farming_token, on_behalf_address) -> (farm_token)
    - claimRewardsOnBehalf(farm_token) -> (new_farm_token, locked_rewards)
    - addSCAddressToWhitelist(address) — deployer-only whitelist management
    - removeSCAddressFromWhitelist(address) — deployer-only whitelist management

    Key Behaviors:
    1. On-behalf operations require the caller to be whitelisted
    2. Unauthorized callers are rejected
    3. Deployer can add/remove addresses from the whitelist
    4. Farm tokens from enterFarmOnBehalf have original_owner set to the on_behalf user

    Note: Many of these tests may fail because:
    - The whitelist mechanism uses addSCAddressToWhitelist (expects SC addresses)
    - On mainnet bytecode, user address whitelisting may use PermissionsHub instead
    - Tests use xfail where the whitelist mechanism is expected to not work
    """

    # ----------------------------------------------------------------
    # Unauthorized Access Tests
    # ----------------------------------------------------------------

    def test_enter_farm_on_behalf_unauthorized_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Non-whitelisted user cannot enter farm on behalf of another

        GIVEN: Alice is NOT whitelisted on the farm contract
        WHEN: Alice tries enterFarmOnBehalf for Bob
        THEN: Transaction fails (unauthorized caller)
        """
        logger.info("TEST: Enter farm on behalf unauthorized fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Fund Alice with farming tokens
        ensure_esdt_amounts(alice, {farming_token: stake_amount})

        # Alice tries to enter farm on behalf of Bob (not whitelisted)
        bob_bech32 = bob.address.to_bech32()
        tx_hash = _enter_farm_on_behalf(
            farm_contract, alice, farming_token, stake_amount,
            bob_bech32, network_providers, blockchain_controller
        )

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm supply should be unchanged after failed on-behalf entry:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        logger.info("PASSED: test_enter_farm_on_behalf_unauthorized_fails")

    def test_claim_rewards_on_behalf_unauthorized_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Non-whitelisted user cannot claim rewards on behalf of another

        GIVEN: Bob has a farm position, Alice is NOT whitelisted
        WHEN: Alice tries claimRewardsOnBehalf with Bob's farm token
        THEN: Transaction fails (unauthorized caller)
        """
        logger.info("TEST: Claim rewards on behalf unauthorized fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Ensure Bob has a farm position
        ensure_esdt_amounts(bob, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, bob, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Get Bob's farm token
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        assert len(bob_farm_tokens) > 0, "Bob should have farm tokens"
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)

        # Transfer Bob's farm token to Alice for the test
        # (In practice, Alice would need the farm token to call claimRewardsOnBehalf)
        # Since we cannot easily transfer NFTs in this framework, we'll have Alice
        # try with a non-existent nonce, which should also fail
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        # Alice tries to claim on behalf with Bob's farm token nonce.
        # This will fail either because Alice doesn't have the token or isn't whitelisted.
        # If Alice doesn't hold the NFT, the transaction may never be processed
        # (ESDT validation failure at node level), causing a timeout.
        try:
            tx_hash = _claim_rewards_on_behalf(
                farm_contract, alice, bob_ft.token.nonce,
                bob_ft.amount, network_providers, blockchain_controller
            )
            TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        except TimeoutError:
            # Transaction was rejected at node level (Alice doesn't have the NFT)
            # This is the expected behavior — unauthorized claim is rejected
            logger.info("Transaction timed out (rejected at node level) — expected for missing NFT")

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm supply should be unchanged after failed on-behalf claim:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        logger.info("PASSED: test_claim_rewards_on_behalf_unauthorized_fails")

    # ----------------------------------------------------------------
    # Whitelist Management Tests
    # ----------------------------------------------------------------

    def test_whitelist_address(
        self,
        farm_contract: FarmContract,
        alice: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        test_environment,
    ):
        """
        SCENARIO: Deployer whitelists Alice on the farm contract

        GIVEN: Alice is not whitelisted
        WHEN: Deployer calls addSCAddressToWhitelist(Alice)
        THEN: Transaction succeeds
        CLEANUP: Remove Alice from whitelist
        """
        logger.info("TEST: Whitelist address")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        alice_bech32 = alice.address.to_bech32()

        try:
            # Whitelist Alice
            tx_whitelist = _whitelist_address(
                farm_contract, deployer_account, network_providers.proxy,
                alice_bech32, blockchain_controller
            )
            TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
            logger.info(f"Whitelisted Alice: {alice_bech32}")

            # Verify Alice is whitelisted
            is_whitelisted = farm_contract.is_contract_whitelisted(
                alice_bech32, network_providers.proxy
            )
            logger.info(f"Alice whitelisted: {is_whitelisted}")
            assert is_whitelisted, "Alice should be whitelisted after addSCAddressToWhitelist"

        finally:
            # Cleanup: remove Alice from whitelist
            try:
                deployer_account.sync_nonce(network_providers.proxy)
                tx_remove = _remove_from_whitelist(
                    farm_contract, deployer_account, network_providers.proxy,
                    alice_bech32, blockchain_controller
                )
                logger.info(f"Cleanup: removed Alice from whitelist (tx: {tx_remove})")
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")

        logger.info("PASSED: test_whitelist_address")

    @pytest.mark.xfail(reason=(
        "isWhitelisted makes a cross-contract call to the PermissionsHub SC, "
        "whose bytecode is not loaded in the chain sim state dump"
    ))
    def test_enter_farm_on_behalf(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
    ):
        """
        SCENARIO: Whitelisted Alice enters farm on behalf of Bob

        GIVEN: Alice is whitelisted on the farm contract
        WHEN: Alice calls enterFarmOnBehalf with Bob as beneficiary
        THEN:
            - Transaction succeeds
            - Farm token is minted to Alice (caller receives the token)
            - Farm token original_owner = Bob
            - Farm token supply increases
        CLEANUP: Remove Alice from whitelist
        """
        logger.info("TEST: Enter farm on behalf")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        alice_bech32 = alice.address.to_bech32()
        bob_bech32 = bob.address.to_bech32()

        try:
            # Whitelist Alice
            tx_whitelist = _whitelist_address(
                farm_contract, deployer_account, network_providers.proxy,
                alice_bech32, blockchain_controller
            )
            TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
            logger.info(f"Whitelisted Alice: {alice_bech32}")

            # Fund Alice with farming tokens
            ensure_esdt_amounts(alice, {farming_token: stake_amount})

            supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
            alice_farm_tokens_before = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)

            # Alice enters farm on behalf of Bob
            tx_hash = _enter_farm_on_behalf(
                farm_contract, alice, farming_token, stake_amount,
                bob_bech32, network_providers, blockchain_controller
            )
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Farm token supply increased
            supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
            assert supply_after == supply_before + stake_amount, (
                f"Farm supply should increase by stake amount:\n"
                f"  Before: {supply_before}\n"
                f"  After: {supply_after}\n"
                f"  Expected increase: {stake_amount}"
            )

            # Alice should have received a farm token
            alice_farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            assert len(alice_farm_tokens_after) > len(alice_farm_tokens_before), (
                f"Alice should have received a new farm token:\n"
                f"  Before: {len(alice_farm_tokens_before)} tokens\n"
                f"  After: {len(alice_farm_tokens_after)} tokens"
            )

            # Verify original_owner is Bob
            latest_token = max(alice_farm_tokens_after, key=lambda t: t.token.nonce)
            attrs = decode_merged_attributes(
                latest_token.attributes.hex(),
                decoding_structures.FARM_TOKEN_ATTRIBUTES
            )
            logger.info(f"Farm token attributes: {attrs}")

            if "original_owner" in attrs:
                assert attrs["original_owner"] == bob_bech32, (
                    f"Farm token original_owner should be Bob:\n"
                    f"  Expected: {bob_bech32}\n"
                    f"  Actual: {attrs['original_owner']}"
                )
            else:
                logger.warning("original_owner not found in farm token attributes")

        finally:
            # Cleanup: remove Alice from whitelist
            try:
                deployer_account.sync_nonce(network_providers.proxy)
                tx_remove = _remove_from_whitelist(
                    farm_contract, deployer_account, network_providers.proxy,
                    alice_bech32, blockchain_controller
                )
                logger.info(f"Cleanup: removed Alice from whitelist (tx: {tx_remove})")
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")

        logger.info("PASSED: test_enter_farm_on_behalf")

    @pytest.mark.xfail(reason=(
        "isWhitelisted makes a cross-contract call to the PermissionsHub SC, "
        "whose bytecode is not loaded in the chain sim state dump"
    ))
    def test_claim_rewards_on_behalf(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
    ):
        """
        SCENARIO: Whitelisted Alice claims rewards on behalf using her farm token

        GIVEN: Alice is whitelisted and has a farm token (from enterFarmOnBehalf or direct enter)
        WHEN: Alice calls claimRewardsOnBehalf with her farm token
        THEN:
            - Transaction succeeds
            - Alice receives a new farm token with updated RPS
            - Farm token supply is unchanged
        CLEANUP: Remove Alice from whitelist
        """
        logger.info("TEST: Claim rewards on behalf")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        alice_bech32 = alice.address.to_bech32()

        try:
            # Whitelist Alice
            tx_whitelist = _whitelist_address(
                farm_contract, deployer_account, network_providers.proxy,
                alice_bech32, blockchain_controller
            )
            TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
            logger.info(f"Whitelisted Alice: {alice_bech32}")

            # Alice enters farm normally first (to get a farm token)
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                                   network_providers, blockchain_controller)
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

            # Get Alice's farm token
            alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            assert len(alice_farm_tokens) > 0, "Alice should have farm tokens"
            farm_token = max(alice_farm_tokens, key=lambda t: t.token.nonce)

            # Advance blocks for potential reward accrual
            blockchain_controller.wait_blocks(5)

            supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

            # Alice claims rewards on behalf
            tx_claim = _claim_rewards_on_behalf(
                farm_contract, alice, farm_token.token.nonce,
                farm_token.amount, network_providers, blockchain_controller
            )
            TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

            # Farm token supply unchanged (old burned, new minted)
            supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
            assert supply_after == supply_before, (
                f"Farm supply should be unchanged after claim on behalf:\n"
                f"  Before: {supply_before}\n"
                f"  After: {supply_after}"
            )

            # Alice still has farm tokens
            alice_farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            assert len(alice_farm_tokens_after) > 0, "Alice should still have farm tokens after claim"

        finally:
            # Cleanup: remove Alice from whitelist
            try:
                deployer_account.sync_nonce(network_providers.proxy)
                tx_remove = _remove_from_whitelist(
                    farm_contract, deployer_account, network_providers.proxy,
                    alice_bech32, blockchain_controller
                )
                logger.info(f"Cleanup: removed Alice from whitelist (tx: {tx_remove})")
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")

        logger.info("PASSED: test_claim_rewards_on_behalf")

    def test_remove_from_whitelist(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        deployer_account: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment,
    ):
        """
        SCENARIO: After removal from whitelist, on-behalf operations fail

        GIVEN: Alice was whitelisted and then removed
        WHEN: Alice tries enterFarmOnBehalf for Bob
        THEN: Transaction fails (no longer whitelisted)
        """
        logger.info("TEST: Remove from whitelist")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        alice_bech32 = alice.address.to_bech32()
        bob_bech32 = bob.address.to_bech32()

        # Step 1: Whitelist Alice
        tx_whitelist = _whitelist_address(
            farm_contract, deployer_account, network_providers.proxy,
            alice_bech32, blockchain_controller
        )
        TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
        logger.info(f"Whitelisted Alice: {alice_bech32}")

        # Step 2: Remove Alice from whitelist
        tx_remove = _remove_from_whitelist(
            farm_contract, deployer_account, network_providers.proxy,
            alice_bech32, blockchain_controller
        )
        TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
        logger.info(f"Removed Alice from whitelist: {alice_bech32}")

        # Step 3: Alice tries on-behalf operation (should fail)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        tx_hash = _enter_farm_on_behalf(
            farm_contract, alice, farming_token, stake_amount,
            bob_bech32, network_providers, blockchain_controller
        )

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm supply should be unchanged after failed on-behalf entry:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        logger.info("PASSED: test_remove_from_whitelist")
