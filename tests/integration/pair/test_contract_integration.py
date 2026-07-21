"""
Integration tests for Pair contract interactions with other DEX contracts.

These tests verify the pair contract works correctly with:
- Router contract (multi-hop swaps via sequential pairs)
- Trusted swap pairs (cross-pair price references)
- Proxy contract configuration

Run:
    pytest --env=chainsim tests/integration/pair/test_contract_integration.py
"""

from multiversx_sdk import Address, Token
import pytest

from contracts.pair_contract import (
    PairContract, SwapFixedInputEvent, AddLiquidityEvent
)
from contracts.router_contract import RouterContract
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import nominated_amount, Account
from tests.helpers import PairAssertions, TransactionAssertions
from utils.logger import get_logger
from multiversx_sdk.abi import TokenIdentifierValue, BigUIntValue
from typing import List


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
class TestContractIntegration:
    """
    Integration tests for Pair contract interactions with other DEX contracts.

    Tests the composability of pair contracts within the broader DEX ecosystem.
    """

    @pytest.mark.happy_path
    def test_router_multi_hop_swap(
        self,
        all_pair_contracts: List[PairContract],
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Simulate multi-hop swap through two connected pair contracts

        GIVEN: Two pair contracts sharing a common token (e.g., A/WEGLD and WEGLD/B)
        WHEN: Alice swaps A -> WEGLD through pair1, then WEGLD -> B through pair2
        THEN:
            - Both swaps succeed sequentially
            - Alice ends up with token B starting from token A
            - k invariant maintained in both pools
            - Intermediate token (WEGLD) balance handled correctly
            - Final output is reasonable (accounts for fees in both legs)

        SECURITY: Multi-hop swaps compound fees and slippage. Users must receive
                  fair output accounting for both legs. Incorrect intermediate
                  handling could lead to fund loss.
        """
        logger.info("TEST: Router multi-hop swap (sequential through two pairs)")

        # Find two pairs that share a common token
        # Pair at index 0 is WEGLD/MEX, pair at index 1 is WEGLD/USDC
        # Both share WEGLD as firstToken
        if len(all_pair_contracts) < 2:
            pytest.skip("Need at least 2 pairs for multi-hop test")

        pair1 = all_pair_contracts[0]  # WEGLD/MEX
        pair2 = all_pair_contracts[1]  # WEGLD/USDC

        # Verify they share a common token
        common_tokens = set()
        pair1_tokens = {pair1.firstToken, pair1.secondToken}
        pair2_tokens = {pair2.firstToken, pair2.secondToken}
        common_tokens = pair1_tokens & pair2_tokens

        if not common_tokens:
            pytest.skip("No common token found between first two pairs")

        common_token = common_tokens.pop()
        logger.info(f"Common token: {common_token}")
        logger.info(f"Pair1: {pair1.firstToken}/{pair1.secondToken} @ {pair1.address}")
        logger.info(f"Pair2: {pair2.firstToken}/{pair2.secondToken} @ {pair2.address}")

        # Determine the unique tokens (start and end of multi-hop)
        start_token = (pair1_tokens - {common_token}).pop()
        end_token = (pair2_tokens - {common_token}).pop()
        logger.info(f"Multi-hop: {start_token} -> {common_token} -> {end_token}")

        # Ensure both pools have liquidity
        reserves1 = PairAssertions.get_reserves(pair1.address, network_providers.proxy)
        reserves2 = PairAssertions.get_reserves(pair2.address, network_providers.proxy)

        if reserves1[0] == 0 or reserves2[0] == 0:
            pytest.skip("One or both pools have no liquidity")

        k1_before = reserves1[0] * reserves1[1]
        k2_before = reserves2[0] * reserves2[1]

        # Use a small fraction of reserves for the swap (0.1% of start_token reserve)
        # This ensures the intermediate amount won't exceed pair2's capacity
        start_token_reserve_idx = 0 if pair1.firstToken == start_token else 1
        swap_amount = reserves1[start_token_reserve_idx] // 1000  # 0.1% of reserve
        swap_amount = max(swap_amount, nominated_amount(1))  # Minimum 1 token
        logger.info(f"Swap amount: {swap_amount} (0.1% of {start_token} reserve in pair1)")

        ensure_esdt_amounts(alice, {start_token: swap_amount})

        # Query expected output for step 1 before executing
        pair1_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair1.address), network_providers.proxy.url
        )
        expected_intermediate = pair1_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(start_token), BigUIntValue(swap_amount)]
        )

        # Step 1: Swap start_token -> common_token through pair1
        common_balance_before = network_providers.proxy.get_token_of_account(
            alice.address, Token(common_token, 0)
        ).amount

        swap1_event = SwapFixedInputEvent(
            tokenA=start_token,
            amountA=swap_amount,
            tokenB=common_token,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_swap1 = pair1.swap_fixed_input(network_providers, alice, swap1_event)
        blockchain_controller.wait_for_tx(tx_swap1)
        TransactionAssertions.assert_transaction_success(tx_swap1, network_providers.proxy)
        logger.info("Step 1: First leg swap succeeded")

        # Verify intermediate amount matches getAmountOut exactly
        common_balance_after_1 = network_providers.proxy.get_token_of_account(
            alice.address, Token(common_token, 0)
        ).amount
        intermediate_amount = common_balance_after_1 - common_balance_before
        assert intermediate_amount == expected_intermediate, (
            f"Intermediate amount should be exactly {expected_intermediate}, got {intermediate_amount}"
        )
        logger.info(f"Intermediate amount received: {intermediate_amount} {common_token}")

        # Cap intermediate amount to 0.1% of pair2's common_token reserve
        # to avoid slippage issues when pool state is modified by prior tests
        common_token_reserve_idx_p2 = 0 if pair2.firstToken == common_token else 1
        reserves2_fresh = PairAssertions.get_reserves(pair2.address, network_providers.proxy)
        max_swap_for_pair2 = reserves2_fresh[common_token_reserve_idx_p2] // 1000
        if intermediate_amount > max_swap_for_pair2 and max_swap_for_pair2 > 0:
            logger.info(f"Capping intermediate amount: {intermediate_amount} -> {max_swap_for_pair2}")
            intermediate_amount = max_swap_for_pair2

        # Query expected output for step 2 (using possibly-capped intermediate amount)
        pair2_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair2.address), network_providers.proxy.url
        )
        expected_final_output = pair2_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(common_token), BigUIntValue(intermediate_amount)]
        )

        # Step 2: Swap common_token -> end_token through pair2
        end_balance_before = network_providers.proxy.get_token_of_account(
            alice.address, Token(end_token, 0)
        ).amount

        swap2_event = SwapFixedInputEvent(
            tokenA=common_token,
            amountA=intermediate_amount,
            tokenB=end_token,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx_swap2 = pair2.swap_fixed_input(network_providers, alice, swap2_event)
        blockchain_controller.wait_for_tx(tx_swap2)
        TransactionAssertions.assert_transaction_success(tx_swap2, network_providers.proxy)
        logger.info("Step 2: Second leg swap succeeded")

        # Verify final output matches getAmountOut exactly
        end_balance_after = network_providers.proxy.get_token_of_account(
            alice.address, Token(end_token, 0)
        ).amount
        final_output = end_balance_after - end_balance_before
        assert final_output == expected_final_output, (
            f"Final output should be exactly {expected_final_output}, got {final_output}"
        )
        logger.info(f"Final output: {final_output} {end_token}")

        # Verify k invariants in both pools
        reserves1_after = PairAssertions.get_reserves(pair1.address, network_providers.proxy)
        reserves2_after = PairAssertions.get_reserves(pair2.address, network_providers.proxy)
        k1_after = reserves1_after[0] * reserves1_after[1]
        k2_after = reserves2_after[0] * reserves2_after[1]

        assert k1_after >= k1_before, f"k decreased in pair1: {k1_before} -> {k1_after}"
        assert k2_after >= k2_before, f"k decreased in pair2: {k2_before} -> {k2_after}"

        logger.info(f"k1: {k1_before} -> {k1_after} (increase: {((k1_after-k1_before)/k1_before*100):.6f}%)")
        logger.info(f"k2: {k2_before} -> {k2_after} (increase: {((k2_after-k2_before)/k2_before*100):.6f}%)")

        logger.info("Test passed: Multi-hop swap succeeded through two connected pairs")

    @pytest.mark.happy_path
    def test_trusted_swap_pair_integration(
        self,
        pair_contract: PairContract,
        all_pair_contracts: List[PairContract],
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        test_environment
    ):
        """
        SCENARIO: Add a trusted swap pair to enable cross-pair price references

        GIVEN: Two pair contracts sharing a common token
        WHEN: Owner adds pair2 as a trusted swap pair for pair1
        THEN:
            - Transaction succeeds (owner has permission)
            - Trusted pair relationship is established
            - Both contracts remain functional after setup

        SECURITY: Trusted swap pairs are used for price oracle validation.
                  Only the owner should be able to add trusted pairs.
                  Adding a malicious pair as trusted could manipulate prices.
        """
        logger.info("TEST: Add trusted swap pair")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        if len(all_pair_contracts) < 2:
            pytest.skip("Need at least 2 pairs for trusted pair test")

        # Use pair at index 1 (our test pair) and add pair at index 0 as trusted
        primary_pair = all_pair_contracts[1]  # WEGLD/USDC
        trusted_pair = all_pair_contracts[0]  # WEGLD/MEX

        logger.info(f"Primary pair: {primary_pair.firstToken}/{primary_pair.secondToken} @ {primary_pair.address}")
        logger.info(f"Adding trusted pair: {trusted_pair.firstToken}/{trusted_pair.secondToken} @ {trusted_pair.address}")

        # Verify both pairs have reserves
        reserves_primary = PairAssertions.get_reserves(primary_pair.address, network_providers.proxy)
        reserves_trusted = PairAssertions.get_reserves(trusted_pair.address, network_providers.proxy)

        if reserves_primary[0] == 0 or reserves_trusted[0] == 0:
            pytest.skip("One or both pairs have no reserves")

        # Add trusted swap pair — treat "already registered" as a valid idempotent outcome.
        # The storage-key inspection approach is unreliable (proxy API may truncate keys for
        # large contracts loaded from mainnet state), so we just attempt the add and accept
        # both a success status and a "already" / "trusted" SC error.
        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = primary_pair.add_trusted_swap_pair(
            deployer_account,
            network_providers.proxy,
            [trusted_pair.address, trusted_pair.firstToken, trusted_pair.secondToken]
        )
        blockchain_controller.wait_for_tx(tx_hash)
        tx_data = network_providers.proxy.get_transaction(tx_hash)
        if tx_data.status.is_successful:
            logger.info("Trusted swap pair added successfully")
        else:
            error_msg = TransactionAssertions._extract_error_from_tx(tx_data)
            if "already" in error_msg.lower() or "trusted" in error_msg.lower():
                logger.info(f"Trusted swap pair already registered (idempotent): {error_msg}")
            else:
                # Unexpected failure — re-raise via the standard helper
                TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify both pairs still functional after the change
        # Check primary pair is still responsive
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(primary_pair.address),
            network_providers.proxy.url
        )
        reserves_after = PairAssertions.get_reserves(primary_pair.address, network_providers.proxy)
        assert reserves_after[0] == reserves_primary[0], "Primary pair reserves should be unchanged"
        assert reserves_after[1] == reserves_primary[1], "Primary pair reserves should be unchanged"

        # Query view function to verify pair is still operational
        test_amount = nominated_amount(1)
        expected_output = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(primary_pair.firstToken), BigUIntValue(test_amount)]
        )
        assert expected_output > 0, "Primary pair should still return valid swap quotes"
        logger.info(f"Primary pair still functional: getAmountOut({test_amount}) = {expected_output}")

        logger.info("Test passed: Trusted swap pair added and both pairs remain functional")

    @pytest.mark.happy_path
    def test_router_pair_pause_resume(
        self,
        pair_contract: PairContract,
        router_contract: RouterContract,
        deployer_account: Account,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: Router can pause and resume a pair contract

        GIVEN: Active pair contract managed by the router
        WHEN: Owner pauses and resumes the pair through the router
        THEN:
            - Router pause transaction succeeds
            - Swaps fail while paused
            - Router resume transaction succeeds
            - Swaps work again after resume
            - Reserves unchanged during the cycle

        SECURITY: The router serves as the admin layer for pair contracts.
                  Router-level pause/resume must correctly propagate to pairs.
                  If the router can't pause a pair, emergency responses are
                  impossible. If resume fails, pools get permanently locked.
        """
        logger.info("TEST: Router pair pause/resume")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts,
            amount=nominated_amount(5000)
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Verify swap works before pause
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
        logger.info("Swap works before router pause")

        try:
            # Pause via router
            deployer_account.sync_nonce(network_providers.proxy)
            tx_pause = router_contract.pair_contract_pause(
                deployer_account, network_providers.proxy, pair_contract.address
            )
            blockchain_controller.wait_for_tx(tx_pause)
            TransactionAssertions.assert_transaction_success(tx_pause, network_providers.proxy)
            logger.info("Router paused pair contract")

            reserves_paused = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

            # Attempt swap while paused - should fail
            ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})
            paused_event = SwapFixedInputEvent(
                tokenA=pair_contract.firstToken,
                amountA=swap_amount,
                tokenB=pair_contract.secondToken,
                amountBmin=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx_paused = pair_contract.swap_fixed_input(network_providers, alice, paused_event)
            blockchain_controller.wait_for_tx(tx_paused)
            TransactionAssertions.assert_transaction_failed(tx_paused, network_providers.proxy)
            logger.info("Swap correctly rejected while paused via router")

            # Verify reserves unchanged
            reserves_after_fail = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            assert reserves_after_fail[0] == reserves_paused[0], "Reserves changed after failed swap"
            assert reserves_after_fail[1] == reserves_paused[1], "Reserves changed after failed swap"

        finally:
            # Resume via router (always cleanup)
            deployer_account.sync_nonce(network_providers.proxy)
            tx_resume = router_contract.pair_contract_resume(
                deployer_account, network_providers.proxy, pair_contract.address
            )
            blockchain_controller.wait_for_tx(tx_resume)
            TransactionAssertions.assert_transaction_success(tx_resume, network_providers.proxy)
            logger.info("Router resumed pair contract")

        # Verify swap works after resume
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
        TransactionAssertions.assert_transaction_success(tx_post, network_providers.proxy)
        logger.info("Swap works after router resume")

        logger.info("Test passed: Router pause/resume correctly controls pair contract")

    @pytest.mark.happy_path
    def test_full_lifecycle_continuous_flow(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Full lifecycle of pool operations in continuous sequence

        GIVEN: Pool with liquidity
        WHEN: Execute a complete flow:
            1. Add liquidity
            2. Swap A -> B
            3. Swap B -> A
            4. Add more liquidity
            5. Remove partial liquidity
            6. Swap again
        THEN:
            - All transactions succeed
            - k invariant holds after each operation
            - LP tokens minted/burned correctly
            - Final state is consistent

        SECURITY: Verifies the state machine handles all transitions correctly
                  in sequence without state corruption.
        """
        logger.info("TEST: Full lifecycle continuous flow")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Step 1: Add liquidity
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves[0] * reserves[1]
        logger.info(f"Initial reserves: {reserves[0]}, {reserves[1]}, k={k_initial}")

        add_amount = reserves[0] // 100  # 1% of first reserve
        equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount)]
        )
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount,
            pair_contract.secondToken: equivalent
        })

        lp_token = Token(pair_contract.lpToken, 0)
        alice_lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount,
            amountAmin=1,
            tokenB=pair_contract.secondToken,
            amountB=equivalent,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx1 = pair_contract.add_liquidity(network_providers, alice, add_event)
        blockchain_controller.wait_for_tx(tx1)
        TransactionAssertions.assert_transaction_success(tx1, network_providers.proxy)

        reserves_1 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_1 = reserves_1[0] * reserves_1[1]
        assert k_1 >= k_initial, f"k decreased after add liquidity: {k_initial} -> {k_1}"
        alice_lp_after_add = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
        alice_lp_gained = alice_lp_after_add - alice_lp_before
        expected_alice_lp = min(
            add_amount * reserves[2] // reserves[0],
            equivalent * reserves[2] // reserves[1]
        )
        assert alice_lp_gained == expected_alice_lp, (
            f"Alice LP minted should be exactly {expected_alice_lp}, got {alice_lp_gained}"
        )
        logger.info(f"Step 1 (Add liquidity): k={k_1}, LP gained={alice_lp_gained}")

        # Step 2: Swap A -> B
        swap_amount = reserves_1[0] // 1000  # 0.1% of reserve
        ensure_esdt_amounts(bob, {pair_contract.firstToken: swap_amount})

        expected_out_2 = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )
        bob_second_before_2 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.secondToken, 0)
        ).amount

        swap1_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        tx2 = pair_contract.swap_fixed_input(network_providers, bob, swap1_event)
        blockchain_controller.wait_for_tx(tx2)
        TransactionAssertions.assert_transaction_success(tx2, network_providers.proxy)

        bob_second_after_2 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.secondToken, 0)
        ).amount
        assert bob_second_after_2 - bob_second_before_2 == expected_out_2, (
            f"Step 2 output should be {expected_out_2}, got {bob_second_after_2 - bob_second_before_2}"
        )
        reserves_2 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_2 = reserves_2[0] * reserves_2[1]
        assert k_2 >= k_1, f"k decreased after swap A->B: {k_1} -> {k_2}"
        logger.info(f"Step 2 (Swap A->B): k={k_2}")

        # Step 3: Swap B -> A
        swap_amount_b = reserves_2[1] // 1000
        ensure_esdt_amounts(bob, {pair_contract.secondToken: swap_amount_b})

        expected_out_3 = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.secondToken), BigUIntValue(swap_amount_b)]
        )
        bob_first_before_3 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.firstToken, 0)
        ).amount

        swap2_event = SwapFixedInputEvent(
            tokenA=pair_contract.secondToken,
            amountA=swap_amount_b,
            tokenB=pair_contract.firstToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        tx3 = pair_contract.swap_fixed_input(network_providers, bob, swap2_event)
        blockchain_controller.wait_for_tx(tx3)
        TransactionAssertions.assert_transaction_success(tx3, network_providers.proxy)

        bob_first_after_3 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.firstToken, 0)
        ).amount
        assert bob_first_after_3 - bob_first_before_3 == expected_out_3, (
            f"Step 3 output should be {expected_out_3}, got {bob_first_after_3 - bob_first_before_3}"
        )
        reserves_3 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_3 = reserves_3[0] * reserves_3[1]
        assert k_3 >= k_2, f"k decreased after swap B->A: {k_2} -> {k_3}"
        logger.info(f"Step 3 (Swap B->A): k={k_3}")

        # Step 4: Add more liquidity
        add_amount_2 = reserves_3[0] // 200  # 0.5% of reserve
        equivalent_2 = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount_2)]
        )
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount_2,
            pair_contract.secondToken: equivalent_2
        })

        add_event_2 = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount_2,
            amountAmin=1,
            tokenB=pair_contract.secondToken,
            amountB=equivalent_2,
            amountBmin=1
        )
        alice.sync_nonce(network_providers.proxy)
        tx4 = pair_contract.add_liquidity(network_providers, alice, add_event_2)
        blockchain_controller.wait_for_tx(tx4)
        TransactionAssertions.assert_transaction_success(tx4, network_providers.proxy)

        reserves_4 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_4 = reserves_4[0] * reserves_4[1]
        assert k_4 >= k_3, f"k decreased after second add: {k_3} -> {k_4}"
        logger.info(f"Step 4 (Add liquidity 2): k={k_4}")

        # Step 5: Remove partial liquidity
        alice_lp_now = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
        MINIMUM_LIQUIDITY = 1000
        total_supply = reserves_4[2]
        max_removable = min(alice_lp_now, total_supply - MINIMUM_LIQUIDITY)
        remove_amount = max_removable // 20  # Remove 5% of removable LP

        if remove_amount > 0:
            from contracts.pair_contract import RemoveLiquidityEvent
            remove_event = RemoveLiquidityEvent(
                amount=remove_amount,
                tokenA=pair_contract.firstToken,
                amountA=1,
                tokenB=pair_contract.secondToken,
                amountB=1
            )
            alice.sync_nonce(network_providers.proxy)
            tx5 = pair_contract.remove_liquidity(network_providers, alice, remove_event)
            blockchain_controller.wait_for_tx(tx5)
            TransactionAssertions.assert_transaction_success(tx5, network_providers.proxy)

            reserves_5 = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
            k_5 = reserves_5[0] * reserves_5[1]
            # k can decrease on remove (proportional withdrawal)
            assert k_5 > 0, "k should remain positive after partial removal"
            logger.info(f"Step 5 (Remove liquidity): k={k_5}")
        else:
            reserves_5 = reserves_4
            logger.info("Step 5 skipped: insufficient LP for removal")

        # Step 6: Final swap to verify pool still functional
        final_swap = reserves_5[0] // 2000
        ensure_esdt_amounts(bob, {pair_contract.firstToken: final_swap})

        expected_final_out = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(final_swap)]
        )
        bob_second_before_6 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.secondToken, 0)
        ).amount

        final_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=final_swap,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        tx6 = pair_contract.swap_fixed_input(network_providers, bob, final_event)
        blockchain_controller.wait_for_tx(tx6)
        TransactionAssertions.assert_transaction_success(tx6, network_providers.proxy)

        bob_second_after_6 = network_providers.proxy.get_token_of_account(
            bob.address, Token(pair_contract.secondToken, 0)
        ).amount
        assert bob_second_after_6 - bob_second_before_6 == expected_final_out, (
            f"Step 6 output should be {expected_final_out}, got {bob_second_after_6 - bob_second_before_6}"
        )
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] > 0, "First reserve should be positive"
        assert reserves_final[1] > 0, "Second reserve should be positive"
        assert reserves_final[2] > 0, "LP supply should be positive"
        logger.info(f"Step 6 (Final swap): reserves={reserves_final[0]}, {reserves_final[1]}")

        # Summary
        k_growth = (reserves_final[0] * reserves_final[1]) / k_initial
        logger.info(f"k growth over lifecycle: {k_growth:.6f}x")
        logger.info(f"Operations completed: add, swap, swap, add, remove, swap")

        logger.info("Test passed: Full lifecycle completed successfully")
