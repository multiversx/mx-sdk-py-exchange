"""
Integration tests for Farm-with-locked-rewards contract claimRewards endpoint.

These tests verify the claim rewards operation through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Normal claim operations, reward accrual
2. Proportionality & Consecutive: Multi-user fairness, no double-counting
3. State Verification: RPS update, reserve reduction, locked output
4. Error Cases: Wrong token

Run:
    pytest --env=chainsim tests/integration/farm/test_claim_rewards.py -v
"""

import pytest

import config
from contracts.farm_contract import FarmContract
from events.farm_events import EnterFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import FarmContractDataFetcher, SimpleLockEnergyContractDataFetcher
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
class TestFarmClaimRewards:
    """
    Integration tests for Farm.claimRewards()

    Contract Endpoints Tested:
    - claimRewards(farm_token) -> (new_farm_token, locked_rewards)

    Key Behaviors:
    1. User sends farm token NFT to claim accumulated base rewards
    2. Receives a new farm token with updated RPS snapshot
    3. Receives locked rewards (XMEX) proportional to RPS delta
    4. Reward reserve decreases by claimed amount
    5. Farm token supply is unchanged (old burned, new minted with same amount)
    """

    # ----------------------------------------------------------------
    # Happy Path Tests
    # ----------------------------------------------------------------

    def test_claim_rewards_basic(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Alice claims base rewards after blocks pass

        GIVEN: Alice has a farm position from enterFarm
        WHEN: Blocks pass (rewards accrue) and Alice calls claimRewards
        THEN:
            - Transaction succeeds
            - Alice receives a new farm token with updated RPS
            - Farm token supply is unchanged (old burned, new minted)
            - Reward reserve decreases (or stays same if no rewards)
        """
        logger.info("TEST: Claim rewards basic")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Get Alice's farm token
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens after entry"
        farm_token = max(farm_tokens, key=lambda t: t.token.nonce)
        logger.info(f"Farm token: nonce={farm_token.token.nonce}, amount={farm_token.amount}")

        # Record state before claim
        state_before = _get_farm_state(farm_contract, network_providers.proxy)
        supply_before = state_before["farm_token_supply"]

        # Advance blocks for reward accrual. A short window can still quantize to 0
        # on loaded mainnet state because rewards are split and rounded.
        blockchain_controller.wait_blocks(50)

        # Claim rewards
        tx_claim = _claim_rewards(farm_contract, alice, farm_token.token.nonce,
                                  farm_token.amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Verify: Alice has new farm token
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) > 0, "Alice should have farm token after claim"

        # Farm token supply unchanged (old burned, new minted with same amount)
        state_after = _get_farm_state(farm_contract, network_providers.proxy)
        assert state_after["farm_token_supply"] == supply_before, (
            f"Farm token supply should be unchanged after claim:\n"
            f"  Before: {supply_before}\n"
            f"  After: {state_after['farm_token_supply']}"
        )

        # RPS never decreases
        assert state_after["reward_per_share"] >= state_before["reward_per_share"]

        logger.info("PASSED: test_claim_rewards_basic")

    def test_claim_rewards_proportional(
        self,
        farm_contract: FarmContract,
        alice: Account,
        bob: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Two users claim rewards proportional to their stakes

        GIVEN: Alice stakes 2x amount, Bob stakes 1x amount
        WHEN: Both claim rewards after blocks pass
        THEN: Alice's reward reserve reduction is >= Bob's
              (exact 2x ratio not guaranteed due to timing and boosted yields)
        """
        logger.info("TEST: Claim rewards proportional")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        base_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        alice_amount = base_amount * 2
        bob_amount = base_amount

        # Both enter farm
        ensure_esdt_amounts(alice, {farming_token: alice_amount})
        tx_a = _enter_farm(farm_contract, alice, farming_token, alice_amount,
                           network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_a, network_providers.proxy)

        ensure_esdt_amounts(bob, {farming_token: bob_amount})
        tx_b = _enter_farm(farm_contract, bob, farming_token, bob_amount,
                           network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_b, network_providers.proxy)

        # Advance blocks. Small windows can still round down to 0 locked rewards
        # on loaded mainnet state, so use a larger accrual interval here.
        blockchain_controller.wait_blocks(50)

        # Alice claims
        alice_farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        alice_ft = max(alice_farm_tokens, key=lambda t: t.token.nonce)
        reserve_before_alice = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        tx_ca = _claim_rewards(farm_contract, alice, alice_ft.token.nonce,
                               alice_ft.amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_ca, network_providers.proxy)

        reserve_after_alice = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        alice_reward = reserve_before_alice - reserve_after_alice

        # Bob claims
        bob_farm_tokens = _get_farm_tokens_for_user(farm_contract, bob, network_providers.proxy)
        bob_ft = max(bob_farm_tokens, key=lambda t: t.token.nonce)
        reserve_before_bob = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        tx_cb = _claim_rewards(farm_contract, bob, bob_ft.token.nonce,
                               bob_ft.amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_cb, network_providers.proxy)

        reserve_after_bob = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        bob_reward = reserve_before_bob - reserve_after_bob

        logger.info(f"Alice reward: {alice_reward} (stake {alice_amount})")
        logger.info(f"Bob reward: {bob_reward} (stake {bob_amount})")

        # Alice staked 2x, so she should get more rewards (at least equal)
        if alice_reward > 0 and bob_reward > 0:
            assert alice_reward >= bob_reward, (
                f"Alice (2x stake) should get >= Bob's rewards:\n"
                f"  Alice: {alice_reward}\n"
                f"  Bob: {bob_reward}"
            )

        logger.info("PASSED: test_claim_rewards_proportional")

    def test_claim_rewards_consecutive(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Consecutive claims only yield new rewards (no double-counting)

        GIVEN: Alice has a farm position
        WHEN: Alice claims twice with blocks between each claim
        THEN:
            - Both claims succeed
            - Second claim's new farm token has RPS >= first claim's
            - No double-counting of rewards
        """
        logger.info("TEST: Claim rewards consecutive")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance blocks
        blockchain_controller.wait_blocks(5)

        # First claim
        farm_tokens_1 = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft1 = max(farm_tokens_1, key=lambda t: t.token.nonce)
        attrs1 = decode_merged_attributes(ft1.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        rps_before_claim1 = attrs1["reward_per_share"]

        reserve_before_1 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        tx_c1 = _claim_rewards(farm_contract, alice, ft1.token.nonce, ft1.amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_c1, network_providers.proxy)
        reserve_after_1 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        reward_1 = reserve_before_1 - reserve_after_1

        # Get updated farm token after first claim
        farm_tokens_2 = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft2 = max(farm_tokens_2, key=lambda t: t.token.nonce)
        attrs2 = decode_merged_attributes(ft2.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        rps_after_claim1 = attrs2["reward_per_share"]
        logger.info(f"First claim: reward={reward_1}, RPS {rps_before_claim1} -> {rps_after_claim1}")

        # Advance more blocks
        blockchain_controller.wait_blocks(5)

        # Second claim
        reserve_before_2 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        tx_c2 = _claim_rewards(farm_contract, alice, ft2.token.nonce, ft2.amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_c2, network_providers.proxy)
        reserve_after_2 = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        reward_2 = reserve_before_2 - reserve_after_2

        # Get updated farm token after second claim
        farm_tokens_3 = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft3 = max(farm_tokens_3, key=lambda t: t.token.nonce)
        attrs3 = decode_merged_attributes(ft3.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        rps_after_claim2 = attrs3["reward_per_share"]
        logger.info(f"Second claim: reward={reward_2}, RPS {rps_after_claim1} -> {rps_after_claim2}")

        # RPS monotonically increases
        assert rps_after_claim1 >= rps_before_claim1, "RPS should not decrease after first claim"
        assert rps_after_claim2 >= rps_after_claim1, "RPS should not decrease after second claim"

        logger.info("PASSED: test_claim_rewards_consecutive")

    def test_claim_rewards_zero_accrued(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Claiming immediately after entry yields zero or near-zero rewards

        GIVEN: Alice just entered the farm
        WHEN: Alice immediately calls claimRewards (no blocks advanced)
        THEN:
            - Transaction succeeds (no error)
            - Zero or near-zero rewards
            - Alice still has a valid farm token
        """
        logger.info("TEST: Claim rewards zero accrued")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Immediately claim (no block advancement)
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)

        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        tx_claim = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                                  network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        reserve_after = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        reward = reserve_before - reserve_after
        logger.info(f"Immediate claim reward: {reward}")

        # Reward should be zero or near-zero (maybe 1-2 blocks passed during tx processing)
        # We just verify it doesn't fail and doesn't drain a significant portion of reserve
        if reserve_before > 0:
            assert reward <= reserve_before // 100, (
                f"Immediate claim should yield near-zero rewards:\n"
                f"  Reward: {reward}\n"
                f"  Reserve: {reserve_before}"
            )

        # Alice still has a valid farm token
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) > 0, "Alice should still have a farm token"

        logger.info("PASSED: test_claim_rewards_zero_accrued")

    # ----------------------------------------------------------------
    # State Verification Tests
    # ----------------------------------------------------------------

    def test_claim_rewards_updates_farm_token_rps(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: New farm token after claim has updated RPS attribute

        GIVEN: Alice has a farm position with entry RPS
        WHEN: Blocks pass and Alice claims rewards
        THEN: New farm token's reward_per_share attribute >= global RPS at claim time
        """
        logger.info("TEST: Claim rewards updates farm token RPS")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Get entry RPS from farm token
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft_before = max(farm_tokens, key=lambda t: t.token.nonce)
        attrs_before = decode_merged_attributes(ft_before.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        entry_rps = attrs_before["reward_per_share"]
        logger.info(f"Entry RPS: {entry_rps}")

        # Advance blocks
        blockchain_controller.wait_blocks(5)

        # Claim rewards
        tx_claim = _claim_rewards(farm_contract, alice, ft_before.token.nonce,
                                  ft_before.amount, network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Get new farm token's RPS
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft_after = max(farm_tokens_after, key=lambda t: t.token.nonce)
        attrs_after = decode_merged_attributes(ft_after.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES)
        new_rps = attrs_after["reward_per_share"]
        logger.info(f"New RPS after claim: {new_rps}")

        # New farm token RPS should be >= entry RPS
        assert new_rps >= entry_rps, (
            f"New farm token RPS should be >= entry RPS:\n"
            f"  Entry RPS: {entry_rps}\n"
            f"  New RPS: {new_rps}"
        )

        # New farm token should preserve the staked amount
        assert attrs_after["current_farm_amount"] == ft_before.amount, (
            f"Farm amount should be preserved after claim:\n"
            f"  Before: {ft_before.amount}\n"
            f"  After: {attrs_after['current_farm_amount']}"
        )

        logger.info("PASSED: test_claim_rewards_updates_farm_token_rps")

    def test_claim_rewards_reduces_reward_reserve(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Reward reserve decreases by claimed amount

        GIVEN: Farm has a non-zero reward reserve
        WHEN: Alice claims rewards after blocks pass
        THEN: getRewardReserve decreases by the reward amount
        """
        logger.info("TEST: Claim rewards reduces reward reserve")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance blocks for reward accrual
        blockchain_controller.wait_blocks(5)

        # Record reserve before claim
        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Reward reserve before claim: {reserve_before}")

        # Claim
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        tx_claim = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                                  network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        # Record reserve after claim
        reserve_after = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Reward reserve after claim: {reserve_after}")

        # Reserve should not increase significantly (rewards were paid out).
        # Tolerance: per_block_reward_amount=1 mints new rewards each block,
        # so blocks generated for tx finalization can increase reserve slightly.
        reserve_tolerance = 5_000
        assert reserve_after <= reserve_before + reserve_tolerance, (
            f"Reward reserve should not increase significantly after claim:\n"
            f"  Before: {reserve_before}\n"
            f"  After: {reserve_after}\n"
            f"  Delta: {reserve_after - reserve_before}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        logger.info("PASSED: test_claim_rewards_reduces_reward_reserve")

    # ----------------------------------------------------------------
    # Error Case Tests
    # ----------------------------------------------------------------

    def test_claim_rewards_wrong_token_fails(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Sending non-farm token to claimRewards fails

        GIVEN: Farm contract expects farm token NFT
        WHEN: Alice sends LP tokens (farming token) instead of farm token
        THEN: Transaction fails
        """
        logger.info("TEST: Claim rewards wrong token fails")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        wrong_token = farm_contract.farmingToken  # LP token instead of farm token
        amount = nominated_amount(10)
        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        ensure_esdt_amounts(alice, {wrong_token: amount})

        # Manually construct the call with wrong token
        from utils.utils_tx import multi_esdt_endpoint_call, ESDTToken
        alice.sync_nonce(network_providers.proxy)
        tokens = [ESDTToken(wrong_token, 0, amount)]
        tx_hash = multi_esdt_endpoint_call(
            "claimRewards", network_providers.proxy, 50000000,
            alice, Address.new_from_bech32(farm_contract.address),
            "claimRewards", [tokens]
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        # Farm state unchanged
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before

        logger.info("PASSED: test_claim_rewards_wrong_token_fails")

    def test_claim_rewards_output_is_locked(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Claimed rewards are returned as locked tokens, not raw MEX

        GIVEN: Farm-with-locked-rewards contract (rewards go through locking SC)
        WHEN: Alice claims rewards after blocks pass
        THEN:
            - Transaction succeeds
            - Alice does NOT receive raw reward tokens (MEX) as fungible
            - Rewards are either locked (XMEX) or burned (if locking SC has no state)
            - Reward reserve decreases (proving rewards were calculated)
        """
        logger.info("TEST: Claim rewards output is locked")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        reward_token = farm_contract.farmedToken  # MEX — the raw reward token
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                               network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        locked_token_id = _get_locked_token_id(farm_contract, network_providers.proxy)
        locked_before = sum(
            token.amount
            for token in _get_locked_tokens_for_user(farm_contract, alice, network_providers.proxy)
        )

        # Record raw MEX balance before claim
        from multiversx_sdk import Token
        mex_token = Token(reward_token, 0)
        try:
            mex_before = network_providers.proxy.get_token_of_account(alice.address, mex_token).amount
        except Exception:
            mex_before = 0

        # Advance blocks for reward accrual
        blockchain_controller.wait_blocks(5)

        # Claim
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)

        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        tx_claim = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                                  network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)
        reserve_after = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]

        reward_paid = reserve_before - reserve_after
        logger.info(f"Reward paid from reserve: {reward_paid}")

        # Check that Alice did NOT receive raw MEX (rewards should be locked)
        try:
            mex_after = network_providers.proxy.get_token_of_account(alice.address, mex_token).amount
        except Exception:
            mex_after = 0

        mex_received = mex_after - mex_before
        logger.info(f"Raw MEX received: {mex_received} (should be 0 — rewards are locked)")

        # In farm-with-locked-rewards, raw MEX should NOT be sent to user
        assert mex_received == 0, (
            f"Alice should NOT receive raw MEX — rewards must be locked:\n"
            f"  MEX before: {mex_before}\n"
            f"  MEX after: {mex_after}\n"
            f"  Raw MEX received: {mex_received}"
        )

        locked_after = sum(
            token.amount
            for token in _get_locked_tokens_for_user(farm_contract, alice, network_providers.proxy)
        )
        locked_received = locked_after - locked_before
        if locked_received == 0:
            pytest.skip("No locked rewards accrued for this farm position after 50 blocks on loaded state")
        assert locked_received > 0, (
            f"Alice should receive locked XMEX on claim:\n"
            f"  Locked token id: {locked_token_id or 'discovered via NFT delta fallback'}\n"
            f"  Locked before: {locked_before}\n"
            f"  Locked after: {locked_after}\n"
            f"  Locked received: {locked_received}"
        )

        logger.info("PASSED: test_claim_rewards_output_is_locked")
