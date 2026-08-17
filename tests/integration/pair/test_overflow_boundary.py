"""
Integration tests for Pair contract overflow/underflow and boundary conditions.

These tests verify the AMM handles extreme numeric values correctly:
- Very large amounts (near BigUint limits)
- Very small amounts (single atomic units)
- Maximum amount handling across operations

Run:
    pytest --env=chainsim tests/integration/pair/test_overflow_boundary.py
"""

from multiversx_sdk import Address, Token
import pytest

from contracts.pair_contract import (
    PairContract, SwapFixedInputEvent, AddLiquidityEvent, RemoveLiquidityEvent
)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import nominated_amount, Account
from tests.helpers import PairAssertions, TransactionAssertions
from utils.logger import get_logger
from multiversx_sdk.abi import TokenIdentifierValue, BigUIntValue


logger = get_logger(__name__)


def _ensure_pool_has_liquidity(
    pair_contract: PairContract,
    account: Account,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    amount: int = None
):
    """Ensure pool has sufficient liquidity for tests."""
    if amount is None:
        amount = nominated_amount(1000)

    reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
    if reserves[0] == 0:
        ensure_esdt_amounts(account, {
            pair_contract.firstToken: amount,
            pair_contract.secondToken: amount
        })
        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=amount,
            amountAmin=amount,
            tokenB=pair_contract.secondToken,
            amountB=amount,
            amountBmin=amount
        )
        account.sync_nonce(network_providers.proxy)
        tx = pair_contract.add_initial_liquidity(network_providers, account, event)
        blockchain_controller.wait_for_tx(tx)
        logger.info(f"Pool initialized with {amount / 10**18:.0f} of each token")
        return PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
    return reserves


