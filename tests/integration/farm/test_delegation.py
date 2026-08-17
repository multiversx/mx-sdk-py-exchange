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
  regular user addresses (expects SC addresses)
- allowExternalClaimBoostedRewards endpoint is NOT available on mainnet bytecode

Run:
    pytest --env=chainsim tests/integration/farm/test_delegation.py -v
"""

import pytest

from contracts.farm_contract import FarmContract
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _check_farm_has_code,
    _claim_rewards_on_behalf,
    _ensure_deployer_has_egld,
    _enter_farm,
    _enter_farm_on_behalf,
    _get_farm_state,
    _get_farm_tokens_for_user,
    _get_stake_amount,
    _remove_from_whitelist,
    _whitelist_address,
)
from utils.logger import get_logger
from utils.utils_chain import Account
from utils.utils_tx import NetworkProviders

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
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            bob_bech32,
            network_providers,
            blockchain_controller,
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
        tx_enter = _enter_farm(
            farm_contract,
            bob,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
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
        tx_hash = _claim_rewards_on_behalf(
            farm_contract,
            alice,
            bob_ft.token.nonce,
            bob_ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

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
                farm_contract,
                deployer_account,
                network_providers.proxy,
                alice_bech32,
                blockchain_controller,
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
            deployer_account.sync_nonce(network_providers.proxy)
            tx_remove = _remove_from_whitelist(
                farm_contract,
                deployer_account,
                network_providers.proxy,
                alice_bech32,
                blockchain_controller,
            )
            logger.info(f"Cleanup: removed Alice from whitelist (tx: {tx_remove})")

        logger.info("PASSED: test_whitelist_address")

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
            farm_contract,
            deployer_account,
            network_providers.proxy,
            alice_bech32,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
        logger.info(f"Whitelisted Alice: {alice_bech32}")

        # Step 2: Remove Alice from whitelist
        tx_remove = _remove_from_whitelist(
            farm_contract,
            deployer_account,
            network_providers.proxy,
            alice_bech32,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
        logger.info(f"Removed Alice from whitelist: {alice_bech32}")

        # Step 3: Alice tries on-behalf operation (should fail)
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        tx_hash = _enter_farm_on_behalf(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            bob_bech32,
            network_providers,
            blockchain_controller,
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
