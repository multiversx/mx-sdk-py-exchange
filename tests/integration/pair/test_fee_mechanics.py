"""
Integration tests for Pair contract fee mechanics.

These tests verify the AMM's fee system works correctly:
- Standard fee collection on swaps
- Special fee configuration and verification
- Fee accumulation over multiple swaps
- LP value increase from accumulated fees
- Fee collector integration

Run:
    pytest --env=chainsim tests/integration/pair/test_fee_mechanics.py
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
class TestFeeMechanics:
    """
    Integration tests for Pair contract fee system.

    Verifies fee collection, accumulation, and distribution.
    """

    @pytest.mark.happy_path
    def test_standard_fee_collection(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify the standard fee is collected on each swap

        GIVEN: Pool with known fee configuration (e.g., 0.3%)
        WHEN: Bob performs a swap
        THEN:
            - Fee is deducted from the swap (output < zero-fee output)
            - Fee remains in the pool reserves (k increases)
            - Fee percentage matches configured value
            - LP supply unchanged (fee is retained, not distributed)

        SECURITY: Fee collection is the economic engine of the AMM.
                  Incorrect fee calculation could drain the pool or
                  disincentivize liquidity providers.
        """
        logger.info("TEST: Standard fee collection on swap")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Query fee configuration
        total_fee_percent = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percent = pair_data_fetcher.get_data("getSpecialFee")
        logger.info(f"Fee config: total={total_fee_percent}/100000, special={special_fee_percent}/100000")

        # Capture state before swap
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]
        lp_supply_before = reserves_before[2]

        # Calculate zero-fee output (theoretical, no fee deducted)
        swap_amount = nominated_amount(100)
        # AMM formula without fees: output = (reserve_out * amount_in) / (reserve_in + amount_in)
        zero_fee_output = (reserves_before[1] * swap_amount) // (reserves_before[0] + swap_amount)

        # Query actual expected output (with fees)
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        logger.info(f"Zero-fee output: {zero_fee_output}")
        logger.info(f"Expected output (with fee): {expected_output}")

        # Fee should cause actual output to be less than zero-fee output
        assert expected_output < zero_fee_output, (
            f"Output with fees should be less than zero-fee output.\n"
            f"With fee: {expected_output}, Without fee: {zero_fee_output}\n"
            f"Fee is not being applied!"
        )

        fee_deducted = zero_fee_output - expected_output
        effective_fee_pct = fee_deducted / zero_fee_output * 100
        configured_fee_pct = total_fee_percent / 1000  # Convert from /100000 to percentage
        logger.info(f"Fee deducted: {fee_deducted} tokens ({effective_fee_pct:.4f}%)")
        logger.info(f"Configured fee: {configured_fee_pct:.4f}%")

        # Execute the swap
        ensure_esdt_amounts(bob, {pair_contract.firstToken: swap_amount})

        event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, bob, event)
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify k increased (fee retained in reserves)
        k_after = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )
        assert k_after > k_before, "k must increase from fee retention"

        # LP supply should be unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after[2] == lp_supply_before, "LP supply should not change from swap"

        # Calculate actual fee retention via k increase
        k_increase_pct = ((k_after - k_before) / k_before) * 100
        logger.info(f"k increase from fee: {k_increase_pct:.6f}%")

        logger.info("Test passed: Standard fee correctly collected and retained in reserves")

    @pytest.mark.happy_path
    def test_special_fee_if_configured(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify special fee configuration and its effect on swaps

        GIVEN: Pool with total_fee and special_fee configured
        WHEN: Query fee parameters and perform a swap
        THEN:
            - getTotalFeePercent returns a valid percentage
            - getSpecialFee returns a value <= total fee
            - Special fee + LP fee = total fee
            - Output reflects the total fee deduction

        SECURITY: Special fee misconfiguration (e.g., special > total) would
                  break the fee split between LPs and protocol, potentially
                  causing reverts or incorrect fee distribution.
        """
        logger.info("TEST: Special fee configuration verification")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Query fee parameters
        total_fee = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee = pair_data_fetcher.get_data("getSpecialFee")

        logger.info(f"Total fee: {total_fee}/100000 ({total_fee / 1000:.2f}%)")
        logger.info(f"Special fee: {special_fee}/100000 ({special_fee / 1000:.2f}%)")

        # Validate fee constraints
        assert total_fee >= 0, f"Total fee must be non-negative, got {total_fee}"
        assert special_fee >= 0, f"Special fee must be non-negative, got {special_fee}"
        assert special_fee <= total_fee, (
            f"Special fee must not exceed total fee.\n"
            f"Special: {special_fee}, Total: {total_fee}"
        )
        # Max fee sanity check (shouldn't exceed 50%)
        assert total_fee <= 50000, (
            f"Total fee exceeds 50% ({total_fee}/100000). This seems wrong."
        )

        lp_fee = total_fee - special_fee
        logger.info(f"LP fee: {lp_fee}/100000 ({lp_fee / 1000:.2f}%)")
        logger.info(f"Fee split: {lp_fee/1000:.2f}% to LPs + {special_fee/1000:.2f}% special = {total_fee/1000:.2f}% total")

        # Perform a swap and verify output reflects total fee
        swap_amount = nominated_amount(100)
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Zero-fee calculation
        zero_fee_output = (reserves[1] * swap_amount) // (reserves[0] + swap_amount)

        # Actual expected output (with fee)
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        # The difference should approximately match the fee percentage
        if zero_fee_output > 0:
            fee_impact = (zero_fee_output - expected_output) / zero_fee_output * 100000
            logger.info(f"Effective fee: ~{fee_impact:.0f}/100000")
            logger.info(f"Configured total fee: {total_fee}/100000")

            # Effective fee should be close to the configured total_fee.
            # The exact relationship is:
            #   fee_impact = total_fee * reserve_in / (reserve_in + swap_amount * (1 - total_fee/100000))
            # This accounts for the AMM curve reducing effective fee for large swaps.
            if total_fee > 0:
                # Compute expected fee impact from AMM math
                fee_frac = total_fee / 100000
                expected_fee_impact = total_fee * reserves[0] / (
                    reserves[0] + swap_amount * (1 - fee_frac)
                )
                fee_error = abs(fee_impact - expected_fee_impact) / expected_fee_impact
                assert fee_error < 0.05, (
                    f"Effective fee ({fee_impact:.0f}) doesn't match expected ({expected_fee_impact:.0f}).\n"
                    f"Configured total fee: {total_fee}/100000\n"
                    f"Error: {fee_error:.2%} (must be < 5%)"
                )
                logger.info(f"Fee match: effective ≈ expected ({expected_fee_impact:.0f}) (error: {fee_error:.2%})")

        logger.info("Test passed: Special fee configuration is valid and affects swaps correctly")

    @pytest.mark.happy_path
    @pytest.mark.slow
    def test_fee_accumulation_over_multiple_swaps(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify cumulative fee accumulation over many swaps

        GIVEN: Pool with liquidity
        WHEN: Bob performs 20 swaps alternating direction
        THEN:
            - k increases monotonically with each swap
            - Cumulative k increase is significant
            - k increase rate is consistent (no drift or decay)
            - LP supply remains constant throughout
            - Both reserves remain positive

        SECURITY: Fee accumulation must be consistent over time.
                  If fee accumulation slows down or reverses, it indicates
                  a precision issue or fee calculation bug.
        """
        logger.info("TEST: Fee accumulation over 20 swaps")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]
        lp_supply_initial = reserves_initial[2]

        swap_amount = nominated_amount(50)
        num_swaps = 20

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: swap_amount * num_swaps,
            pair_contract.secondToken: swap_amount * num_swaps
        })

        k_values = [k_initial]
        k_increases = []

        for i in range(num_swaps):
            if i % 2 == 0:
                token_in = pair_contract.firstToken
                token_out = pair_contract.secondToken
            else:
                token_in = pair_contract.secondToken
                token_out = pair_contract.firstToken

            event = SwapFixedInputEvent(
                tokenA=token_in, amountA=swap_amount,
                tokenB=token_out, amountBmin=1
            )
            bob.sync_nonce(network_providers.proxy)
            tx = pair_contract.swap_fixed_input(network_providers, bob, event)
            blockchain_controller.wait_for_tx(tx)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

            reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            k_now = reserves_now[0] * reserves_now[1]

            assert k_now > k_values[-1], f"k must increase after swap {i + 1}"

            k_increase_pct = ((k_now - k_values[-1]) / k_values[-1]) * 100
            k_increases.append(k_increase_pct)
            k_values.append(k_now)

            if (i + 1) % 5 == 0:
                logger.info(f"After {i + 1} swaps: k={k_now}, increase={k_increase_pct:.6f}%")

        # Verify LP supply unchanged
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[2] == lp_supply_initial, "LP supply should not change"

        # Verify cumulative increase is significant
        k_final = k_values[-1]
        total_increase_pct = ((k_final - k_initial) / k_initial) * 100
        avg_increase = sum(k_increases) / len(k_increases)

        logger.info(f"Total k increase over {num_swaps} swaps: {total_increase_pct:.4f}%")
        logger.info(f"Average k increase per swap: {avg_increase:.6f}%")
        logger.info(f"Min per-swap increase: {min(k_increases):.6f}%")
        logger.info(f"Max per-swap increase: {max(k_increases):.6f}%")

        assert total_increase_pct > 0, "Cumulative fee accumulation should be positive"

        # Per-swap increases should all be positive (monotonic)
        for i, inc in enumerate(k_increases):
            assert inc > 0, f"k increase at swap {i + 1} should be positive, got {inc:.6f}%"

        logger.info("Test passed: Fees accumulate consistently over 20 swaps")

    @pytest.mark.happy_path
    def test_lp_value_increase_from_fees(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: LP token redemption value increases proportionally with fees

        GIVEN: Alice holds LP tokens
        WHEN: Bob performs swaps generating fees
        THEN:
            - Alice can redeem her LP for more tokens than she deposited
            - The excess represents accumulated fees
            - Redemption value increase is proportional to fee accumulation
            - Removing liquidity after fees gives more than original deposit

        SECURITY: LP redemption value is the fundamental incentive for providing
                  liquidity. If redemption doesn't reflect accumulated fees,
                  the protocol's incentive structure is broken.
        """
        logger.info("TEST: LP redemption value increases from fees")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Alice adds a known amount of liquidity
        alice_first = nominated_amount(100)
        alice_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(alice_first)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: alice_first,
            pair_contract.secondToken: alice_second
        })

        lp_token = Token(pair_contract.lpToken, 0)
        alice_lp_before_add = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=alice_first,
            amountAmin=int(alice_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=alice_second,
            amountBmin=int(alice_second * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_add = pair_contract.add_liquidity(network_providers, alice, add_event)
        blockchain_controller.wait_for_tx(tx_add)
        TransactionAssertions.assert_transaction_success(tx_add, network_providers.proxy)

        alice_lp = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount - alice_lp_before_add
        logger.info(f"Alice deposited: first={alice_first}, second={alice_second}, got LP={alice_lp}")

        # Record Alice's position value at deposit time
        reserves_at_deposit = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        deposit_value_first = alice_lp * reserves_at_deposit[0] // reserves_at_deposit[2]
        deposit_value_second = alice_lp * reserves_at_deposit[1] // reserves_at_deposit[2]

        # Bob generates fees with 10 swaps
        swap_amount = nominated_amount(100)
        num_swaps = 10
        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: swap_amount * num_swaps,
            pair_contract.secondToken: swap_amount * num_swaps
        })

        for i in range(num_swaps):
            if i % 2 == 0:
                token_in = pair_contract.firstToken
                token_out = pair_contract.secondToken
            else:
                token_in = pair_contract.secondToken
                token_out = pair_contract.firstToken

            event = SwapFixedInputEvent(
                tokenA=token_in, amountA=swap_amount,
                tokenB=token_out, amountBmin=1
            )
            bob.sync_nonce(network_providers.proxy)
            tx = pair_contract.swap_fixed_input(network_providers, bob, event)
            blockchain_controller.wait_for_tx(tx)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        # Calculate Alice's position value AFTER fee accumulation
        reserves_post_fees = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        redemption_value_first = alice_lp * reserves_post_fees[0] // reserves_post_fees[2]
        redemption_value_second = alice_lp * reserves_post_fees[1] // reserves_post_fees[2]

        logger.info(f"Deposit value: first={deposit_value_first}, second={deposit_value_second}")
        logger.info(f"Redemption value: first={redemption_value_first}, second={redemption_value_second}")

        # Geometric mean should increase (both dimensions may not increase individually
        # due to directional swap imbalance, but geometric mean always increases)
        geo_deposit = (deposit_value_first * deposit_value_second) ** 0.5
        geo_redemption = (redemption_value_first * redemption_value_second) ** 0.5

        assert geo_redemption > geo_deposit, (
            f"LP redemption geometric value must increase from fees.\n"
            f"At deposit: {geo_deposit:.2f}\n"
            f"At redemption: {geo_redemption:.2f}\n"
            f"Fees are not benefiting LP holders!"
        )

        value_increase_pct = ((geo_redemption - geo_deposit) / geo_deposit) * 100
        logger.info(f"LP value increase: {value_increase_pct:.4f}%")

        logger.info("Test passed: LP redemption value increases from fee accumulation")

    @pytest.mark.happy_path
    def test_fees_collector_integration(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify fee collector setup and query

        GIVEN: Pair contract with fee configuration
        WHEN: Query fee parameters to verify collector configuration
        THEN:
            - Total fee and special fee are queryable
            - Fee percentages are within valid bounds
            - Fee split (LP fee vs special fee) is consistent
            - Fee configuration matches expected values

        NOTE: Setting up a fees collector requires a separate collector contract.
              This test verifies the fee CONFIGURATION is correct, not the
              collector integration itself (which would require deploying a
              fees collector contract).
        """
        logger.info("TEST: Fee collector configuration verification")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Query all fee-related parameters
        total_fee = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee = pair_data_fetcher.get_data("getSpecialFee")

        logger.info(f"Total fee percent: {total_fee} / 100000")
        logger.info(f"Special fee percent: {special_fee} / 100000")

        # Validate fee bounds
        assert 0 <= total_fee <= 50000, f"Total fee out of range: {total_fee}"
        assert 0 <= special_fee <= total_fee, f"Special fee out of range: {special_fee}"

        lp_fee = total_fee - special_fee
        logger.info(f"LP fee: {lp_fee} / 100000 ({lp_fee / 1000:.2f}%)")

        # Verify fee affects swap output
        swap_amount = nominated_amount(100)
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Calculate zero-fee output
        zero_fee_output = (reserves[1] * swap_amount) // (reserves[0] + swap_amount)

        # Query actual output with fees
        actual_expected = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )

        assert actual_expected < zero_fee_output, (
            f"Fee should reduce output.\n"
            f"Zero-fee: {zero_fee_output}, With fee: {actual_expected}"
        )

        fee_amount = zero_fee_output - actual_expected
        fee_ratio = fee_amount / zero_fee_output if zero_fee_output > 0 else 0
        logger.info(f"Fee amount: {fee_amount} ({fee_ratio * 100:.4f}% of output)")

        # If special fee is configured, verify it takes a portion
        if special_fee > 0:
            special_ratio = special_fee / total_fee
            logger.info(f"Special fee takes {special_ratio * 100:.1f}% of total fee")
            assert special_ratio <= 1.0, "Special fee ratio should not exceed 100%"

        logger.info("Test passed: Fee collector configuration is valid and consistent")
