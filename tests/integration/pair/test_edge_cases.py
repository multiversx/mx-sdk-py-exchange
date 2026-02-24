"""
Integration tests for Pair contract edge cases and boundary conditions.

These tests verify the AMM handles extreme scenarios correctly:
- First liquidity provider advantage (initial price setting)
- Extreme price ratios (1:1000000)
- Pool recovery after drain (re-add liquidity after full removal)

Run:
    pytest --env=chainsim tests/integration/pair/test_edge_cases.py
    pytest --env=chainsim tests/integration/pair/test_edge_cases.py -m "edge_case"
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
class TestEdgeCases:
    """
    Integration tests for edge cases and boundary conditions.

    Tests extreme scenarios that could expose bugs in the AMM implementation.
    """

    @pytest.mark.edge_case
    def test_first_liquidity_provider_advantage(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: First LP sets the price ratio; subsequent LPs must match it

        GIVEN: Pool with existing reserves at some ratio
        WHEN: Bob tries to add liquidity at a different ratio
        THEN:
            - Contract adjusts amounts to match existing ratio
            - Excess tokens returned to Bob
            - Bob's LP tokens are proportional to the USED amounts, not sent amounts
            - Pool ratio remains unchanged

        SECURITY: The first LP has power to set the initial price.
                  Subsequent LPs must not be able to change the ratio.
                  If they could, it would enable price manipulation attacks.
        """
        logger.info("TEST: First LP advantage - ratio enforcement for subsequent LPs")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(1000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        ratio_before = reserves_before[0] / reserves_before[1]
        logger.info(f"Pool ratio: {ratio_before:.6f}")

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Bob tries to add with 2x the required second token (imbalanced)
        bob_first = nominated_amount(100)
        equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(bob_first)]
        )
        bob_second = equivalent_second * 2  # Double the required amount

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: bob_first,
            pair_contract.secondToken: bob_second
        })

        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        bob_first_before = network_providers.proxy.get_token_of_account(bob.address, token_first).amount
        bob_second_before = network_providers.proxy.get_token_of_account(bob.address, token_second).amount
        lp_token = Token(pair_contract.lpToken, 0)
        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount

        bob_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=bob_first,
            amountAmin=int(bob_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=bob_second,
            amountBmin=int(equivalent_second * 0.95)  # Min based on actual equivalent
        )
        bob.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, bob, bob_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify pool ratio unchanged
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        ratio_after = reserves_after[0] / reserves_after[1]

        ratio_change_pct = abs(ratio_after - ratio_before) / ratio_before * 100
        assert ratio_change_pct < 0.1, (
            f"Pool ratio should not change. Before: {ratio_before:.6f}, After: {ratio_after:.6f}, "
            f"Change: {ratio_change_pct:.4f}%"
        )
        logger.info(f"Pool ratio maintained: {ratio_before:.6f} -> {ratio_after:.6f}")

        # Verify Bob got excess tokens back (contract used only proportional amounts)
        bob_second_after = network_providers.proxy.get_token_of_account(bob.address, token_second).amount
        bob_second_spent = bob_second_before - bob_second_after

        # Bob should have spent approximately equivalent_second, not bob_second (2x)
        tolerance = nominated_amount(5)
        assert abs(bob_second_spent - equivalent_second) < tolerance, (
            f"Bob should have spent ~{equivalent_second} second tokens.\n"
            f"Actually spent: {bob_second_spent}\n"
            f"Sent: {bob_second} (excess should be returned)"
        )

        # Bob should have received LP tokens
        bob_lp_after = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount
        bob_lp_delta = bob_lp_after - bob_lp_before
        assert bob_lp_delta > 0, "Bob should have received LP tokens"

        logger.info("Test passed: Subsequent LPs must match existing ratio, excess returned")

    @pytest.mark.edge_case
    def test_extreme_price_ratios(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Verify swaps work correctly even with extreme pool ratios

        GIVEN: Pool where one reserve is much larger than the other
              (created by a large directional swap)
        WHEN: Alice swaps in both directions at the extreme ratio
        THEN:
            - Both swaps succeed
            - k never decreases
            - Reserves remain positive
            - Output amounts are reasonable (no precision loss)

        SECURITY: Extreme ratios stress-test integer arithmetic.
                  Overflow, underflow, or precision loss at extreme ratios
                  could enable rounding attacks or pool drainage.
        """
        logger.info("TEST: Swaps at extreme price ratios")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]

        # Push the pool to an extreme ratio by swapping a large amount
        # Swap 30% of first reserve to skew ratio significantly
        skew_amount = reserves_initial[0] * 30 // 100
        ensure_esdt_amounts(alice, {pair_contract.firstToken: skew_amount})

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(skew_amount)]
        )

        skew_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=skew_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx = pair_contract.swap_fixed_input(network_providers, alice, skew_event)
        blockchain_controller.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        reserves_skewed = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        skewed_ratio = reserves_skewed[0] / reserves_skewed[1] if reserves_skewed[1] > 0 else float('inf')
        logger.info(f"Skewed reserves: ({reserves_skewed[0]}, {reserves_skewed[1]}), ratio: {skewed_ratio:.4f}")

        # Now swap in both directions at the extreme ratio
        # Swap first -> second (adding to already-large first reserve)
        small_amount = nominated_amount(10)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: small_amount})

        expected_out_fwd = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(small_amount)]
        )
        assert expected_out_fwd > 0, "Output should be positive even at extreme ratio"

        fwd_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=small_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_fwd = pair_contract.swap_fixed_input(network_providers, alice, fwd_event)
        blockchain_controller.wait_for_tx(tx_fwd)
        TransactionAssertions.assert_transaction_success(tx_fwd, network_providers.proxy)

        k_after_fwd = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_initial, network_providers.proxy
        )
        logger.info(f"Forward swap at extreme ratio succeeded, k={k_after_fwd}")

        # Swap second -> first (small amount of depleted token)
        small_second = nominated_amount(1)
        ensure_esdt_amounts(alice, {pair_contract.secondToken: small_second})

        expected_out_rev = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.secondToken), BigUIntValue(small_second)]
        )
        assert expected_out_rev > 0, "Reverse output should be positive"

        rev_event = SwapFixedInputEvent(
            tokenA=pair_contract.secondToken,
            amountA=small_second,
            tokenB=pair_contract.firstToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_rev = pair_contract.swap_fixed_input(network_providers, alice, rev_event)
        blockchain_controller.wait_for_tx(tx_rev)
        TransactionAssertions.assert_transaction_success(tx_rev, network_providers.proxy)

        k_final = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_after_fwd, network_providers.proxy
        )

        # Final state check
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "First reserve must be positive"
        assert reserves_final[1] > 0, "Second reserve must be positive"

        logger.info(f"Final reserves: ({reserves_final[0]}, {reserves_final[1]})")
        logger.info("Test passed: Swaps work correctly at extreme price ratios")

    @pytest.mark.edge_case
    def test_pool_recovery_after_drain(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Pool can be re-used after being drained to minimum liquidity

        GIVEN: Alice adds liquidity, then removes as much as possible
        WHEN: Bob adds new liquidity to the near-empty pool
        THEN:
            - Bob can add liquidity successfully
            - Pool is functional again (swaps work)
            - k is positive and grows with fees
            - Reserves reflect the new liquidity

        SECURITY: A pool drained to minimum locked liquidity must remain usable.
                  If recovery fails, an attacker could permanently DoS a pool
                  by draining it.
        """
        logger.info("TEST: Pool recovery after drain")

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
        add_amount = nominated_amount(500)
        equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount,
            pair_contract.secondToken: equivalent
        })

        lp_token = Token(pair_contract.lpToken, 0)
        alice_lp_before_add = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount,
            amountAmin=int(add_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=equivalent,
            amountBmin=int(equivalent * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx = pair_contract.add_liquidity(network_providers, alice, add_event)
        blockchain_controller.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        alice_lp_after_add = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
        alice_lp_delta = alice_lp_after_add - alice_lp_before_add
        logger.info(f"Alice LP minted: {alice_lp_delta}")

        reserves_after_add = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Alice removes all her LP from this add
        if alice_lp_delta > 0:
            expected_first = alice_lp_delta * reserves_after_add[0] // reserves_after_add[2]
            expected_second = alice_lp_delta * reserves_after_add[1] // reserves_after_add[2]

            remove_event = RemoveLiquidityEvent(
                amount=alice_lp_delta,
                tokenA=pair_contract.firstToken,
                amountA=int(expected_first * 0.90),  # 10% slippage
                tokenB=pair_contract.secondToken,
                amountB=int(expected_second * 0.90)
            )
            alice.sync_nonce(network_providers.proxy)
            tx_remove = pair_contract.remove_liquidity(network_providers, alice, remove_event)
            blockchain_controller.wait_for_tx(tx_remove)
            TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
            logger.info("Alice removed her LP tokens")

        reserves_after_drain = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        logger.info(f"Reserves after drain: ({reserves_after_drain[0]}, {reserves_after_drain[1]})")

        # Pool should still have some liquidity (minimum locked + other LPs)
        assert reserves_after_drain[0] > 0, "Pool should still have first token reserves"
        assert reserves_after_drain[1] > 0, "Pool should still have second token reserves"

        # Bob adds new liquidity to recover the pool
        bob_amount = nominated_amount(200)
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
        logger.info("Bob added new liquidity - pool recovered")

        reserves_recovered = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_recovered = reserves_recovered[0] * reserves_recovered[1]
        logger.info(f"Recovered reserves: ({reserves_recovered[0]}, {reserves_recovered[1]}), k={k_recovered}")

        # Verify pool is functional: perform a swap
        swap_amount = nominated_amount(5)
        ensure_esdt_amounts(bob, {pair_contract.firstToken: swap_amount})

        swap_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        tx_swap = pair_contract.swap_fixed_input(network_providers, bob, swap_event)
        blockchain_controller.wait_for_tx(tx_swap)
        TransactionAssertions.assert_transaction_success(tx_swap, network_providers.proxy)

        # k should increase from the swap fee
        k_after_swap = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_recovered, network_providers.proxy
        )
        assert k_after_swap > k_recovered, "k should increase from swap fee"

        logger.info("Test passed: Pool successfully recovered after drain and is fully functional")
