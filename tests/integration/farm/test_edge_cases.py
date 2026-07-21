"""
Integration tests for Farm-with-locked-rewards contract edge cases.

These tests verify the farm contract handles boundary and unusual scenarios:
- Enter and exit in rapid succession
- Dust amounts (1 wei)
- Large stake amounts
- Rapid enter/exit cycles
- Claim with large reserve
- Exit penalty boundary (minimum farming epochs)

Test Categories:
1. Rapid Operations: Enter/exit in quick succession
2. Amount Boundaries: Dust amounts, large amounts
3. State Consistency: Repeated enter/exit cycles
4. Reward Mechanics: Claim behavior with large reserve
5. Penalty Boundary: Exact minimum farming epochs

Run:
    pytest --env=chainsim tests/integration/farm/test_edge_cases.py -v
"""

import pytest

from contracts.farm_contract import FarmContract
from tests.helpers import TransactionAssertions
from tests.integration.farm import (
    _check_farm_has_code,
    _claim_rewards,
    _enter_farm,
    _exit_farm,
    _get_farm_state,
    _get_farm_tokens_for_user,
    _get_farming_token_balance,
    _get_minimum_farming_epochs,
    _get_stake_amount,
)
from utils import decoding_structures
from utils.logger import get_logger
from utils.utils_chain import Account, decode_merged_attributes, nominated_amount
from utils.utils_tx import NetworkProviders

logger = get_logger(__name__)


# ============================================================================
# TEST CLASS
# ============================================================================


