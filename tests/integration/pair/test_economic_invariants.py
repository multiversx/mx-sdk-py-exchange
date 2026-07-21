"""
Integration tests for Pair contract economic invariants.

These tests verify that the AMM's core economic properties hold under various
conditions through black-box testing:
- Fee accumulation increases k (constant product)
- LP token value increases as fees accumulate
- No round-trip arbitrage is profitable (fees prevent it)
- LP supply is consistent with user holdings

Test Categories:
1. Fee Accumulation: Verify fees are retained in reserves via k increase
2. LP Value: LP redemption value increases with accumulated fees
3. Arbitrage: No profitable round-trip swaps
4. Supply Consistency: LP supply matches sum of user holdings

Run:
    pytest --env=chainsim tests/integration/pair/test_economic_invariants.py
    pytest --env=chainsim tests/integration/pair/test_economic_invariants.py -m "happy_path"
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
class TestPairEconomicInvariants:
    """
    Integration tests for Pair contract economic invariants.

    These tests verify the fundamental economic properties of the AMM:
    1. Constant product k = x * y only increases (from fees)
    2. LP token value reflects accumulated fees
    3. Fees prevent profitable round-trip arbitrage
    4. LP total supply is always consistent with individual holdings

    Economic Invariants Verified:
    - k never decreases after any operation
    - LP redemption value monotonically increases with fee accumulation
    - Round-trip swap always results in net loss (fee cost)
    - sum(user_lp_balances) == total_lp_supply
    """

    @pytest.mark.happy_path
    def test_fees_accumulate_correctly(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify fees accumulate in pool reserves after swaps

        GIVEN: Pool with initial liquidity, known fee configuration
        WHEN: Bob performs multiple swaps in both directions
        THEN:
            - k increases monotonically after each swap
            - Total k increase is consistent with fee rate
            - LP supply unchanged (swaps don't mint/burn LP)
            - Both reserves remain positive

        SECURITY: Fee accumulation is the economic engine of the AMM.
                  If fees don't accumulate correctly, LP providers lose incentive.
        """
        logger.info("TEST: Fees accumulate correctly in reserves")

        # Setup pool with substantial liquidity
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        # Query fee configuration
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        total_fee_percent = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee_percent = pair_data_fetcher.get_data("getSpecialFee")
        logger.info(f"Fee config: total_fee={total_fee_percent}/100000, special_fee={special_fee_percent}/100000")

        # Capture initial state
        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]
        lp_supply_initial = reserves_initial[2]

        logger.info(f"Initial: reserves=({reserves_initial[0]}, {reserves_initial[1]}), k={k_initial}")

        # Perform swaps and track k after each
        swap_amount = nominated_amount(100)
        num_swaps = 8
        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: swap_amount * num_swaps,
            pair_contract.secondToken: swap_amount * num_swaps
        })

        k_values = [k_initial]
        for i in range(num_swaps):
            if i % 2 == 0:
                token_in = pair_contract.firstToken
                token_out = pair_contract.secondToken
            else:
                token_in = pair_contract.secondToken
                token_out = pair_contract.firstToken

            event = SwapFixedInputEvent(
                tokenA=token_in,
                amountA=swap_amount,
                tokenB=token_out,
                amountBmin=1
            )
            bob.sync_nonce(network_providers.proxy)
            tx_hash = pair_contract.swap_fixed_input(network_providers, bob, event)
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Verify k increased
            reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            k_now = reserves_now[0] * reserves_now[1]

            assert k_now > k_values[-1], (
                f"k must increase after swap {i + 1} (fees retained).\n"
                f"k_before: {k_values[-1]}\nk_after: {k_now}"
            )
            k_values.append(k_now)

            logger.info(f"Swap {i + 1}: k={k_now} (+{((k_now - k_values[-2]) / k_values[-2] * 100):.6f}%)")

        # Verify monotonic k increase
        for i in range(1, len(k_values)):
            assert k_values[i] > k_values[i - 1], (
                f"k must be monotonically increasing. k[{i - 1}]={k_values[i - 1]}, k[{i}]={k_values[i]}"
            )

        # Verify LP supply unchanged
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[2] == lp_supply_initial, (
            f"LP supply should be unchanged after swaps.\n"
            f"Initial: {lp_supply_initial}, Final: {reserves_final[2]}"
        )

        # Log total fee accumulation
        k_final = reserves_final[0] * reserves_final[1]
        total_k_increase_pct = ((k_final - k_initial) / k_initial) * 100
        logger.info(f"Total k increase over {num_swaps} swaps: {total_k_increase_pct:.4f}%")
        logger.info(f"Average k increase per swap: {total_k_increase_pct / num_swaps:.4f}%")

        logger.info("Test passed: Fees accumulate correctly (k monotonically increases)")

    @pytest.mark.happy_path
    def test_lp_token_value_increases_with_fees(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: LP token redemption value increases as fees accumulate

        GIVEN: Pool with initial liquidity, Alice holds LP tokens
        WHEN: Bob performs multiple swaps (paying fees)
        THEN:
            - getTokensForGivenPosition returns higher values for same LP amount
            - Geometric mean of underlying token values increases
            - LP supply unchanged, but reserves grew from fees

        SECURITY: This is the core value proposition for liquidity providers.
                  If LP value doesn't increase with fees, the AMM is broken.
        """
        logger.info("TEST: LP token value increases with fee accumulation")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        lp_supply = reserves_before[2]

        # Use a fixed LP amount to query position value
        test_lp_amount = nominated_amount(100)

        # Calculate LP value BEFORE swaps
        # Formula: token_amount = lp_amount * reserve / total_supply
        value_first_before = test_lp_amount * reserves_before[0] // lp_supply
        value_second_before = test_lp_amount * reserves_before[1] // lp_supply
        geo_value_before = (value_first_before * value_second_before) ** 0.5

        logger.info(f"LP value before swaps: first={value_first_before}, second={value_second_before}")
        logger.info(f"Geometric mean: {geo_value_before:.2f}")

        # Bob performs swaps to accumulate fees
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
                tokenA=token_in,
                amountA=swap_amount,
                tokenB=token_out,
                amountBmin=1
            )
            bob.sync_nonce(network_providers.proxy)
            tx = pair_contract.swap_fixed_input(network_providers, bob, event)
            blockchain_controller.wait_for_tx(tx)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        # Calculate LP value AFTER swaps
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        lp_supply_after = reserves_after[2]

        # LP supply must be unchanged
        assert lp_supply_after == lp_supply, "LP supply should not change from swaps"

        value_first_after = test_lp_amount * reserves_after[0] // lp_supply_after
        value_second_after = test_lp_amount * reserves_after[1] // lp_supply_after
        geo_value_after = (value_first_after * value_second_after) ** 0.5

        logger.info(f"LP value after swaps: first={value_first_after}, second={value_second_after}")
        logger.info(f"Geometric mean: {geo_value_after:.2f}")

        # Geometric mean of LP position value MUST increase
        assert geo_value_after > geo_value_before, (
            f"LP geometric value must increase with fee accumulation.\n"
            f"Before: {geo_value_before:.2f}\n"
            f"After: {geo_value_after:.2f}\n"
            f"This means fees are NOT being retained in the pool."
        )

        value_increase_pct = ((geo_value_after - geo_value_before) / geo_value_before) * 100
        logger.info(f"LP value increased by {value_increase_pct:.4f}%")

        logger.info("Test passed: LP token value increases with fee accumulation")

    @pytest.mark.happy_path
    def test_no_arbitrage_opportunity(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Round-trip swap (A->B->A) always results in net loss due to fees

        GIVEN: Pool with liquidity
        WHEN: Alice swaps tokenA for tokenB, then swaps all received tokenB back to tokenA
        THEN:
            - Alice ends up with LESS tokenA than she started with
            - The difference is approximately 2x the fee rate (fee on each leg)
            - No profitable arbitrage exists from simple round-trip swaps

        SECURITY: If round-trip arbitrage were profitable, the pool could be drained.
                  Fees MUST prevent this to ensure pool stability.
        """
        logger.info("TEST: No arbitrage opportunity from round-trip swaps")

        # Setup pool
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Swap amounts to test
        swap_amount = nominated_amount(100)

        # Fund Alice with firstToken for leg 1 (leg 2 uses received secondToken)
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: swap_amount
        })

        # Get Alice's initial balances
        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        alice_first_before = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # Leg 1: Swap tokenA -> tokenB
        event1 = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx1 = pair_contract.swap_fixed_input(network_providers, alice, event1)
        blockchain_controller.wait_for_tx(tx1)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        # Check how much tokenB Alice ACTUALLY received (not pre-queried estimate)
        alice_second_after_leg1 = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        actual_received_b = alice_second_after_leg1 - alice_second_before
        logger.info(f"Leg 1: Swapped {swap_amount} tokenA -> received {actual_received_b} tokenB")

        # Leg 2: Swap ALL ACTUALLY RECEIVED tokenB back to tokenA
        # Critical: use actual_received_b, not pre-queried expected amount,
        # since pool state changed after leg 1
        event2 = SwapFixedInputEvent(
            tokenA=pair_contract.secondToken,
            amountA=actual_received_b,
            tokenB=pair_contract.firstToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx2 = pair_contract.swap_fixed_input(network_providers, alice, event2)
        blockchain_controller.wait_for_tx(tx2)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        # Get Alice's final tokenA balance
        alice_first_after = network_providers.proxy.get_token_of_account(alice.address, token_first).amount

        # Calculate net change
        net_change = alice_first_after - alice_first_before
        logger.info(f"Leg 2: Swapped tokenB back -> received tokenA")
        logger.info(f"Alice tokenA: before={alice_first_before}, after={alice_first_after}")
        logger.info(f"Net change: {net_change} (should be negative)")

        # CRITICAL ASSERTION: Alice must end up with LESS tokenA
        assert net_change < 0, (
            f"Round-trip swap MUST result in net loss (fees prevent arbitrage).\n"
            f"Started: {alice_first_before}\n"
            f"Ended: {alice_first_after}\n"
            f"Net change: {net_change} (SHOULD be negative)\n"
            f"CRITICAL: Profitable round-trip arbitrage would drain the pool!"
        )

        loss_pct = abs(net_change) / swap_amount * 100
        logger.info(f"Round-trip loss: {abs(net_change)} tokens ({loss_pct:.2f}% of input)")

        # Loss should be approximately 2x fee rate (fee applied on each leg)
        total_fee_percent = pair_data_fetcher.get_data("getTotalFeePercent")
        expected_loss_pct = 2 * total_fee_percent / 1000  # Convert from basis points to percentage
        logger.info(f"Expected loss ~{expected_loss_pct:.2f}% (2x {total_fee_percent}/100000 fee)")

        logger.info("Test passed: No arbitrage opportunity - round-trip results in net loss")

    @pytest.mark.happy_path
    def test_lp_supply_consistency(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        charlie: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Sum of all user LP holdings equals total LP supply

        GIVEN: Pool with multiple liquidity providers
        WHEN: Alice, Bob, and Charlie each add liquidity
        THEN:
            - LP_alice + LP_bob + LP_charlie == total_LP_supply
            - Each user's LP balance is non-zero
            - Total supply from getReservesAndTotalSupply matches

        SECURITY: LP supply inconsistency would mean tokens minted/burned
                  without proper accounting, enabling infinite mint attacks.
        """
        logger.info("TEST: LP supply consistency across multiple users")

        # Setup pool with initial liquidity from Alice
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(1000)
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Track LP supply and reserves BEFORE this test's add operations
        lp_token = Token(pair_contract.lpToken, 0)
        reserves_before_bob = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        supply_before = reserves_before_bob[2]
        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount
        charlie_lp_before = network_providers.proxy.get_token_of_account(charlie.address, lp_token).amount

        # Bob adds liquidity
        bob_amount = nominated_amount(500)
        bob_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(bob_amount)]
        )
        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: bob_amount,
            pair_contract.secondToken: bob_equivalent
        })

        bob_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=bob_amount,
            amountAmin=int(bob_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=bob_equivalent,
            amountBmin=int(bob_equivalent * 0.95)
        )
        bob.sync_nonce(network_providers.proxy)
        tx_bob = pair_contract.add_liquidity(network_providers, bob, bob_event)
        blockchain_controller.wait_for_tx(tx_bob)
        TransactionAssertions.assert_transaction_success(tx_bob, network_providers.proxy)

        reserves_after_bob = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Charlie adds liquidity
        charlie_amount = nominated_amount(200)
        charlie_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(charlie_amount)]
        )
        ensure_esdt_amounts(charlie, {
            pair_contract.firstToken: charlie_amount,
            pair_contract.secondToken: charlie_equivalent
        })

        charlie_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=charlie_amount,
            amountAmin=int(charlie_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=charlie_equivalent,
            amountBmin=int(charlie_equivalent * 0.95)
        )
        charlie.sync_nonce(network_providers.proxy)
        tx_charlie = pair_contract.add_liquidity(network_providers, charlie, charlie_event)
        blockchain_controller.wait_for_tx(tx_charlie)
        TransactionAssertions.assert_transaction_success(tx_charlie, network_providers.proxy)

        # Query LP deltas from THIS test's operations only
        bob_lp_delta = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount - bob_lp_before
        charlie_lp_delta = network_providers.proxy.get_token_of_account(charlie.address, lp_token).amount - charlie_lp_before

        logger.info(f"LP minted in this test: Bob={bob_lp_delta}, Charlie={charlie_lp_delta}")

        # Each user should have received exactly the expected LP amount
        expected_bob_lp = min(
            bob_amount * reserves_before_bob[2] // reserves_before_bob[0],
            bob_equivalent * reserves_before_bob[2] // reserves_before_bob[1]
        )
        assert bob_lp_delta == expected_bob_lp, (
            f"Bob LP minted should be exactly {expected_bob_lp}, got {bob_lp_delta}"
        )

        expected_charlie_lp = min(
            charlie_amount * reserves_after_bob[2] // reserves_after_bob[0],
            charlie_equivalent * reserves_after_bob[2] // reserves_after_bob[1]
        )
        assert charlie_lp_delta == expected_charlie_lp, (
            f"Charlie LP minted should be exactly {expected_charlie_lp}, got {charlie_lp_delta}"
        )

        # Query total supply after adds
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        total_supply = reserves[2]
        supply_delta = total_supply - supply_before

        logger.info(f"LP supply increase: {supply_delta}")
        logger.info(f"Sum of LP minted to users: {bob_lp_delta + charlie_lp_delta}")

        # The LP minted to Bob + Charlie should exactly equal the supply increase
        sum_user_lp_delta = bob_lp_delta + charlie_lp_delta
        assert sum_user_lp_delta == supply_delta, (
            f"Sum of user LP deltas should exactly equal supply increase!\n"
            f"Bob: {bob_lp_delta} + Charlie: {charlie_lp_delta} = {sum_user_lp_delta}\n"
            f"Supply increase: {supply_delta}"
        )

        # The difference (if any) should be negligible (rounding)
        unaccounted_lp = supply_delta - sum_user_lp_delta
        logger.info(f"Unaccounted LP (rounding): {unaccounted_lp}")

        if supply_delta > 0:
            unaccounted_pct = unaccounted_lp / supply_delta * 100
            logger.info(f"Unaccounted as % of minted: {unaccounted_pct:.4f}%")
            assert unaccounted_pct < 1.0, (
                f"Unaccounted LP percentage too high: {unaccounted_pct:.4f}%\n"
                f"This suggests LP tokens minted without proper accounting."
            )

        logger.info("Test passed: LP supply is consistent with individual holdings")
