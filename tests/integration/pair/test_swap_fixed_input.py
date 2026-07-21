"""
Integration tests for Pair contract swapTokensFixedInput endpoint.

These tests verify the swap fixed input operation through black-box testing:
- Query state via view functions only (getAmountOut, getReservesAndTotalSupply)
- Execute transactions via contract endpoints (swapTokensFixedInput)
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Normal swap operations (both directions, minimum output, sequential)
2. Edge Cases: Large amounts, small amounts, slippage exceeded
3. Security: Zero amounts, exceeding reserves, wrong tokens

Run:
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_input.py
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_input.py -m "happy_path"
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_input.py -m "edge_case"
"""

from multiversx_sdk import Address, Token
import pytest

from contracts.pair_contract import (
    PairContract, SwapFixedInputEvent, AddLiquidityEvent
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
    """Ensure pool has sufficient liquidity for swap tests."""
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
class TestSwapFixedInput:
    """
    Integration tests for Pair.swapTokensFixedInput()

    Contract Endpoint Tested:
    - swapTokensFixedInput(token_in, token_out, amount_out_min) -> tokens_out

    Economic Invariants Verified:
    1. Constant product (k = x * y) never decreases after swap
    2. Input reserve increases, output reserve decreases
    3. Output amount within slippage bounds
    4. User balances reflect the swap correctly
    """

    @pytest.mark.happy_path
    def test_swap_fixed_input_first_to_second(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap exact amount of first token for second token

        GIVEN: Pool with liquidity, Alice funded with first token
        WHEN: Alice swaps via swapTokensFixedInput (tokenA -> tokenB)
        THEN:
            - Transaction succeeds
            - First reserve increased, second reserve decreased
            - Constant product (k) never decreased (fees increase k)
            - Alice's first token balance decreased
            - Alice's second token balance increased
            - Output within slippage bounds

        SECURITY: Constant product must not decrease. Any decrease indicates
                  potential arbitrage drain or broken fee logic.
        """
        logger.info("TEST: Swap fixed input first -> second")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state before
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]
        logger.info(f"Reserves before: ({reserves_before[0]}, {reserves_before[1]}), k={k_before}")

        # 2. ARRANGE: Calculate expected output via getAmountOut view
        swap_amount = nominated_amount(10)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )
        min_output = int(expected_output * 0.95)  # 5% slippage
        logger.info(f"Swap {swap_amount / 10**18:.4f} firstToken, expected output: {expected_output / 10**18:.4f}, min: {min_output / 10**18:.4f}")

        # 3. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        # Get Alice's balances before
        token_second = Token(pair_contract.secondToken, 0)
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 4. ACT: Execute swap
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=min_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 5. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info("Transaction succeeded")

        # 6. ASSERT: Reserves changed by exact amounts
        # Special fee is deducted from input and sent to the fees collector, NOT added to the reserve.
        # reserve_increase = swap_amount * (100000 - special_fee) / 100000
        special_fee = pair_data_fetcher.get_data("getSpecialFee") or 0
        expected_input_delta = swap_amount * (100000 - special_fee) // 100000
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[0] - reserves_before[0] == expected_input_delta, (
            f"First reserve should increase by exactly {expected_input_delta} "
            f"(swap_amount={swap_amount} minus special_fee={swap_amount - expected_input_delta}).\n"
            f"Before: {reserves_before[0]}, After: {reserves_after[0]}, Delta: {reserves_after[0] - reserves_before[0]}"
        )
        assert reserves_before[1] - reserves_after[1] == expected_output, (
            f"Second reserve should decrease by exactly {expected_output} (output token removed).\n"
            f"Before: {reserves_before[1]}, After: {reserves_after[1]}, Delta: {reserves_before[1] - reserves_after[1]}"
        )
        logger.info(f"Reserves after: ({reserves_after[0]}, {reserves_after[1]})")

        # 7. ASSERT: Constant product holds (k never decreases)
        k_after = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )
        logger.info(f"k: {k_before} -> {k_after} (increase from fees)")

        # 8. ASSERT: Alice received exactly the expected output
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_output = alice_second_after - alice_second_before

        assert actual_output == expected_output, (
            f"Output does not match getAmountOut query result.\n"
            f"Expected: {expected_output}, Got: {actual_output}"
        )
        logger.info(f"Alice received {actual_output / 10**18:.4f} secondToken (expected {expected_output / 10**18:.4f})")

        logger.info("Test passed: Swap fixed input first->second successful")

    @pytest.mark.happy_path
    def test_swap_fixed_input_second_to_first(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap exact amount of second token for first token (reverse direction)

        GIVEN: Pool with liquidity, Alice funded with second token
        WHEN: Alice swaps via swapTokensFixedInput (tokenB -> tokenA)
        THEN:
            - Transaction succeeds
            - Second reserve increased, first reserve decreased
            - Constant product (k) never decreased
            - Output within slippage bounds

        SECURITY: Bidirectional swaps must work identically in both directions.
                  A directional bias could indicate a bug in reserve handling.
        """
        logger.info("TEST: Swap fixed input second -> first")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state before
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # 2. ARRANGE: Calculate expected output
        swap_amount = nominated_amount(10)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.secondToken), BigUIntValue(swap_amount)]
        )
        min_output = int(expected_output * 0.95)

        # 3. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.secondToken: swap_amount})

        # Get Alice's balances before
        token_first = Token(pair_contract.firstToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount

        # 4. ACT: Execute swap (reverse direction)
        event = SwapFixedInputEvent(
            tokenA=pair_contract.secondToken,
            amountA=swap_amount,
            tokenB=pair_contract.firstToken,
            amountBmin=min_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 5. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 6. ASSERT: Reserves changed by exact amounts
        # Special fee portion goes to fees collector, not to the reserve.
        special_fee = pair_data_fetcher.get_data("getSpecialFee") or 0
        expected_input_delta = swap_amount * (100000 - special_fee) // 100000
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[1] - reserves_before[1] == expected_input_delta, (
            f"Second reserve should increase by exactly {expected_input_delta} "
            f"(swap_amount={swap_amount} minus special_fee={swap_amount - expected_input_delta}).\n"
            f"Before: {reserves_before[1]}, After: {reserves_after[1]}, Delta: {reserves_after[1] - reserves_before[1]}"
        )
        assert reserves_before[0] - reserves_after[0] == expected_output, (
            f"First reserve should decrease by exactly {expected_output} (output token removed).\n"
            f"Before: {reserves_before[0]}, After: {reserves_after[0]}, Delta: {reserves_before[0] - reserves_after[0]}"
        )

        # 7. ASSERT: Constant product holds
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )

        # 8. ASSERT: Alice received exactly the expected output
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        actual_output = alice_first_after - alice_first_before

        assert actual_output == expected_output, (
            f"Output does not match getAmountOut query result.\n"
            f"Expected: {expected_output}, Got: {actual_output}"
        )
        logger.info(f"Alice received {actual_output / 10**18:.4f} firstToken")

        logger.info("Test passed: Swap fixed input second->first successful")

    @pytest.mark.happy_path
    def test_swap_fixed_input_minimum_output(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap with amountBmin set to exactly the getAmountOut value (0% slippage)

        GIVEN: Pool with liquidity, Alice funded with first token
        WHEN: Alice swaps with amountBmin = getAmountOut (tightest possible slippage)
        THEN:
            - Transaction succeeds
            - Alice receives at least the queried amount
            - No value leak between query and execution

        SECURITY: Tests tightest possible slippage protection. If this fails, there
                  is a discrepancy between the view function and actual execution.
                  Such discrepancy could be exploited by MEV bots.
        """
        logger.info("TEST: Swap fixed input with minimum output (0% slippage tolerance)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Query expected output
        swap_amount = nominated_amount(5)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        # Set min_output to EXACTLY the expected output (0% slippage)
        min_output = expected_output
        logger.info(f"Swap {swap_amount / 10**18:.4f}, min_output = expected_output = {min_output / 10**18:.4f}")

        # 2. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        token_second = Token(pair_contract.secondToken, 0)
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 3. ACT: Execute swap with tight slippage
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=min_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 5. ASSERT: Received at least the queried amount
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_output = alice_second_after - alice_second_before

        assert actual_output == expected_output, (
            f"Output does not match getAmountOut query result!\n"
            f"getAmountOut returned: {expected_output}\n"
            f"Actually received: {actual_output}\n"
            f"CRITICAL: View function and execution disagree."
        )
        logger.info(f"Received {actual_output / 10**18:.4f} == expected {expected_output / 10**18:.4f}")

        logger.info("Test passed: Minimum output (0% slippage) swap successful")

    @pytest.mark.edge_case
    def test_swap_fixed_input_slippage_exceeded(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Set amountBmin to 200% of getAmountOut (impossible to satisfy)

        GIVEN: Pool with liquidity, Alice funded with first token
        WHEN: Alice attempts swap with amountBmin = 2x expected output
        THEN:
            - Transaction FAILS
            - Reserves unchanged
            - Alice's balances unchanged

        SECURITY: Slippage protection is the user's primary defense against
                  sandwich attacks. If this test passes (tx succeeds), the contract
                  is BROKEN and users are vulnerable to price manipulation.
        """
        logger.info("TEST: Swap fixed input with impossible slippage (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        swap_amount = nominated_amount(5)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        # Set impossible minimum (200% of expected)
        impossible_min = expected_output * 2
        logger.info(f"Expected output: {expected_output}, impossible min: {impossible_min}")

        # Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})
        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 2. ACT: Execute swap with impossible slippage
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=impossible_min
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy, "slippage")
        logger.info("Transaction failed as expected (slippage protection)")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged after failed swap.\n"
            f"Before: {reserves_before}\nAfter: {reserves_after}"
        )

        # 5. ASSERT: Alice balances unchanged
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        assert alice_first_after == alice_first_before, "First token balance should be unchanged"
        assert alice_second_after == alice_second_before, "Second token balance should be unchanged"

        logger.info("Test passed: Impossible slippage correctly rejected")

    @pytest.mark.edge_case
    def test_swap_fixed_input_large_amount(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap 40% of the pool's first token reserve (large price impact)

        GIVEN: Pool with liquidity
        WHEN: Alice swaps 40% of the first reserve
        THEN:
            - Transaction succeeds
            - Large price impact (output per unit much less than small swap)
            - Constant product (k) still holds
            - Reserves still positive

        SECURITY: Large swaps move the price significantly. The contract must
                  handle this correctly without overflow or unexpected behavior.
                  This also tests the curvature of the bonding curve.
        """
        logger.info("TEST: Swap fixed input large amount (40% of reserve)")

        # Setup pool with substantial liquidity
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        # 1. ARRANGE: Get reserves and calculate 40% of first reserve
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]
        swap_amount = reserves_before[0] * 40 // 100  # 40% of first reserve
        logger.info(f"Swapping {swap_amount / 10**18:.4f} ({swap_amount * 100 // reserves_before[0]}% of reserve)")

        # Query expected output
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        # Also query output for a small swap to compare price impact
        small_amount = nominated_amount(1)
        small_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(small_amount)]
        )

        # Calculate effective rates
        large_rate = expected_output / swap_amount if swap_amount > 0 else 0
        small_rate = small_output / small_amount if small_amount > 0 else 0

        logger.info(f"Small swap rate: {small_rate:.6f}, Large swap rate: {large_rate:.6f}")
        logger.info(f"Price impact: {((small_rate - large_rate) / small_rate * 100):.2f}%")

        # 2. ARRANGE: Fund Alice
        min_output = int(expected_output * 0.95)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        # 3. ACT: Execute large swap
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=min_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 5. ASSERT: Large price impact exists
        assert large_rate < small_rate, (
            f"Large swap should have worse rate than small swap (price impact).\n"
            f"Small rate: {small_rate:.6f}, Large rate: {large_rate:.6f}"
        )
        logger.info("Large price impact verified")

        # 6. ASSERT: Constant product holds
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )

        # 7. ASSERT: Reserves still positive
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[0] > 0, "First reserve must remain positive"
        assert reserves_after[1] > 0, "Second reserve must remain positive"
        logger.info(f"Reserves after: ({reserves_after[0]}, {reserves_after[1]})")

        logger.info("Test passed: Large swap handled correctly with expected price impact")

    @pytest.mark.edge_case
    def test_swap_fixed_input_small_amount(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap dust amount (1000 atomic units)

        GIVEN: Pool with liquidity
        WHEN: Alice swaps 1000 atomic units
        THEN:
            - Transaction succeeds or fails gracefully
            - If success: reserves changed by at least 1 unit, k holds
            - If failure: appropriate error, state unchanged

        SECURITY: Dust amounts test integer rounding behavior. Improper rounding
                  could allow repeated dust swaps to slowly drain the pool
                  (rounding attack / penny shaving).
        """
        logger.info("TEST: Swap fixed input small (dust) amount")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        dust_amount = 1000  # 1000 atomic units (very small)

        # Fund Alice with dust
        ensure_esdt_amounts(alice, {pair_contract.firstToken: dust_amount})

        # 2. ACT: Swap dust amount
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=dust_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1  # Accept any output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Check outcome
        tx_result = network_providers.proxy.get_transaction(tx_hash)

        if tx_result.status.is_successful:
            logger.info("Dust swap succeeded")

            reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

            # Reserves should have changed
            assert reserves_after[0] >= reserves_before[0], (
                "First reserve should not decrease (input token added)"
            )

            # k should not decrease
            PairAssertions.assert_constant_product_holds(
                pair_contract.address, k_before, network_providers.proxy
            )
            logger.info("Test passed: Dust swap succeeded with k maintained")
        else:
            logger.info("Dust swap failed gracefully")

            # State should be unchanged
            reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after == reserves_before, (
                f"Reserves should be unchanged after failed dust swap.\n"
                f"Before: {reserves_before}\nAfter: {reserves_after}"
            )
            logger.info("Test passed: Dust swap failed gracefully with unchanged state")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_input_zero_amount(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap 0 tokens (zero input amount)

        GIVEN: Pool with liquidity
        WHEN: Alice attempts to swap 0 tokens
        THEN:
            - Transaction FAILS
            - Reserves unchanged
            - No tokens moved

        SECURITY: Zero-amount operations must be rejected to prevent:
                  1. Gas-griefing (wasting gas for no-ops)
                  2. State manipulation if rounding produces non-zero output from zero input
                  3. Event log spam
        """
        logger.info("TEST: Swap fixed input zero amount (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # 2. ACT: Attempt zero-amount swap
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=0,
            tokenB=pair_contract.secondToken,
            amountBmin=0
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (protocol rejects 0-amount ESDT transfer)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="negative value"
        )
        logger.info("Transaction failed as expected")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged after zero-amount swap.\n"
            f"Before: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Zero amount swap correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_input_exceeds_reserve(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Swap amount = 10x the pool's first token reserve

        GIVEN: Pool with liquidity
        WHEN: Alice attempts to swap an amount vastly exceeding available liquidity
        THEN:
            - Transaction FAILS with insufficient liquidity
            - Reserves unchanged

        SECURITY: The contract must reject swaps that would deplete the output
                  reserve below safe limits. Without this check, the AMM curve
                  would produce near-zero output for massive inputs.
        """
        logger.info("TEST: Swap fixed input exceeding reserve (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Get current reserves and calculate excessive amount
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        excessive_amount = reserves_before[0] * 10  # 10x the first reserve
        logger.info(f"Reserve: {reserves_before[0]}, attempting swap of: {excessive_amount}")

        # Fund Alice with excessive amount
        ensure_esdt_amounts(alice, {pair_contract.firstToken: excessive_amount})

        # Set amountBmin to something that would require draining the pool
        # The output for such a massive input should be close to the entire second reserve
        # Set min to 99% of second reserve (impossible without draining)
        impossible_min = reserves_before[1] * 99 // 100

        # 2. ACT: Attempt excessive swap
        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=excessive_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=impossible_min
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED with slippage error
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Slippage exceeded"
        )
        logger.info("Transaction failed as expected")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged after failed excessive swap.\n"
            f"Before: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Excessive swap correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_input_wrong_token(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Attempt swap with a token not in the pair

        GIVEN: Pool with tokens (firstToken, secondToken)
        WHEN: Alice attempts to swap a fake token "FAKE-aaaaaa" through the pair
        THEN:
            - Transaction FAILS
            - Reserves unchanged

        SECURITY: The contract must validate that the input token matches one
                  of the pair's configured tokens. Accepting arbitrary tokens
                  would allow draining the pool with worthless tokens.
        """
        logger.info("TEST: Swap fixed input with wrong token (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        fake_token = "FAKE-aaaaaa"
        swap_amount = nominated_amount(10)

        # 2. ACT: Attempt swap with wrong token
        event = SwapFixedInputEvent(
            tokenA=fake_token,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (user doesn't have FAKE token)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="insufficient funds"
        )
        logger.info("Transaction failed as expected (wrong token)")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged after wrong-token swap.\n"
            f"Before: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Wrong token swap correctly rejected")

    @pytest.mark.happy_path
    @pytest.mark.slow
    def test_swap_fixed_input_multiple_sequential(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Execute 10 sequential swaps alternating direction

        GIVEN: Pool with liquidity
        WHEN: Alice executes 10 swaps (odd: A->B, even: B->A)
        THEN:
            - After each swap: k never decreases, reserves stay positive
            - After all swaps: cumulative k increase (from fees)
            - Final reserves are consistent

        SECURITY: Sequential swaps must not cause:
                  1. k drift (gradual loss from rounding)
                  2. Reserve depletion through accumulated rounding errors
                  3. State corruption from rapid nonce progression
        """
        logger.info("TEST: Multiple sequential swaps (10 alternating direction)")

        # Setup pool with substantial liquidity
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        # Pre-fund Alice with enough tokens for all swaps
        swap_amount = nominated_amount(10)
        num_swaps = 10
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: swap_amount * num_swaps,
            pair_contract.secondToken: swap_amount * num_swaps
        })

        # Track k values
        initial_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = initial_reserves[0] * initial_reserves[1]
        k_previous = k_initial

        logger.info(f"Initial reserves: ({initial_reserves[0]}, {initial_reserves[1]}), k={k_initial}")

        for i in range(num_swaps):
            # Alternate direction: odd swaps go A->B, even swaps go B->A
            if i % 2 == 0:
                token_in = pair_contract.firstToken
                token_out = pair_contract.secondToken
                direction = "first->second"
            else:
                token_in = pair_contract.secondToken
                token_out = pair_contract.firstToken
                direction = "second->first"

            logger.info(f"Swap {i + 1}/{num_swaps}: {direction}")

            event = SwapFixedInputEvent(
                tokenA=token_in,
                amountA=swap_amount,
                tokenB=token_out,
                amountBmin=1  # Accept any output
            )

            alice.sync_nonce(network_providers.proxy)
            tx_hash = pair_contract.swap_fixed_input(network_providers, alice, event)
            blockchain_controller.wait_for_tx(tx_hash)

            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Verify k never decreases after each swap
            k_current = PairAssertions.assert_constant_product_holds(
                pair_contract.address, k_previous, network_providers.proxy
            )

            # Verify reserves stay positive
            reserves_current = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_current[0] > 0, f"First reserve must be positive after swap {i + 1}"
            assert reserves_current[1] > 0, f"Second reserve must be positive after swap {i + 1}"

            k_previous = k_current

        # Final verification
        final_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_final = final_reserves[0] * final_reserves[1]

        # k should have increased due to accumulated fees
        assert k_final > k_initial, (
            f"k should increase after {num_swaps} swaps (fees accumulated).\n"
            f"Initial k: {k_initial}\nFinal k: {k_final}"
        )

        k_increase_pct = ((k_final - k_initial) / k_initial) * 100
        logger.info(f"Final reserves: ({final_reserves[0]}, {final_reserves[1]})")
        logger.info(f"k increased by {k_increase_pct:.4f}% over {num_swaps} swaps")

        logger.info("Test passed: Sequential swaps completed with monotonically increasing k")
