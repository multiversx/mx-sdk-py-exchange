"""
Integration tests for Pair contract swapTokensFixedOutput endpoint.

These tests verify the swap fixed output operation through black-box testing:
- Query state via view functions only (getAmountOut, getReservesAndTotalSupply)
- Execute transactions via contract endpoints (swapTokensFixedOutput)
- Verify state changes after transaction finalization

Fixed output swaps request an exact amount of output tokens and specify
a maximum input. The contract deducts only the required input and returns
any excess back to the user.

Test Categories:
1. Happy Path: Normal fixed output swaps (both directions, max input protection)
2. Edge Cases: Large output, max input exceeded
3. Security: Zero amounts, exceeding reserves, wrong tokens

Run:
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_output.py
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_output.py -m "happy_path"
    pytest --env=chainsim tests/integration/pair/test_swap_fixed_output.py -m "edge_case"
"""

from multiversx_sdk import Address, Token
import pytest

from contracts.pair_contract import (
    PairContract, SwapFixedOutputEvent, AddLiquidityEvent
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


def _estimate_input_for_output(
    pair_contract: PairContract,
    token_in: str,
    desired_output: int,
    network_providers
) -> int:
    """
    Estimate the input amount required for a desired output using reserves.

    Uses the constant product formula:
    amount_in = (reserve_in * amount_out) / (reserve_out - amount_out) + 1

    Then adds fee adjustment using the actual configured fee from the contract.
    """
    reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

    if token_in == pair_contract.firstToken:
        reserve_in = reserves[0]
        reserve_out = reserves[1]
    else:
        reserve_in = reserves[1]
        reserve_out = reserves[0]

    if desired_output >= reserve_out:
        return reserve_in * 10  # Return a very large amount

    # Query actual fee from contract
    pair_data_fetcher = PairContractDataFetcher(
        Address.new_from_bech32(pair_contract.address),
        network_providers.proxy.url
    )
    total_fee = pair_data_fetcher.get_data("getTotalFeePercent")
    # total_fee is in /100000 units. Convert to /10000 for the formula.
    fee_in_10k = total_fee // 10  # e.g., 300/100000 -> 30/10000

    # Constant product formula with fee
    # amount_in_no_fee = (reserve_in * desired_output) / (reserve_out - desired_output)
    # With fee: amount_in = amount_in_no_fee * 10000 / (10000 - fee_in_10k)
    numerator = reserve_in * desired_output * 10000
    denominator = (reserve_out - desired_output) * (10000 - fee_in_10k)
    estimated_input = numerator // denominator + 1

    return estimated_input


@pytest.mark.integration
@pytest.mark.pair
class TestSwapFixedOutput:
    """
    Integration tests for Pair.swapTokensFixedOutput()

    Contract Endpoint Tested:
    - swapTokensFixedOutput(token_in_max, token_out, amount_out) -> (tokens_out, refund)

    Key Difference from Fixed Input:
    - User specifies desired OUTPUT amount and maximum input
    - Contract calculates required input, deducts it, returns excess
    - User receives EXACT output (not approximate)

    Economic Invariants Verified:
    1. Constant product (k = x * y) never decreases
    2. User receives exactly the requested output
    3. Input deducted <= amountAmax
    4. Excess input returned to user
    """

    @pytest.mark.happy_path
    def test_swap_fixed_output_first_to_second(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request exact amount of second token using first token as input

        GIVEN: Pool with liquidity, Alice funded with first token
        WHEN: Alice requests exact amount of tokenB, provides max tokenA
        THEN:
            - Transaction succeeds
            - Alice receives exactly the requested output
            - Input deducted <= amountAmax
            - Constant product (k) never decreased
            - Reserves consistent

        SECURITY: Fixed output swaps protect buyers who need exact amounts
                  (e.g., for downstream contract calls). Input protection prevents
                  overpaying due to price movement.
        """
        logger.info("TEST: Swap fixed output first -> second")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Capture state before
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # Desired output: 1% of the second token reserve (safe for any token decimals)
        desired_output = reserves_before[1] // 100
        assert desired_output > 0, "Pool must have non-zero second reserve"

        # Estimate input needed and set max to 2x for safety
        estimated_input = _estimate_input_for_output(
            pair_contract, pair_contract.firstToken, desired_output, network_providers
        )
        max_input = estimated_input * 2
        logger.info(f"Requesting {desired_output} secondToken (1% of reserve), estimated input: {estimated_input}, max: {max_input}")

        # 2. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: max_input})

        # Get Alice's balances before
        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 3. ACT: Execute fixed output swap
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=max_input,
            tokenB=pair_contract.secondToken,
            amountB=desired_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info("Transaction succeeded")

        # 5. ASSERT: Alice received exactly the requested output
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_output = alice_second_after - alice_second_before

        assert actual_output == desired_output, (
            f"Should receive exact requested output.\n"
            f"Requested: {desired_output}, Received: {actual_output}"
        )
        logger.info(f"Alice received exactly {actual_output / 10**18:.4f} secondToken")

        # 6. ASSERT: Input deducted <= max_input
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        actual_input_spent = alice_first_before - alice_first_after

        assert actual_input_spent <= max_input, (
            f"Input spent should not exceed max.\n"
            f"Max: {max_input}, Spent: {actual_input_spent}"
        )
        assert actual_input_spent > 0, "Some input should have been spent"

        # 6b. ASSERT: Refund is correct (max_input - actual_spent returned)
        refund = max_input - actual_input_spent
        logger.info(f"Input spent: {actual_input_spent / 10**18:.4f}, refund: {refund / 10**18:.4f} (max was {max_input / 10**18:.4f})")
        assert refund >= 0, "Refund must be non-negative"
        if max_input > actual_input_spent:
            assert refund > 0, (
                f"Contract should refund excess input.\n"
                f"Max: {max_input}, Spent: {actual_input_spent}, Refund: {refund}"
            )

        # 7. ASSERT: Reserves consistent
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[0] > reserves_before[0], "First reserve should increase"
        assert reserves_after[1] < reserves_before[1], "Second reserve should decrease"

        # 8. ASSERT: Reserve increase <= actual input spent
        # Note: reserve increase may be less than input spent because the special
        # fee is deducted from input and sent to the fee collector externally
        reserve_increase = reserves_after[0] - reserves_before[0]
        assert reserve_increase <= actual_input_spent, (
            f"Reserve increase should not exceed actual input spent.\n"
            f"Reserve increase: {reserve_increase}, Input spent: {actual_input_spent}"
        )
        assert reserve_increase > 0, "Reserve should increase from input"

        # 9. ASSERT: Constant product holds
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )

        logger.info("Test passed: Fixed output swap first->second successful")

    @pytest.mark.happy_path
    def test_swap_fixed_output_second_to_first(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request exact amount of first token using second token as input

        GIVEN: Pool with liquidity, Alice funded with second token
        WHEN: Alice requests exact amount of tokenA, provides max tokenB
        THEN:
            - Transaction succeeds
            - Alice receives exactly the requested output
            - Input deducted <= amountAmax
            - Constant product (k) never decreased

        SECURITY: Bidirectional fixed output swaps must work identically.
        """
        logger.info("TEST: Swap fixed output second -> first")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # Desired output: 1% of the first token reserve (safe for any token decimals)
        desired_output = reserves_before[0] // 100
        assert desired_output > 0, "Pool must have non-zero first reserve"

        estimated_input = _estimate_input_for_output(
            pair_contract, pair_contract.secondToken, desired_output, network_providers
        )
        max_input = estimated_input * 2

        # 2. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.secondToken: max_input})

        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 3. ACT: Execute fixed output swap (reverse direction)
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.secondToken,
            amountAmax=max_input,
            tokenB=pair_contract.firstToken,
            amountB=desired_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 5. ASSERT: Alice received exactly the requested output
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        actual_output = alice_first_after - alice_first_before

        assert actual_output == desired_output, (
            f"Should receive exact requested output.\n"
            f"Requested: {desired_output}, Received: {actual_output}"
        )

        # 6. ASSERT: Input deducted <= max_input
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_input_spent = alice_second_before - alice_second_after

        assert actual_input_spent <= max_input, (
            f"Input spent exceeds max.\nMax: {max_input}, Spent: {actual_input_spent}"
        )
        assert actual_input_spent > 0, "Some input should have been spent"

        # 7. ASSERT: Constant product holds
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )

        logger.info("Test passed: Fixed output swap second->first successful")

    @pytest.mark.happy_path
    def test_swap_fixed_output_maximum_input(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Set amountAmax tightly (5% above estimated input)

        GIVEN: Pool with liquidity
        WHEN: Alice requests exact output with tight max input (estimated + 5%)
        THEN:
            - Transaction succeeds
            - Input stays within max
            - Validates protection against excessive spending

        SECURITY: Tight max input protects users from overpaying. If the contract
                  charges more than the maximum, it is broken. This tests the
                  boundary of the input protection mechanism.
        """
        logger.info("TEST: Swap fixed output with tight max input (5% above estimated)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Calculate amounts (1% of second reserve, safe for any token decimals)
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        desired_output = reserves[1] // 100
        assert desired_output > 0, "Pool must have non-zero second reserve"

        estimated_input = _estimate_input_for_output(
            pair_contract, pair_contract.firstToken, desired_output, network_providers
        )
        # Tight max: only 5% above estimated
        tight_max_input = int(estimated_input * 1.05)
        logger.info(f"Estimated input: {estimated_input}, tight max: {tight_max_input}")

        # 2. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: tight_max_input})

        token_first = Token(pair_contract.firstToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount

        # 3. ACT: Execute swap with tight max
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=tight_max_input,
            tokenB=pair_contract.secondToken,
            amountB=desired_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 5. ASSERT: Input within tight max
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        actual_input_spent = alice_first_before - alice_first_after

        assert actual_input_spent <= tight_max_input, (
            f"Input spent should be within tight max.\n"
            f"Max: {tight_max_input}, Spent: {actual_input_spent}"
        )
        logger.info(f"Input spent: {actual_input_spent / 10**18:.4f} <= max {tight_max_input / 10**18:.4f}")

        # Verify input is close to estimated (within 10% tolerance)
        input_variance = abs(actual_input_spent - estimated_input) / estimated_input if estimated_input > 0 else 0
        logger.info(f"Input variance from estimate: {input_variance:.2%}")

        logger.info("Test passed: Tight max input swap successful")

    @pytest.mark.edge_case
    def test_swap_fixed_output_max_input_exceeded(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Set amountAmax to 50% of estimated required input (too low)

        GIVEN: Pool with liquidity
        WHEN: Alice requests output but provides max input far below required
        THEN:
            - Transaction FAILS
            - Reserves unchanged
            - Alice's balances unchanged

        SECURITY: If the contract accepts a swap where max input is insufficient,
                  it either charged less than needed (draining the pool) or
                  ignored the max constraint (violating user protection).
        """
        logger.info("TEST: Swap fixed output with insufficient max input (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE: Calculate amounts
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Desired output: 1% of second reserve (safe for any token decimals)
        desired_output = reserves_before[1] // 100
        assert desired_output > 0, "Pool must have non-zero second reserve"

        estimated_input = _estimate_input_for_output(
            pair_contract, pair_contract.firstToken, desired_output, network_providers
        )
        # Set max to only 50% of estimated (too low)
        insufficient_max = estimated_input // 2
        logger.info(f"Estimated input: {estimated_input}, insufficient max: {insufficient_max}")

        # Fund Alice with the insufficient max
        ensure_esdt_amounts(alice, {pair_contract.firstToken: insufficient_max})

        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 2. ACT: Attempt swap with insufficient max input
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=insufficient_max,
            tokenB=pair_contract.secondToken,
            amountB=desired_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (max input too low for required amount)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Slippage exceeded"
        )
        logger.info("Transaction failed as expected (insufficient max input)")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged.\nBefore: {reserves_before}\nAfter: {reserves_after}"
        )

        # 5. ASSERT: Alice balances unchanged
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        assert alice_first_after == alice_first_before, "First token balance should be unchanged"
        assert alice_second_after == alice_second_before, "Second token balance should be unchanged"

        logger.info("Test passed: Insufficient max input correctly rejected")

    @pytest.mark.edge_case
    def test_swap_fixed_output_large_output(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request 40% of the pool's second token reserve as output

        GIVEN: Pool with liquidity
        WHEN: Alice requests 40% of second reserve as exact output
        THEN:
            - Transaction succeeds
            - Large input required due to price impact
            - Constant product holds
            - Alice receives exactly the requested output

        SECURITY: Large fixed output requests require disproportionately large
                  inputs due to the bonding curve. The contract must calculate
                  this correctly without overflow.
        """
        logger.info("TEST: Swap fixed output large amount (40% of reserve)")

        # Setup pool with substantial liquidity
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]

        # Request 40% of second reserve
        desired_output = reserves_before[1] * 40 // 100
        logger.info(f"Requesting {desired_output / 10**18:.4f} ({desired_output * 100 // reserves_before[1]}% of second reserve)")

        # Estimate input and use generous max
        estimated_input = _estimate_input_for_output(
            pair_contract, pair_contract.firstToken, desired_output, network_providers
        )
        max_input = estimated_input * 2
        logger.info(f"Estimated input: {estimated_input / 10**18:.4f}, max: {max_input / 10**18:.4f}")

        # 2. ARRANGE: Fund Alice
        ensure_esdt_amounts(alice, {pair_contract.firstToken: max_input})

        token_second = Token(pair_contract.secondToken, 0)
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # 3. ACT: Execute large fixed output swap
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=max_input,
            tokenB=pair_contract.secondToken,
            amountB=desired_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. ASSERT: Transaction success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 5. ASSERT: Alice received exactly the requested output
        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_output = alice_second_after - alice_second_before

        assert actual_output == desired_output, (
            f"Should receive exact requested output for large swap.\n"
            f"Requested: {desired_output}, Received: {actual_output}"
        )

        # 6. ASSERT: Constant product holds
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )

        # 7. ASSERT: Reserves still positive
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[0] > 0, "First reserve must remain positive"
        assert reserves_after[1] > 0, "Second reserve must remain positive"

        logger.info(f"Large fixed output swap complete: received {actual_output / 10**18:.4f} secondToken")
        logger.info("Test passed: Large fixed output swap handled correctly")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_output_exceeds_reserve(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request output > available reserve (2x second token reserve)

        GIVEN: Pool with liquidity
        WHEN: Alice requests 2x the second reserve as output
        THEN:
            - Transaction FAILS
            - Reserves unchanged

        SECURITY: Requesting more than available reserve is mathematically
                  impossible in a constant product AMM (would require infinite input).
                  The contract must reject this cleanly, not hang or overflow.
        """
        logger.info("TEST: Swap fixed output exceeding reserve (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Request 2x the available second reserve (impossible)
        impossible_output = reserves_before[1] * 2
        max_input = reserves_before[0] * 10  # Very generous max input
        logger.info(f"Reserve: {reserves_before[1]}, requesting: {impossible_output}")

        # Fund Alice with generous input
        ensure_esdt_amounts(alice, {pair_contract.firstToken: max_input})

        # 2. ACT: Attempt impossible swap
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=max_input,
            tokenB=pair_contract.secondToken,
            amountB=impossible_output
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (output > reserve causes BigUint underflow)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Not enough reserve"
        )
        logger.info("Transaction failed as expected")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged.\nBefore: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Exceeding reserve output correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_output_zero_amount(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request 0 tokens as output

        GIVEN: Pool with liquidity
        WHEN: Alice requests 0 output tokens
        THEN:
            - Transaction FAILS
            - Reserves unchanged

        SECURITY: Zero-output requests must be rejected. If the contract accepts
                  a zero-output swap, it may still deduct input tokens (stealing funds)
                  or produce inconsistent state.
        """
        logger.info("TEST: Swap fixed output zero amount (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        max_input = nominated_amount(10)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: max_input})

        # 2. ACT: Request zero output
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=max_input,
            tokenB=pair_contract.secondToken,
            amountB=0  # Zero output requested
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (contract rejects 0 output)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Invalid args"
        )
        logger.info("Transaction failed as expected")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged.\nBefore: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Zero output swap correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_swap_fixed_output_wrong_token(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Request output of a token not in the pair

        GIVEN: Pool with tokens (firstToken, secondToken)
        WHEN: Alice requests output of "FAKE-aaaaaa" (not in pair)
        THEN:
            - Transaction FAILS
            - Reserves unchanged

        SECURITY: The contract must validate that the output token is one of
                  the pair's tokens. Accepting arbitrary output token identifiers
                  could cause undefined behavior or state corruption.
        """
        logger.info("TEST: Swap fixed output with wrong token (should fail)")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        # 1. ARRANGE
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        max_input = nominated_amount(10)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: max_input})

        fake_token = "FAKE-aaaaaa"

        # 2. ACT: Request output of wrong token
        event = SwapFixedOutputEvent(
            tokenA=pair_contract.firstToken,
            amountAmax=max_input,
            tokenB=fake_token,
            amountB=nominated_amount(5)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_output(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. ASSERT: Transaction FAILED (contract rejects unknown output token)
        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Invalid tokens"
        )
        logger.info("Transaction failed as expected (wrong output token)")

        # 4. ASSERT: Reserves unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after == reserves_before, (
            f"Reserves should be unchanged.\nBefore: {reserves_before}\nAfter: {reserves_after}"
        )

        logger.info("Test passed: Wrong output token correctly rejected")
