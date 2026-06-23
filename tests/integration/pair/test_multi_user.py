"""
Integration tests for Pair contract multi-user scenarios.

These tests verify that the AMM handles multiple concurrent users correctly:
- Multiple users swapping in sequence
- LP dilution when new providers enter
- Proportional fee distribution across LPs
- User isolation (one user's failure doesn't affect others)

Run:
    pytest --env=chainsim tests/integration/pair/test_multi_user.py
    pytest --env=chainsim tests/integration/pair/test_multi_user.py -m "happy_path"
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
class TestMultiUser:
    """
    Integration tests for multi-user pair contract interactions.

    Verifies that the AMM correctly handles concurrent users,
    proportional fee distribution, LP dilution, and user isolation.
    """

    @pytest.mark.happy_path
    def test_concurrent_swaps(
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
        SCENARIO: Multiple users swap sequentially, all succeed with correct amounts

        GIVEN: Pool with liquidity
        WHEN: Alice, Bob, and Charlie each perform swaps in sequence
        THEN:
            - All transactions succeed
            - Each user receives expected output (within slippage)
            - k monotonically increases after each swap (fees retained)
            - Reserves remain positive throughout
            - Pool state is consistent after all swaps

        SECURITY: Sequential multi-user swaps must not corrupt pool state.
                  Each swap must execute against the CURRENT pool state, not stale state.
        """
        logger.info("TEST: Concurrent (sequential) swaps by multiple users")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        swap_amount = nominated_amount(50)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        users = [
            ("Alice", alice, pair_contract.firstToken, pair_contract.secondToken),
            ("Bob", bob, pair_contract.secondToken, pair_contract.firstToken),
            ("Charlie", charlie, pair_contract.firstToken, pair_contract.secondToken),
        ]

        # Fund all users
        for name, user, token_in, _ in users:
            ensure_esdt_amounts(user, {token_in: swap_amount})

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_previous = reserves_before[0] * reserves_before[1]
        logger.info(f"Initial: reserves=({reserves_before[0]}, {reserves_before[1]}), k={k_previous}")

        # Execute swaps sequentially
        for name, user, token_in, token_out in users:
            expected_output = pair_data_fetcher.get_data(
                "getAmountOut",
                [TokenIdentifierValue(token_in), BigUIntValue(swap_amount)]
            )
            min_output = int(expected_output * 0.95)

            token_out_sdk = Token(token_out, 0)
            balance_before = network_providers.proxy.get_token_of_account(user.address, token_out_sdk).amount

            event = SwapFixedInputEvent(
                tokenA=token_in,
                amountA=swap_amount,
                tokenB=token_out,
                amountBmin=min_output
            )
            user.sync_nonce(network_providers.proxy)
            tx_hash = pair_contract.swap_fixed_input(network_providers, user, event)
            blockchain_controller.wait_for_tx(tx_hash)

            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            balance_after = network_providers.proxy.get_token_of_account(user.address, token_out_sdk).amount
            actual_output = balance_after - balance_before

            assert actual_output == expected_output, (
                f"{name}'s swap output does not match getAmountOut query result.\n"
                f"Expected: {expected_output}, Got: {actual_output}"
            )

            # k must increase
            k_current = PairAssertions.assert_constant_product_holds(
                pair_contract.address, k_previous, network_providers.proxy
            )
            logger.info(f"{name}: swapped {swap_amount} -> received {actual_output}, k={k_current}")
            k_previous = k_current

        # Final verification
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "First reserve must be positive"
        assert reserves_final[1] > 0, "Second reserve must be positive"

        k_final = reserves_final[0] * reserves_final[1]
        k_initial = reserves_before[0] * reserves_before[1]
        assert k_final > k_initial, "k should increase from accumulated fees"

        logger.info("Test passed: All concurrent swaps succeeded with monotonically increasing k")

    @pytest.mark.happy_path
    def test_lp_dilution(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Later LPs dilute early LP position correctly

        GIVEN: Pool with Alice's initial liquidity
        WHEN: Bob adds 10x more liquidity than Alice
        THEN:
            - Alice's share of pool decreases proportionally
            - Alice's LP tokens represent a smaller fraction of total supply
            - Bob's LP tokens represent a larger fraction
            - Pool ratio maintained throughout
            - Alice's absolute token position is unchanged (only relative share changes)

        SECURITY: Dilution must be purely proportional. No LP should gain or lose
                  absolute value due to another LP entering the pool.
        """
        logger.info("TEST: LP dilution when new provider enters")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        lp_token = Token(pair_contract.lpToken, 0)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Alice adds liquidity
        alice_amount = nominated_amount(100)
        alice_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(alice_amount)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: alice_amount,
            pair_contract.secondToken: alice_equivalent
        })

        alice_lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        alice_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=alice_amount,
            amountAmin=int(alice_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=alice_equivalent,
            amountBmin=int(alice_equivalent * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_alice = pair_contract.add_liquidity(network_providers, alice, alice_event)
        blockchain_controller.wait_for_tx(tx_alice)
        TransactionAssertions.assert_transaction_success(tx_alice, network_providers.proxy)

        alice_lp_delta = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount - alice_lp_before

        reserves_after_alice = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        total_supply_after_alice = reserves_after_alice[2]
        alice_share_before = alice_lp_delta / total_supply_after_alice
        logger.info(f"Alice LP delta: {alice_lp_delta}, share: {alice_share_before:.4%}")

        # Compute Alice's position value before Bob enters
        alice_value_first_before = alice_lp_delta * reserves_after_alice[0] // total_supply_after_alice
        alice_value_second_before = alice_lp_delta * reserves_after_alice[1] // total_supply_after_alice

        # Bob adds 10x more liquidity
        bob_amount = nominated_amount(1000)
        bob_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(bob_amount)]
        )

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: bob_amount,
            pair_contract.secondToken: bob_equivalent
        })

        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount

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

        bob_lp_delta = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount - bob_lp_before

        reserves_after_bob = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        total_supply_after_bob = reserves_after_bob[2]

        alice_share_after = alice_lp_delta / total_supply_after_bob
        bob_share = bob_lp_delta / total_supply_after_bob

        logger.info(f"After Bob: Alice share={alice_share_after:.4%}, Bob share={bob_share:.4%}")

        # Alice's share should have decreased
        assert alice_share_after < alice_share_before, (
            f"Alice's share should decrease after Bob enters.\n"
            f"Before: {alice_share_before:.4%}, After: {alice_share_after:.4%}"
        )

        # Bob should have larger share (he added 10x more)
        assert bob_lp_delta > alice_lp_delta, (
            f"Bob should have more LP tokens (added 10x more).\n"
            f"Alice: {alice_lp_delta}, Bob: {bob_lp_delta}"
        )

        # Alice's absolute position value should be approximately unchanged
        alice_value_first_after = alice_lp_delta * reserves_after_bob[0] // total_supply_after_bob
        alice_value_second_after = alice_lp_delta * reserves_after_bob[1] // total_supply_after_bob

        tolerance_pct = 0.01  # 1% tolerance for rounding
        if alice_value_first_before > 0:
            value_change_first = abs(alice_value_first_after - alice_value_first_before) / alice_value_first_before
            assert value_change_first < tolerance_pct, (
                f"Alice's first token position value changed by {value_change_first:.2%}.\n"
                f"Before: {alice_value_first_before}, After: {alice_value_first_after}"
            )

        # Pool ratio should be maintained
        ratio_before = reserves_after_alice[0] / reserves_after_alice[1]
        ratio_after = reserves_after_bob[0] / reserves_after_bob[1]
        ratio_change = abs(ratio_after - ratio_before) / ratio_before * 100
        assert ratio_change < 0.1, f"Pool ratio changed by {ratio_change:.4f}%"

        logger.info("Test passed: LP dilution is purely proportional, no value loss")

    @pytest.mark.happy_path
    @pytest.mark.slow
    def test_proportional_fee_distribution(
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
        SCENARIO: Fees from swaps are distributed proportionally to LP holders

        GIVEN: Alice and Bob provide liquidity in 2:1 ratio
        WHEN: Charlie performs multiple swaps (generating fees)
        THEN:
            - Both LPs benefit from fees (LP value increases)
            - Fee distribution is proportional to LP share
            - Alice (2x liquidity) gets ~2x the fee benefit of Bob
            - Pool k increases from accumulated fees

        SECURITY: Fee distribution must be fair and proportional.
                  Unproportional distribution would create an exploit vector.
        """
        logger.info("TEST: Proportional fee distribution across LPs")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        lp_token = Token(pair_contract.lpToken, 0)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Alice adds 200 tokens of liquidity
        alice_amount = nominated_amount(200)
        alice_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(alice_amount)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: alice_amount,
            pair_contract.secondToken: alice_equivalent
        })

        alice_lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        alice_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=alice_amount,
            amountAmin=int(alice_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=alice_equivalent,
            amountBmin=int(alice_equivalent * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx = pair_contract.add_liquidity(network_providers, alice, alice_event)
        blockchain_controller.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        alice_lp_delta = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount - alice_lp_before

        # Bob adds 100 tokens (half of Alice)
        bob_amount = nominated_amount(100)
        bob_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(bob_amount)]
        )

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: bob_amount,
            pair_contract.secondToken: bob_equivalent
        })

        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount

        bob_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=bob_amount,
            amountAmin=int(bob_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=bob_equivalent,
            amountBmin=int(bob_equivalent * 0.95)
        )
        bob.sync_nonce(network_providers.proxy)
        tx = pair_contract.add_liquidity(network_providers, bob, bob_event)
        blockchain_controller.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        bob_lp_delta = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount - bob_lp_before

        logger.info(f"LP deltas: Alice={alice_lp_delta}, Bob={bob_lp_delta}")

        # Record LP position values BEFORE swaps
        reserves_pre_swap = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        supply_pre = reserves_pre_swap[2]

        alice_geo_before = (
            (alice_lp_delta * reserves_pre_swap[0] // supply_pre) *
            (alice_lp_delta * reserves_pre_swap[1] // supply_pre)
        ) ** 0.5

        bob_geo_before = (
            (bob_lp_delta * reserves_pre_swap[0] // supply_pre) *
            (bob_lp_delta * reserves_pre_swap[1] // supply_pre)
        ) ** 0.5

        # Charlie performs 10 swaps to generate fees
        swap_amount = nominated_amount(50)
        num_swaps = 10
        ensure_esdt_amounts(charlie, {
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
            charlie.sync_nonce(network_providers.proxy)
            tx = pair_contract.swap_fixed_input(network_providers, charlie, event)
            blockchain_controller.wait_for_tx(tx)
            TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)

        # Record LP position values AFTER swaps
        reserves_post_swap = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        supply_post = reserves_post_swap[2]

        assert supply_post == supply_pre, "LP supply should be unchanged after swaps"

        alice_geo_after = (
            (alice_lp_delta * reserves_post_swap[0] // supply_post) *
            (alice_lp_delta * reserves_post_swap[1] // supply_post)
        ) ** 0.5

        bob_geo_after = (
            (bob_lp_delta * reserves_post_swap[0] // supply_post) *
            (bob_lp_delta * reserves_post_swap[1] // supply_post)
        ) ** 0.5

        # Both should have increased in value
        assert alice_geo_after > alice_geo_before, "Alice's LP value should increase from fees"
        assert bob_geo_after > bob_geo_before, "Bob's LP value should increase from fees"

        alice_gain = alice_geo_after - alice_geo_before
        bob_gain = bob_geo_after - bob_geo_before

        logger.info(f"Alice gain: {alice_gain:.2f}, Bob gain: {bob_gain:.2f}")

        # Alice should gain approximately 2x what Bob gains (she has 2x LP)
        if bob_gain > 0:
            gain_ratio = alice_gain / bob_gain
            expected_ratio = alice_lp_delta / bob_lp_delta
            logger.info(f"Gain ratio: {gain_ratio:.4f}, Expected: {expected_ratio:.4f}")

            assert abs(gain_ratio - expected_ratio) / expected_ratio < 0.05, (
                f"Fee distribution not proportional to LP share.\n"
                f"Alice/Bob LP ratio: {expected_ratio:.4f}\n"
                f"Alice/Bob gain ratio: {gain_ratio:.4f}"
            )

        logger.info("Test passed: Fee distribution is proportional to LP holdings")

    @pytest.mark.happy_path
    def test_user_isolation(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: One user's failed transaction doesn't affect another user's state

        GIVEN: Pool with liquidity, Alice and Bob funded
        WHEN: Bob attempts a swap with impossible slippage (fails),
              then Alice performs a normal swap (succeeds)
        THEN:
            - Bob's failed tx doesn't change pool reserves
            - Alice's successful tx works as expected
            - Bob's token balances unchanged after his failed tx
            - Pool state is consistent throughout

        SECURITY: Failed transactions MUST NOT modify any state.
                  User isolation prevents cross-contamination of errors.
        """
        logger.info("TEST: User isolation - failed tx doesn't affect others")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(10000)
        )

        swap_amount = nominated_amount(10)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Fund both users
        ensure_esdt_amounts(bob, {pair_contract.firstToken: swap_amount})
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        # Capture state before Bob's failed tx
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        bob_first_before = network_providers.proxy.get_token_of_account(bob.address, token_first).amount
        bob_second_before = network_providers.proxy.get_token_of_account(bob.address, token_second).amount

        # Bob tries swap with impossible slippage (should fail)
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )
        impossible_min = expected_output * 2  # 200% of expected

        bob_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=impossible_min
        )
        bob.sync_nonce(network_providers.proxy)
        bob_tx = pair_contract.swap_fixed_input(network_providers, bob, bob_event)
        blockchain_controller.wait_for_tx(bob_tx)

        TransactionAssertions.assert_transaction_failed(bob_tx, network_providers.proxy)
        logger.info("Bob's swap failed as expected")

        # Verify Bob's state unchanged
        bob_first_after_fail = network_providers.proxy.get_token_of_account(bob.address, token_first).amount
        bob_second_after_fail = network_providers.proxy.get_token_of_account(bob.address, token_second).amount
        assert bob_first_after_fail == bob_first_before, "Bob's first token balance should be unchanged"
        assert bob_second_after_fail == bob_second_before, "Bob's second token balance should be unchanged"

        # Verify reserves unchanged after Bob's failure
        reserves_after_bob = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after_bob == reserves_before, "Reserves should be unchanged after failed tx"

        # Alice performs a normal swap (should succeed)
        alice_second_before = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        alice_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        alice_tx = pair_contract.swap_fixed_input(network_providers, alice, alice_event)
        blockchain_controller.wait_for_tx(alice_tx)

        TransactionAssertions.assert_transaction_success(alice_tx, network_providers.proxy)

        alice_second_after = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        assert alice_second_after > alice_second_before, "Alice should have received output tokens"

        # Reserves should now reflect Alice's swap
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > reserves_before[0], "First reserve should increase from Alice's input"
        assert reserves_final[1] < reserves_before[1], "Second reserve should decrease from Alice's output"

        logger.info("Test passed: User isolation maintained - Bob's failure didn't affect Alice")
