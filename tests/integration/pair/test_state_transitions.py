"""
Integration tests for Pair contract state transitions.

These tests verify the pair contract's pause/resume lifecycle:
- Active -> Inactive (pause swaps)
- All operations fail when paused
- Inactive -> Active (resume swaps)

Requires deployer_account fixture (admin/owner permissions).

Run:
    pytest --env=chainsim tests/integration/pair/test_state_transitions.py
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


def _ensure_deployer_has_egld(deployer_account, test_environment, network_providers):
    """Ensure deployer account has EGLD for gas fees on chain simulator."""
    from tests.environments import ChainsimEnvironment
    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        account_data = network_providers.proxy.get_account(deployer_account.address)
        min_egld = nominated_amount(10)
        if account_data.balance < min_egld:
            logger.info(f"Funding deployer {deployer_account.address.to_bech32()} with EGLD for gas")
            test_environment.chain_sim.fund_users_w_egld(
                [deployer_account.address.to_bech32()], min_egld
            )


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
class TestStateTransitions:
    """
    Integration tests for Pair contract state management.

    Tests the pause/resume lifecycle and verifies that all user operations
    fail correctly when the contract is paused.

    IMPORTANT: These tests modify contract state (pause/resume).
    They always resume the contract at the end to avoid affecting other tests.
    """

    @pytest.mark.happy_path
    def test_pair_state_active_to_inactive(
        self,
        pair_contract: PairContract,
        alice: Account,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: Pause the pair contract (disable swaps)

        GIVEN: Active pair contract with liquidity
        WHEN: Owner calls setStateActiveNoSwaps
        THEN:
            - Transaction succeeds (owner has permission)
            - Swaps are rejected after pause
            - Contract state reflects the change

        SECURITY: Only the owner should be able to pause the contract.
                  Unauthorized pauses would be a denial-of-service attack.
        """
        logger.info("TEST: Transition pair from active to inactive (no swaps)")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Verify swaps work BEFORE pause
        swap_amount = nominated_amount(5)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        pre_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_pre = pair_contract.swap_fixed_input(network_providers, alice, pre_event)
        blockchain_controller.wait_for_tx(tx_pre)
        TransactionAssertions.assert_transaction_success(tx_pre, network_providers.proxy)
        logger.info("Swap succeeded while active (pre-pause check)")

        # Pause the contract
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = pair_contract.set_active_no_swaps(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Pair contract paused (setStateActiveNoSwaps)")

        # Attempt swap after pause - should FAIL
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        post_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_post = pair_contract.swap_fixed_input(network_providers, alice, post_event)
        blockchain_controller.wait_for_tx(tx_post)

        TransactionAssertions.assert_transaction_failed(
            tx_post, network_providers.proxy, expected_error="Swap is not enabled"
        )
        logger.info("Swap correctly rejected after pause")

        # CLEANUP: Resume the contract for other tests
        deployer_account.sync_nonce(network_providers.proxy)
        tx_resume = pair_contract.resume(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_resume)
        TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
        logger.info("Contract resumed (cleanup)")

        logger.info("Test passed: Pair correctly transitions from active to inactive")

    @pytest.mark.happy_path
    def test_pair_state_inactive_operations_fail(
        self,
        pair_contract: PairContract,
        alice: Account,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: All user operations fail when pair is paused

        GIVEN: Pair contract paused via setStateActiveNoSwaps
        WHEN: Users attempt swap, add liquidity, remove liquidity
        THEN:
            - Swap fails
            - Add liquidity may still work (activeNoSwaps allows it)
            - Reserves unchanged for failed operations
            - No state corruption from rejected transactions

        SECURITY: A paused contract must reject swap operations consistently.
                  Partial operation acceptance during pause could lead to
                  inconsistent state.
        """
        logger.info("TEST: All swap operations fail when pair is paused")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        # Pause the contract
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = pair_contract.set_active_no_swaps(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Pair contract paused")

        reserves_paused = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        try:
            # Test 1: Swap should fail
            swap_amount = nominated_amount(5)
            ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

            swap_event = SwapFixedInputEvent(
                tokenA=pair_contract.firstToken,
                amountA=swap_amount,
                tokenB=pair_contract.secondToken,
                amountBmin=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx_swap = pair_contract.swap_fixed_input(network_providers, alice, swap_event)
            blockchain_controller.wait_for_tx(tx_swap)

            TransactionAssertions.assert_transaction_failed(
                tx_swap, network_providers.proxy, expected_error="Swap is not enabled"
            )
            logger.info("1. Swap correctly rejected when paused")

            # Verify reserves unchanged after failed swap
            reserves_after_swap = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after_swap[0] == reserves_paused[0], "First reserve changed after failed swap"
            assert reserves_after_swap[1] == reserves_paused[1], "Second reserve changed after failed swap"

            # Test 2: Swap in reverse direction should also fail
            ensure_esdt_amounts(alice, {pair_contract.secondToken: swap_amount})

            swap_rev_event = SwapFixedInputEvent(
                tokenA=pair_contract.secondToken,
                amountA=swap_amount,
                tokenB=pair_contract.firstToken,
                amountBmin=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx_swap_rev = pair_contract.swap_fixed_input(network_providers, alice, swap_rev_event)
            blockchain_controller.wait_for_tx(tx_swap_rev)

            TransactionAssertions.assert_transaction_failed(
                tx_swap_rev, network_providers.proxy, expected_error="Swap is not enabled"
            )
            logger.info("2. Reverse swap correctly rejected when paused")

            # Test 3: Add liquidity should WORK in ActiveNoSwaps state
            pair_data_fetcher = PairContractDataFetcher(
                Address.new_from_bech32(pair_contract.address),
                network_providers.proxy.url
            )
            add_amount = nominated_amount(10)
            equivalent = pair_data_fetcher.get_data(
                "getEquivalent",
                [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount)]
            )
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: add_amount,
                pair_contract.secondToken: equivalent
            })

            add_event = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=add_amount,
                amountAmin=1,
                tokenB=pair_contract.secondToken,
                amountB=equivalent,
                amountBmin=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx_add = pair_contract.add_liquidity(network_providers, alice, add_event)
            blockchain_controller.wait_for_tx(tx_add)
            TransactionAssertions.assert_transaction_success(tx_add, network_providers.proxy)
            logger.info("3. Add liquidity correctly ALLOWED in ActiveNoSwaps state")

            # Test 4: Remove liquidity should WORK in ActiveNoSwaps state
            lp_token = Token(pair_contract.lpToken, 0)
            alice_lp = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
            reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            total_supply = reserves_now[2]
            MINIMUM_LIQUIDITY = 1000

            # Must leave at least MINIMUM_LIQUIDITY in the pool after removal
            max_removable = min(alice_lp, total_supply - MINIMUM_LIQUIDITY)
            remove_amount = max_removable // 10 if max_removable > 0 else 0

            if remove_amount > 0:
                remove_event = RemoveLiquidityEvent(
                    amount=remove_amount,
                    tokenA=pair_contract.firstToken,
                    amountA=1,
                    tokenB=pair_contract.secondToken,
                    amountB=1
                )
                alice.sync_nonce(network_providers.proxy)
                tx_remove = pair_contract.remove_liquidity(network_providers, alice, remove_event)
                blockchain_controller.wait_for_tx(tx_remove)
                TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
                logger.info("4. Remove liquidity correctly ALLOWED in ActiveNoSwaps state")
            else:
                logger.info("4. Skipped remove liquidity test (insufficient LP or pool near minimum)")

        finally:
            # CLEANUP: Always resume the contract
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = pair_contract.resume(deployer_account, network_providers.proxy)
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Contract resumed (cleanup)")

        logger.info("Test passed: Swap operations correctly fail when paused")

    @pytest.mark.happy_path
    def test_pair_state_resume(
        self,
        pair_contract: PairContract,
        alice: Account,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: Resume paused pair, all operations work again

        GIVEN: Pair contract paused via setStateActiveNoSwaps
        WHEN: Owner calls resume
        THEN:
            - Resume transaction succeeds
            - Swaps work again
            - Add liquidity works
            - Remove liquidity works
            - k maintained throughout the pause/resume cycle

        SECURITY: Resume must fully restore contract functionality.
                  Any residual effects from the pause state would indicate
                  a state management bug.
        """
        logger.info("TEST: Resume paused pair and verify all operations work")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]

        # Pause
        deployer_account.sync_nonce(network_providers.proxy)
        tx_pause = pair_contract.set_active_no_swaps(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_pause)
        TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
        logger.info("Contract paused")

        # Resume
        deployer_account.sync_nonce(network_providers.proxy)
        tx_resume = pair_contract.resume(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_resume)
        TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
        logger.info("Contract resumed")

        # Verify reserves unchanged during pause/resume cycle
        reserves_after_resume = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_after_resume[0] == reserves_initial[0], "First reserve changed during pause/resume"
        assert reserves_after_resume[1] == reserves_initial[1], "Second reserve changed during pause/resume"

        # Test 1: Swap works
        swap_amount = nominated_amount(10)
        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})

        swap_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_swap = pair_contract.swap_fixed_input(network_providers, alice, swap_event)
        blockchain_controller.wait_for_tx(tx_swap)
        TransactionAssertions.assert_transaction_success(tx_swap, network_providers.proxy)
        logger.info("1. Swap works after resume")

        k_after_swap = PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_initial, network_providers.proxy
        )

        # Test 2: Add liquidity works
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        add_amount = nominated_amount(50)
        equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount,
            pair_contract.secondToken: equivalent
        })

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount,
            amountAmin=int(add_amount * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=equivalent,
            amountBmin=int(equivalent * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_add = pair_contract.add_liquidity(network_providers, alice, add_event)
        blockchain_controller.wait_for_tx(tx_add)
        TransactionAssertions.assert_transaction_success(tx_add, network_providers.proxy)
        logger.info("2. Add liquidity works after resume")

        # Test 3: Remove liquidity works
        lp_token = Token(pair_contract.lpToken, 0)
        alice_lp = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        if alice_lp > 0:
            remove_amount = alice_lp // 10  # Remove 10% of Alice's LP
            if remove_amount > 0:
                reserves_now = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
                expected_first = remove_amount * reserves_now[0] // reserves_now[2]
                expected_second = remove_amount * reserves_now[1] // reserves_now[2]

                remove_event = RemoveLiquidityEvent(
                    amount=remove_amount,
                    tokenA=pair_contract.firstToken,
                    amountA=int(expected_first * 0.90),
                    tokenB=pair_contract.secondToken,
                    amountB=int(expected_second * 0.90)
                )
                alice.sync_nonce(network_providers.proxy)
                tx_remove = pair_contract.remove_liquidity(network_providers, alice, remove_event)
                blockchain_controller.wait_for_tx(tx_remove)
                TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
                logger.info("3. Remove liquidity works after resume")

        logger.info("Test passed: All operations work correctly after resume")