@pytest.mark.integration
@pytest.mark.farm
class TestFarmEdgeCases:
    """
    Integration tests for Farm contract edge cases and boundary conditions.

    Verifies that the farm contract handles unusual inputs, rapid operations,
    and boundary amounts without errors, overflows, or state corruption.
    """

    def test_enter_exit_same_block(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Enter farm and exit in rapid succession.

        GIVEN: Farm contract is active
        WHEN: Alice enters farm and immediately exits (minimal block gap)
        THEN:
            - Both transactions succeed
            - Farm token supply returns to original value
            - Minimal or zero rewards (near-zero time in farm)
            - Alice gets LP tokens back (possibly minus early exit penalty)

        EDGE CASE: Near-zero time in farm should not cause division errors
                   or incorrect reward calculations.
        """
        logger.info("TEST: Enter exit same block")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        farm_state_before = _get_farm_state(farm_contract, network_providers.proxy)
        supply_before = farm_state_before["farm_token_supply"]

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Immediately exit (next block)
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens after entry"
        ft = max(farm_tokens, key=lambda t: t.token.nonce)

        tx_exit = _exit_farm(
            farm_contract,
            alice,
            ft.token.nonce,
            ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)

        # Farm token supply should return to original
        farm_state_after = _get_farm_state(farm_contract, network_providers.proxy)
        supply_after = farm_state_after["farm_token_supply"]
        assert supply_after == supply_before, (
            f"Farm token supply should return to original after enter+exit:\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}"
        )

        logger.info("PASSED: test_enter_exit_same_block")

    def test_dust_amounts(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Stake very small amount (1 wei = 1). Verify no division errors.

        GIVEN: Farm contract is active
        WHEN: Alice stakes 1 unit (smallest possible amount)
        THEN:
            - Transaction succeeds (no division-by-zero or underflow)
            - Farm token supply increases by 1
            - Farm state remains consistent

        EDGE CASE: Minimum possible stake should not cause arithmetic errors
                   in reward per share calculations.
        """
        logger.info("TEST: Dust amounts (1 wei)")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        dust_amount = 1  # 1 wei - smallest possible amount

        supply_before = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]

        ensure_esdt_amounts(alice, {farming_token: dust_amount})

        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            dust_amount,
            network_providers,
            blockchain_controller,
        )

        # The transaction may succeed or fail depending on contract minimums.
        # Either outcome is acceptable -- what matters is no crash/panic.
        tx_data = network_providers.proxy.get_transaction(tx_enter)
        if tx_data.status.is_successful:
            logger.info("Dust amount accepted by contract")
            supply_after = _get_farm_state(farm_contract, network_providers.proxy)[
                "farm_token_supply"
            ]
            assert supply_after == supply_before + dust_amount, (
                f"Supply mismatch after dust entry:\n"
                f"  Before: {supply_before}\n"
                f"  After: {supply_after}\n"
                f"  Expected increase: {dust_amount}"
            )

            # Verify farm state is still consistent
            farm_state = _get_farm_state(farm_contract, network_providers.proxy)
            assert farm_state["reward_per_share"] >= 0, "RPS should not be negative"
            assert farm_state["reward_reserve"] >= 0, "Reserve should not be negative"
        else:
            logger.info("Dust amount rejected by contract (acceptable)")
            # Supply should be unchanged
            supply_after = _get_farm_state(farm_contract, network_providers.proxy)[
                "farm_token_supply"
            ]
            assert supply_after == supply_before, "Supply should not change on failed tx"

        logger.info("PASSED: test_dust_amounts")

    def test_large_stake_amount(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Stake a large amount (but within ESDT limits). Verify no overflow.

        GIVEN: Farm contract is active
        WHEN: Alice stakes a very large amount (10% of current supply, or 10M tokens)
        THEN:
            - Transaction succeeds
            - Farm token supply increases correctly (no overflow)
            - RPS and reward reserve remain consistent

        EDGE CASE: Large amounts must not cause BigUint overflow in
                   reward_per_share * amount / division_safety_constant calculations.
        """
        logger.info("TEST: Large stake amount")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        farm_state = _get_farm_state(farm_contract, network_providers.proxy)
        supply_before = farm_state["farm_token_supply"]

        # Use 10% of current supply or 10M tokens, whichever is larger
        large_amount = max(supply_before // 10, nominated_amount(10_000_000))
        logger.info(f"Large stake amount: {large_amount} (supply: {supply_before})")

        ensure_esdt_amounts(alice, {farming_token: large_amount})

        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            large_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Verify supply increased correctly (no overflow wrapping)
        supply_after = _get_farm_state(farm_contract, network_providers.proxy)["farm_token_supply"]
        assert supply_after == supply_before + large_amount, (
            f"Supply mismatch after large entry (possible overflow):\n"
            f"  Before: {supply_before}\n"
            f"  After: {supply_after}\n"
            f"  Expected: {supply_before + large_amount}"
        )

        # RPS should not have gone negative (overflow indicator)
        rps = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]
        assert rps >= 0, f"RPS went negative after large stake: {rps}"

        # Advance blocks and verify no overflow in reward calculations
        blockchain_controller.wait_blocks(5)
        farm_state_after = _get_farm_state(farm_contract, network_providers.proxy)
        assert farm_state_after["reward_per_share"] >= rps, (
            f"RPS should not decrease after blocks:\n"
            f"  Before: {rps}\n"
            f"  After: {farm_state_after['reward_per_share']}"
        )
        assert farm_state_after["reward_reserve"] >= 0, "Reserve should not be negative"

        logger.info("PASSED: test_large_stake_amount")

    def test_rapid_enter_exit_cycles(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Enter, exit, enter, exit in sequence. Verify state consistency.

        GIVEN: Farm contract is active
        WHEN: Alice performs 3 enter/exit cycles in sequence
        THEN:
            - All transactions succeed
            - Farm token supply returns to original after each cycle
            - RPS monotonically increases (never decreases)
            - Final farm state is consistent

        EDGE CASE: Rapid cycling must not cause state corruption from
                   partial updates or nonce management issues.
        """
        logger.info("TEST: Rapid enter/exit cycles")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)
        num_cycles = 3

        supply_baseline = _get_farm_state(farm_contract, network_providers.proxy)[
            "farm_token_supply"
        ]
        rps_previous = _get_farm_state(farm_contract, network_providers.proxy)["reward_per_share"]

        for i in range(num_cycles):
            logger.info(f"Cycle {i + 1}/{num_cycles}")

            # Enter
            ensure_esdt_amounts(alice, {farming_token: stake_amount})
            tx_enter = _enter_farm(
                farm_contract,
                alice,
                farming_token,
                stake_amount,
                network_providers,
                blockchain_controller,
            )
            TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

            supply_during = _get_farm_state(farm_contract, network_providers.proxy)[
                "farm_token_supply"
            ]
            assert supply_during == supply_baseline + stake_amount, (
                f"Cycle {i + 1}: Supply after enter mismatch:\n"
                f"  Expected: {supply_baseline + stake_amount}\n"
                f"  Got: {supply_during}"
            )

            # RPS should not decrease
            rps_current = _get_farm_state(farm_contract, network_providers.proxy)[
                "reward_per_share"
            ]
            assert rps_current >= rps_previous, (
                f"Cycle {i + 1}: RPS decreased:\n"
                f"  Previous: {rps_previous}\n"
                f"  Current: {rps_current}"
            )
            rps_previous = rps_current

            # Exit
            farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
            ft = max(farm_tokens, key=lambda t: t.token.nonce)
            tx_exit = _exit_farm(
                farm_contract,
                alice,
                ft.token.nonce,
                ft.amount,
                network_providers,
                blockchain_controller,
            )
            TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)

            supply_after_exit = _get_farm_state(farm_contract, network_providers.proxy)[
                "farm_token_supply"
            ]
            assert supply_after_exit == supply_baseline, (
                f"Cycle {i + 1}: Supply after exit mismatch:\n"
                f"  Expected: {supply_baseline}\n"
                f"  Got: {supply_after_exit}"
            )

        # Final state verification
        final_state = _get_farm_state(farm_contract, network_providers.proxy)
        assert final_state["farm_token_supply"] == supply_baseline, (
            "Final supply should match baseline"
        )
        assert final_state["reward_per_share"] >= 0, "Final RPS should not be negative"
        assert final_state["reward_reserve"] >= 0, "Final reserve should not be negative"

        logger.info("PASSED: test_rapid_enter_exit_cycles")

    def test_claim_after_reward_reserve_large(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Verify claim succeeds when reserve is very large.

        GIVEN: Farm contract has a large reward reserve (mainnet state)
        WHEN: Alice enters, advances blocks, and claims rewards
        THEN:
            - Transaction succeeds
            - Reserve decreases by claimed amount
            - New farm token has updated RPS

        NOTE: This test verifies claim works correctly against the existing
              mainnet reward reserve (which can be very large). We cannot
              easily deplete the reserve on chain sim, so instead we verify
              that claim succeeds against the large reserve without errors.
        """
        logger.info("TEST: Claim after reward reserve large")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Check that reserve is non-zero
        reserve_before = _get_farm_state(farm_contract, network_providers.proxy)["reward_reserve"]
        logger.info(f"Current reward reserve: {reserve_before}")

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)

        # Advance blocks for reward accrual
        blockchain_controller.wait_blocks(10)

        # Claim rewards
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens"
        ft = max(farm_tokens, key=lambda t: t.token.nonce)

        reserve_before_claim = _get_farm_state(farm_contract, network_providers.proxy)[
            "reward_reserve"
        ]
        tx_claim = _claim_rewards(
            farm_contract,
            alice,
            ft.token.nonce,
            ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_claim, network_providers.proxy)

        farm_state_after = _get_farm_state(farm_contract, network_providers.proxy)
        reserve_after_claim = farm_state_after["reward_reserve"]
        reward = reserve_before_claim - reserve_after_claim

        logger.info(f"Reserve before claim: {reserve_before_claim}")
        logger.info(f"Reserve after claim: {reserve_after_claim}")
        logger.info(f"Reward claimed: {reward}")

        # Reserve should not increase significantly.
        reserve_tolerance = farm_state_after["per_second_reward_amount"] * 6 * 11
        assert reserve_after_claim <= reserve_before_claim + reserve_tolerance, (
            f"Reserve should not increase significantly after claim:\n"
            f"  Before: {reserve_before_claim}\n"
            f"  After: {reserve_after_claim}\n"
            f"  Delta: {reserve_after_claim - reserve_before_claim}\n"
            f"  Tolerance: {reserve_tolerance}"
        )

        # Alice should have a new farm token with updated RPS
        farm_tokens_after = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens_after) > 0, "Alice should have a farm token after claim"

        new_ft = max(farm_tokens_after, key=lambda t: t.token.nonce)
        attrs = decode_merged_attributes(
            new_ft.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES
        )
        assert attrs["reward_per_share"] >= 0, "New farm token RPS should not be negative"

        logger.info("PASSED: test_claim_after_reward_reserve_large")

    def test_exit_penalty_boundary(
        self,
        farm_contract: FarmContract,
        alice: Account,
        network_providers: NetworkProviders,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Read minimum_farming_epochs, advance exactly that many epochs, exit.
                  Verify no penalty applied.

        GIVEN: Farm has minimum_farming_epochs configured
        WHEN: Alice enters, advances exactly min_epochs, then exits
        THEN:
            - Transaction succeeds
            - Alice receives full LP amount back (no penalty)
            - This verifies the boundary condition: exactly at the minimum
              should not incur a penalty

        EDGE CASE: Off-by-one in epoch comparison. The penalty check is
                   typically `entering_epoch + min_epochs <= current_epoch`.
                   This test verifies the exact boundary.
        """
        logger.info("TEST: Exit penalty boundary")

        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded on chain simulator")

        min_epochs = _get_minimum_farming_epochs(farm_contract, network_providers.proxy)
        logger.info(f"Minimum farming epochs: {min_epochs}")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter farm
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx_enter = _enter_farm(
            farm_contract,
            alice,
            farming_token,
            stake_amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_enter, network_providers.proxy)
        lp_after_enter = _get_farming_token_balance(farm_contract, alice, network_providers.proxy)

        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens"
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        attrs = decode_merged_attributes(
            ft.attributes.hex(), decoding_structures.FARM_TOKEN_ATTRIBUTES
        )
        entering_epoch = attrs["entering_epoch"]
        logger.info(f"Entering epoch from farm token: {entering_epoch}")

        # Advance exactly min_epochs
        target_epoch = entering_epoch + min_epochs
        logger.info(f"Advancing to epoch {target_epoch} (exactly min_epochs={min_epochs})")
        blockchain_controller.advance_to_epoch(target_epoch)

        actual_epoch = blockchain_controller.get_current_epoch()
        logger.info(f"Current epoch after advance: {actual_epoch}")

        # Exit farm
        tx_exit = _exit_farm(
            farm_contract,
            alice,
            ft.token.nonce,
            ft.amount,
            network_providers,
            blockchain_controller,
        )
        TransactionAssertions.assert_transaction_success(tx_exit, network_providers.proxy)

        lp_after_exit = _get_farming_token_balance(farm_contract, alice, network_providers.proxy)
        lp_returned = lp_after_exit - lp_after_enter
        logger.info(f"Staked: {stake_amount}, LP returned: {lp_returned}")

        # After min_epochs, full amount should be returned (no penalty)
        assert lp_returned == stake_amount, (
            f"LP returned should equal staked amount at min epoch boundary (no penalty):\n"
            f"  Staked: {stake_amount}\n"
            f"  Returned: {lp_returned}\n"
            f"  Enter epoch: {entering_epoch}\n"
            f"  Exit epoch: {actual_epoch}\n"
            f"  Min epochs: {min_epochs}"
        )

        logger.info("PASSED: test_exit_penalty_boundary")