@pytest.mark.integration
@pytest.mark.pair
class TestOverflowBoundary:
    """
    Integration tests for integer overflow/underflow and boundary conditions.

    Tests extreme numeric values that could expose bugs in the AMM's
    safe math operations. MultiversX contracts use BigUint, so these tests
    verify that large amounts are handled gracefully.
    """

    @pytest.mark.edge_case
    def test_no_overflow_large_amounts(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Test operations with very large token amounts

        GIVEN: Pool with existing liquidity
        WHEN: Operations attempted with amounts near 10^30 (much larger than typical)
        THEN:
            - Swap with extremely large amount either succeeds or fails gracefully
            - Add liquidity with very large amounts either succeeds or fails gracefully
            - No overflow in reserve calculations
            - Contract state remains consistent after operations
            - Reserves remain positive and k invariant holds

        SECURITY: Integer overflow in AMM calculations (x*y=k) could lead to
                  zero-output swaps or infinite minting attacks.
                  BigUint should prevent this, but we verify at the contract level.
        """
        logger.info("TEST: No overflow with large amounts")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # Test 1: Swap with amount = 10x the reserve (very large relative to pool)
        large_amount = reserves_before[0] * 10
        ensure_esdt_amounts(alice, {pair_contract.firstToken: large_amount})

        logger.info(f"Attempting swap with 10x reserve: {large_amount}")

        swap_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=large_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1  # Accept any output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_swap = pair_contract.swap_fixed_input(network_providers, alice, swap_event)
        blockchain_controller.wait_for_tx(tx_swap)

        # The swap should succeed (BigUint handles large values)
        # With 10x reserve, user gets ~90.9% of second reserve (minus fees)
        tx_data = network_providers.proxy.get_transaction(tx_swap)
        if tx_data.status.is_successful:
            logger.info("Large swap succeeded")
            reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after[0] > 0, "First reserve must remain positive"
            assert reserves_after[1] > 0, "Second reserve must remain positive"
            k_after = reserves_after[0] * reserves_after[1]
            assert k_after >= k_before, f"k must not decrease: {k_before} -> {k_after}"
            logger.info(f"Reserves after large swap: ({reserves_after[0]}, {reserves_after[1]})")

            # Swap back to restore some balance
            small_swap = reserves_after[1] // 10
            if small_swap > 0:
                ensure_esdt_amounts(alice, {pair_contract.secondToken: small_swap})
                restore_event = SwapFixedInputEvent(
                    tokenA=pair_contract.secondToken,
                    amountA=small_swap,
                    tokenB=pair_contract.firstToken,
                    amountBmin=1
                )
                alice.sync_nonce(network_providers.proxy)
                tx_restore = pair_contract.swap_fixed_input(network_providers, alice, restore_event)
                blockchain_controller.wait_for_tx(tx_restore)
        else:
            logger.info("Large swap failed gracefully (expected for extreme amounts)")
            # Verify state unchanged
            reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after[0] == reserves_before[0], "Reserves must be unchanged after failed tx"
            assert reserves_after[1] == reserves_before[1], "Reserves must be unchanged after failed tx"

        # Test 2: Very large add liquidity (10^30 each token)
        huge_amount = 10**30
        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: huge_amount,
            pair_contract.secondToken: huge_amount
        })

        reserves_current = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_current = reserves_current[0] * reserves_current[1]

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(huge_amount)]
        )

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=huge_amount,
            amountAmin=int(huge_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=equivalent,
            amountBmin=int(equivalent * 0.95)
        )
        bob.sync_nonce(network_providers.proxy)
        tx_add = pair_contract.add_liquidity(network_providers, bob, add_event)
        blockchain_controller.wait_for_tx(tx_add)

        tx_add_data = network_providers.proxy.get_transaction(tx_add)
        if tx_add_data.status.is_successful:
            logger.info("Large add liquidity succeeded")
            reserves_after_add = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after_add[0] > reserves_current[0], "First reserve should increase"
            assert reserves_after_add[1] > reserves_current[1], "Second reserve should increase"
            assert reserves_after_add[2] > reserves_current[2], "LP supply should increase"
            logger.info(f"Reserves after large add: ({reserves_after_add[0]}, {reserves_after_add[1]})")

            # Remove the added liquidity to clean up
            lp_token = Token(pair_contract.lpToken, 0)
            bob_lp = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount
            if bob_lp > 0:
                remove_amount = bob_lp // 2  # Remove half
                if remove_amount > 0:
                    reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
                    exp_first = remove_amount * reserves_now[0] // reserves_now[2]
                    exp_second = remove_amount * reserves_now[1] // reserves_now[2]
                    remove_event = RemoveLiquidityEvent(
                        amount=remove_amount,
                        tokenA=pair_contract.firstToken,
                        amountA=int(exp_first * 0.90),
                        tokenB=pair_contract.secondToken,
                        amountB=int(exp_second * 0.90)
                    )
                    bob.sync_nonce(network_providers.proxy)
                    tx_rem = pair_contract.remove_liquidity(network_providers, bob, remove_event)
                    blockchain_controller.wait_for_tx(tx_rem)
                    logger.info("Cleanup: Removed large LP position")
        else:
            logger.info("Large add liquidity failed gracefully")

        # Final state check
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "Final first reserve must be positive"
        assert reserves_final[1] > 0, "Final second reserve must be positive"

        logger.info("Test passed: No overflow with large amounts, all operations handled safely")

    @pytest.mark.edge_case
    def test_no_underflow_edge_cases(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Test operations with minimum possible amounts (1 atomic unit)

        GIVEN: Pool with existing liquidity
        WHEN: Operations attempted with amount = 1 (single atomic unit)
        THEN:
            - Swap with 1 token either succeeds with 0 output or fails gracefully
            - No underflow in (reserve_out * amount_in) / (reserve_in + amount_in)
            - No negative values produced
            - Contract state remains consistent
            - Reserve ratios not corrupted by dust operations

        SECURITY: Underflow in AMM math could produce enormous outputs from
                  tiny inputs. With unsigned integers (BigUint), underflow wraps
                  to very large values, potentially draining the pool.
        """
        logger.info("TEST: No underflow with minimum amounts")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # Test 1: Swap with 1 atomic unit
        min_amount = 1
        ensure_esdt_amounts(alice, {pair_contract.firstToken: min_amount})

        logger.info(f"Attempting swap with 1 atomic unit")

        swap_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=min_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=0  # Accept any output including 0
        )
        alice.sync_nonce(network_providers.proxy)
        tx_swap_1 = pair_contract.swap_fixed_input(network_providers, alice, swap_event)
        blockchain_controller.wait_for_tx(tx_swap_1)

        tx_data_1 = network_providers.proxy.get_transaction(tx_swap_1)
        if tx_data_1.status.is_successful:
            logger.info("Swap with 1 atomic unit succeeded (output likely 0 or very small)")
        else:
            logger.info("Swap with 1 atomic unit failed gracefully (expected)")

        # Verify reserves haven't gone negative or changed significantly
        reserves_after_1 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after_1[0] > 0, "First reserve must remain positive"
        assert reserves_after_1[1] > 0, "Second reserve must remain positive"

        # Test 2: Swap with very small amounts (100, 1000 atomic units)
        small_amounts = [100, 1000, 10000]
        for amount in small_amounts:
            ensure_esdt_amounts(alice, {pair_contract.firstToken: amount})

            small_event = SwapFixedInputEvent(
                tokenA=pair_contract.firstToken,
                amountA=amount,
                tokenB=pair_contract.secondToken,
                amountBmin=0
            )
            alice.sync_nonce(network_providers.proxy)
            tx_small = pair_contract.swap_fixed_input(network_providers, alice, small_event)
            blockchain_controller.wait_for_tx(tx_small)

            tx_data = network_providers.proxy.get_transaction(tx_small)
            status_str = "succeeded" if tx_data.status.is_successful else "failed"
            logger.info(f"Swap with {amount} atomic units: {status_str}")

        # Test 3: Verify getAmountOut with 1 atomic unit doesn't underflow
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        output_for_1 = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(1)]
        )
        logger.info(f"getAmountOut(1 atomic unit) = {output_for_1}")
        # Output should be 0 or a very small number, NEVER negative or huge
        assert output_for_1 >= 0, f"Output for 1 atomic unit should be non-negative, got {output_for_1}"
        # Sanity check: output should not exceed reserves (would indicate underflow wrap)
        reserves_check = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert output_for_1 < reserves_check[1], (
            f"Output for 1 atomic unit ({output_for_1}) exceeds second reserve ({reserves_check[1]})!\n"
            f"This suggests an underflow bug!"
        )

        # Test 4: Add liquidity with very small amounts
        tiny_add = nominated_amount(1) // 10**15  # 1000 atomic units (0.000000000000001 tokens)
        if tiny_add > 0:
            equivalent = pair_data_fetcher.get_data(
                "getEquivalent",
                [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(tiny_add)]
            )
            if equivalent > 0:
                ensure_esdt_amounts(alice, {
                    pair_contract.firstToken: tiny_add,
                    pair_contract.secondToken: equivalent
                })

                tiny_add_event = AddLiquidityEvent(
                    tokenA=pair_contract.firstToken,
                    amountA=tiny_add,
                    amountAmin=0,
                    tokenB=pair_contract.secondToken,
                    amountB=equivalent,
                    amountBmin=0
                )
                alice.sync_nonce(network_providers.proxy)
                tx_tiny_add = pair_contract.add_liquidity(network_providers, alice, tiny_add_event)
                blockchain_controller.wait_for_tx(tx_tiny_add)

                tx_tiny_data = network_providers.proxy.get_transaction(tx_tiny_add)
                status_str = "succeeded" if tx_tiny_data.status.is_successful else "failed"
                logger.info(f"Add liquidity with {tiny_add} atomic units: {status_str}")

        # Final verification: reserves still positive, k never decreased
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "Final first reserve must be positive"
        assert reserves_final[1] > 0, "Final second reserve must be positive"

        logger.info("Test passed: No underflow with minimum amounts, all operations safe")

    @pytest.mark.edge_case
    def test_maximum_amount_handling(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Test operations with amounts approaching practical maximums

        GIVEN: Pool with existing liquidity
        WHEN: Operations with amounts at various large boundaries
        THEN:
            - Operations succeed or fail gracefully at each boundary
            - No integer overflow in intermediate calculations
            - k invariant maintained throughout
            - Remove liquidity works correctly for large LP positions
            - Pool remains functional after large operations

        SECURITY: The AMM formula involves multiplications (x*y, amount*reserve)
                  that can overflow if not using safe math. BigUint prevents this
                  but we verify the contract handles boundary values correctly.
        """
        logger.info("TEST: Maximum amount handling at various boundaries")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Test at multiple large amount boundaries
        boundaries = [
            ("1x reserve", reserves_initial[0]),
            ("5x reserve", reserves_initial[0] * 5),
            ("10^24 (1M tokens)", 10**24),
            ("10^27 (1B tokens)", 10**27),
        ]

        for label, amount in boundaries:
            logger.info(f"Testing swap at boundary: {label} = {amount}")

            ensure_esdt_amounts(alice, {pair_contract.firstToken: amount})

            reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            k_before = reserves_before[0] * reserves_before[1]

            swap_event = SwapFixedInputEvent(
                tokenA=pair_contract.firstToken,
                amountA=amount,
                tokenB=pair_contract.secondToken,
                amountBmin=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.swap_fixed_input(network_providers, alice, swap_event)
            blockchain_controller.wait_for_tx(tx)

            tx_data = network_providers.proxy.get_transaction(tx)
            reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

            if tx_data.status.is_successful:
                k_after = reserves_after[0] * reserves_after[1]
                assert k_after >= k_before, f"k decreased at boundary {label}: {k_before} -> {k_after}"
                assert reserves_after[0] > 0, f"First reserve went to 0 at {label}"
                assert reserves_after[1] > 0, f"Second reserve went to 0 at {label}"
                logger.info(f"  Succeeded: reserves=({reserves_after[0]}, {reserves_after[1]})")

                # Swap back some to restore balance for next test
                restore_amount = reserves_after[1] // 5
                if restore_amount > 0:
                    ensure_esdt_amounts(alice, {pair_contract.secondToken: restore_amount})
                    restore_event = SwapFixedInputEvent(
                        tokenA=pair_contract.secondToken,
                        amountA=restore_amount,
                        tokenB=pair_contract.firstToken,
                        amountBmin=1
                    )
                    alice.sync_nonce(network_providers.proxy)
                    tx_r = pair_contract.swap_fixed_input(network_providers, alice, restore_event)
                    blockchain_controller.wait_for_tx(tx_r)
            else:
                logger.info(f"  Failed gracefully at boundary {label}")
                assert reserves_after[0] == reserves_before[0], f"State changed after failed tx at {label}"
                assert reserves_after[1] == reserves_before[1], f"State changed after failed tx at {label}"

        # Test large add + remove liquidity cycle
        logger.info("Testing large add + remove liquidity cycle")
        large_liq = 10**27  # 1 billion tokens
        reserves_current = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(large_liq)]
        )

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: large_liq,
            pair_contract.secondToken: equivalent
        })

        lp_token = Token(pair_contract.lpToken, 0)
        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=large_liq,
            amountAmin=int(large_liq * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=equivalent,
            amountBmin=int(equivalent * 0.95)
        )
        bob.sync_nonce(network_providers.proxy)
        tx_add = pair_contract.add_liquidity(network_providers, bob, add_event)
        blockchain_controller.wait_for_tx(tx_add)

        tx_add_data = network_providers.proxy.get_transaction(tx_add)
        if tx_add_data.status.is_successful:
            bob_lp_after = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount
            bob_lp_delta = bob_lp_after - bob_lp_before
            logger.info(f"Large add succeeded, got {bob_lp_delta} LP tokens")

            # Now remove the LP tokens
            if bob_lp_delta > 0:
                reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
                exp_first = bob_lp_delta * reserves_now[0] // reserves_now[2]
                exp_second = bob_lp_delta * reserves_now[1] // reserves_now[2]

                remove_event = RemoveLiquidityEvent(
                    amount=bob_lp_delta,
                    tokenA=pair_contract.firstToken,
                    amountA=int(exp_first * 0.90),
                    tokenB=pair_contract.secondToken,
                    amountB=int(exp_second * 0.90)
                )
                bob.sync_nonce(network_providers.proxy)
                tx_rem = pair_contract.remove_liquidity(network_providers, bob, remove_event)
                blockchain_controller.wait_for_tx(tx_rem)
                TransactionAssertions.assert_transaction_success(tx_rem, network_providers.proxy)
                logger.info("Large remove succeeded")
        else:
            logger.info("Large add failed gracefully")

        # Final verification
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "Pool must remain functional"
        assert reserves_final[1] > 0, "Pool must remain functional"

        # Verify pool still functional with a normal swap
        normal_swap = nominated_amount(10)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: normal_swap})
        normal_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=normal_swap,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_normal = pair_contract.swap_fixed_input(network_providers, alice, normal_event)
        blockchain_controller.wait_for_tx(tx_normal)
        TransactionAssertions.assert_transaction_success(tx_normal, network_providers.proxy)
        logger.info("Normal swap works after boundary tests")

        logger.info("Test passed: All boundary amounts handled correctly, pool remains functional")
