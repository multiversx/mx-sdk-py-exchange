"""
Integration tests for Pair contract addLiquidity endpoint.

These tests verify the add liquidity operation through black-box testing:
- Query state via view functions only
- Execute transactions via contract endpoints
- Verify state changes after transaction finalization

Test Categories:
1. Happy Path: Normal add liquidity operations
2. Edge Cases: Empty pool, imbalanced ratios, minimum amounts
3. Security: Zero amounts, slippage attacks

Run:
    pytest --env=chainsim tests/integration/pair/test_add_liquidity.py
    pytest --env=devnet tests/integration/pair/test_add_liquidity.py -m "not slow"
"""

from multiversx_sdk import Address, find_events_by_identifier, Token
import pytest

import config
from contracts.builtin_contracts import ESDTContract
from contracts.pair_contract import PairContract, AddLiquidityEvent, SwapFixedInputEvent, PairContractVersion
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import nominated_amount, Account, hex_to_string
from tests.helpers import PairAssertions, TransactionAssertions
from utils.logger import get_logger
from multiversx_sdk.abi import TokenIdentifierValue, BigUIntValue


logger = get_logger(__name__)


@pytest.mark.integration
@pytest.mark.pair
class TestPairAddLiquidity:
    """
    Integration tests for Pair.addLiquidity() and Pair.addInitialLiquidity()

    Contract Endpoints Tested:
    - addInitialLiquidity(token_a, token_b) -> lp_tokens
    - addLiquidity(token_a, token_b, min_a, min_b) -> lp_tokens

    Economic Invariants Verified:
    1. Reserves increase by at least min amounts
    2. LP token supply increases
    3. Constant product (k = x * y) never decreases
    4. User receives LP tokens proportional to liquidity added
    """

    @pytest.mark.happy_path
    def test_add_initial_liquidity_empty_pool(
        self,
        router_contract,
        alice: Account,
        network_providers,
        blockchain_controller,
        test_environment
    ):
        """
        SCENARIO: Alice adds initial liquidity to a freshly deployed empty pool

        GIVEN: Fresh pair contract with zero reserves (deployed via router)
        WHEN: Alice adds 1000 token_a and 1000 token_b
        THEN:
            - Reserves increase to (1000, 1000)
            - LP token supply > 0
            - Alice receives LP tokens
            - Transaction succeeds

        SECURITY: Initial liquidity sets the price ratio for the pool.
                  First LP provider has significant power over initial price.
        """
        logger.info("TEST: Add initial liquidity to empty pool")

        # 0. Ensure Alice has sufficient EGLD for tx fees and token issuance
        # Token issuance costs 0.05 EGLD per token, so we need at least 2 EGLD total
        if test_environment.supports_time_control():
            from tests.environments import ChainsimEnvironment
            if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim and alice.address:
                required_egld = nominated_amount(2)  # 2 EGLD
                logger.info(f"Funding Alice with {required_egld / 10**18} EGLD for fees")
                test_environment.chain_sim.fund_users_w_egld([alice.address.to_bech32()], required_egld)

        liquidity_amount = nominated_amount(1000)

        # 1. Issue two new test tokens
        esdt_contract = ESDTContract(config.TOKENS_CONTRACT_ADDRESS)

        # Issue first token
        alice.sync_nonce(network_providers.proxy)
        logger.info("Issuing first test token")
        tx_hash_1 = esdt_contract.issue_fungible_token(
            alice,
            network_providers.proxy,
            ["TestTokenA", "TESTA", liquidity_amount, 18]
        )
        # Wait for metachain round-trip (shard → metachain → shard callback)
        blockchain_controller.wait_for_tx(tx_hash_1, blocks=15)

        # Get first token identifier from transaction
        # Cross-shard issue events may need extra blocks to appear
        tx_data_1 = network_providers.proxy.get_transaction(tx_hash_1)
        issue_events_1 = find_events_by_identifier(tx_data_1, "issue")
        if not issue_events_1:
            blockchain_controller.wait_for_tx(tx_hash_1, blocks=10)
            tx_data_1 = network_providers.proxy.get_transaction(tx_hash_1)
            issue_events_1 = find_events_by_identifier(tx_data_1, "issue")
        assert issue_events_1, f"No 'issue' events found for token issuance tx {tx_hash_1}"
        issue_event_1 = issue_events_1[0]
        first_token = issue_event_1.topics[0].decode('utf-8') if isinstance(issue_event_1.topics[0], bytes) else str(issue_event_1.topics[0])
        logger.info(f"First token issued: {first_token}")

        # Issue second token
        alice.sync_nonce(network_providers.proxy)
        logger.info("Issuing second test token")
        tx_hash_2 = esdt_contract.issue_fungible_token(
            alice,
            network_providers.proxy,
            ["TestTokenB", "TESTB", liquidity_amount, 18]
        )
        # Wait for metachain round-trip
        blockchain_controller.wait_for_tx(tx_hash_2, blocks=15)

        # Get second token identifier from transaction
        tx_data_2 = network_providers.proxy.get_transaction(tx_hash_2)
        issue_events_2 = find_events_by_identifier(tx_data_2, "issue")
        if not issue_events_2:
            blockchain_controller.wait_for_tx(tx_hash_2, blocks=10)
            tx_data_2 = network_providers.proxy.get_transaction(tx_hash_2)
            issue_events_2 = find_events_by_identifier(tx_data_2, "issue")
        assert issue_events_2, f"No 'issue' events found for token issuance tx {tx_hash_2}"
        issue_event_2 = issue_events_2[0]
        second_token = issue_event_2.topics[0].decode('utf-8') if isinstance(issue_event_2.topics[0], bytes) else str(issue_event_2.topics[0])
        logger.info(f"Second token issued: {second_token}")

        # Deploy new pair
        alice.sync_nonce(network_providers.proxy)

        deploy_args = [
            first_token,      # first token
            second_token,     # second token
            alice.address.to_bech32() if alice.address else "",  # initial liquidity adder
            300,              # total fee percentage (3%)
            0                 # special fee percentage
        ]

        # Advance router nonce to a session-unique value to avoid deploying to an
        # address already occupied by a pair from a previous test run.
        if test_environment.supports_time_control():
            from tests.environments import ChainsimEnvironment
            if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
                test_environment.chain_sim.advance_nonce_for_deploys(router_contract.address)

        logger.info(f"Deploying new pair: {first_token} / {second_token}")
        tx_hash, pair_address = router_contract.pair_contract_deploy(alice, network_providers.proxy, deploy_args)

        if not pair_address:
            raise RuntimeError(f"Failed to deploy pair. Transaction: {tx_hash}")

        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info(f"Pair deployed at: {pair_address}")

        # Issue LP token for the new pair
        lp_token_name = f"{first_token[:4]}{second_token[:4]}LP"
        lp_token_ticker = f"{first_token[:4]}{second_token[:4]}"

        alice.sync_nonce(network_providers.proxy)
        logger.info(f"Issuing LP token: {lp_token_name} ({lp_token_ticker})")
        tx_hash = router_contract.issue_lp_token(alice, network_providers.proxy, [pair_address, lp_token_name, lp_token_ticker])
        blockchain_controller.wait_for_tx(tx_hash, blocks=8)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Get LP token identifier from pair
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_address), network_providers.proxy.url)
        lp_token_hex = pair_data_fetcher.get_data("getLpTokenIdentifier")
        lp_token = hex_to_string(lp_token_hex)
        logger.info(f"LP token issued: {lp_token}")

        # Set LP token local roles
        alice.sync_nonce(network_providers.proxy)
        logger.info("Setting LP token local roles")
        tx_hash = router_contract.set_lp_token_local_roles(alice, network_providers.proxy, pair_address)
        blockchain_controller.wait_for_tx(tx_hash, blocks=8)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Create PairContract instance for the new pair
        new_pair = PairContract(first_token, second_token, PairContractVersion.V2, lpToken=lp_token, address=pair_address)

        try:
            # 2. Capture reserves before (fresh pair, should be zero)
            old_reserves = PairAssertions.get_reserves(new_pair.address, network_providers.proxy)
            logger.info(f"Initial reserves: {old_reserves}")

            assert old_reserves[0] == 0 and old_reserves[1] == 0, (
                f"Freshly deployed pair should have zero reserves, got {old_reserves}"
            )

            event = AddLiquidityEvent(
                tokenA=first_token,
                amountA=liquidity_amount,
                amountAmin=liquidity_amount,  # No slippage for initial liquidity
                tokenB=second_token,
                amountB=liquidity_amount,
                amountBmin=liquidity_amount
            )

            # Get LP balance before
            lp_token_obj = Token(new_pair.lpToken, 0)
            lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token_obj).amount

            # 5. Sync nonce and execute transaction
            alice.sync_nonce(network_providers.proxy)
            logger.info(f"Alice adding liquidity: {liquidity_amount} of each token")

            # Use addInitialLiquidity for empty pool
            tx_hash = new_pair.add_initial_liquidity(network_providers, alice, event)

            logger.info(f"Transaction hash: {tx_hash}")

            # 6. Wait for transaction to be processed
            blockchain_controller.wait_for_tx(tx_hash)

            # 7. Verify transaction succeeded
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # 8. Verify reserves increased by exact amounts
            new_reserves = PairAssertions.get_reserves(new_pair.address, network_providers.proxy)
            logger.info(f"New reserves: {new_reserves}")

            assert new_reserves[0] - old_reserves[0] == liquidity_amount, (
                f"First reserve should increase by exactly {liquidity_amount}\n"
                f"Before: {old_reserves[0]}, After: {new_reserves[0]}"
            )
            assert new_reserves[1] - old_reserves[1] == liquidity_amount, (
                f"Second reserve should increase by exactly {liquidity_amount}\n"
                f"Before: {old_reserves[1]}, After: {new_reserves[1]}"
            )

            # 9. Verify LP tokens were minted (delta > 0)
            lp_after = network_providers.proxy.get_token_of_account(alice.address, lp_token_obj).amount
            lp_minted = lp_after - lp_before
            assert lp_minted > 0, (
                f"LP tokens should have been minted:\n"
                f"  Before: {lp_before}\n"
                f"  After: {lp_after}"
            )

            logger.info("✅ Test passed: Initial liquidity added successfully")
        finally:
            # Clear deployed pair code so chain simulator does not retain it
            # across sessions (prevents "cannot deploy over existing account"
            # when router nonce resets to mainnet value on next run).
            if test_environment.supports_time_control():
                from tests.environments import ChainsimEnvironment
                if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
                    test_environment.chain_sim.apply_states([[{
                        "address": pair_address,
                        "code": "",
                        "codeHash": "",
                        "codeMetadata": "",
                    }]])
                    logger.info(f"Cleared test pair code at {pair_address}")

    @pytest.mark.happy_path
    def test_add_liquidity_to_existing_pool(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Alice adds liquidity to pool that already has reserves

        GIVEN: Pair contract with existing reserves
        WHEN: Alice adds liquidity with 5% slippage tolerance
        THEN:
            - Reserves increase by exact amounts sent
            - LP tokens minted proportional to contribution
            - Constant product maintained
            - Pool ratio unchanged
            - Alice receives LP tokens

        SECURITY: Adding liquidity to existing pool must respect current ratio.
                  Slippage protection prevents front-running attacks.
        """
        logger.info("TEST: Add liquidity to existing pool")

        # Setup pool if needed (ensure test independence)
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })
            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)
            logger.info("Pool initialized with 1000:1000 (setup)")

        # 1. Capture state before adding liquidity
        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = reserves_before[0] * reserves_before[1]
        ratio_before = reserves_before[0] / reserves_before[1] if reserves_before[1] > 0 else 0
        logger.info(f"Reserves before: {reserves_before}, ratio: {ratio_before:.6f}")

        # 2. Calculate amounts needed for liquidity
        amount = nominated_amount(1)
        slippage = 0.05
        min_amount = int(amount * (1 - slippage))

        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
        equivalent_amount = pair_data_fetcher.get_data("getEquivalent", [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(amount)])
        equivalent_amount_min = int(equivalent_amount * (1 - slippage))

        # 3. Ensure Alice has exact amounts needed (chainsim only)
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: amount,
            pair_contract.secondToken: equivalent_amount
        })

        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=amount,
            amountAmin=min_amount,  # 5% slippage
            tokenB=pair_contract.secondToken,
            amountB=equivalent_amount,
            amountBmin=equivalent_amount_min
        )

        # Get LP token balance before
        lp_token = Token(pair_contract.lpToken, 0)
        lp_balance_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # 3. Verify transaction succeeded
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # 4. Verify reserves increased by EXACT amounts
        reserves_after = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        assert reserves_after[0] == reserves_before[0] + amount, (
            f"First reserve should increase by exactly {amount}\n"
            f"Before: {reserves_before[0]}, After: {reserves_after[0]}, Expected increase: {amount}, Actual: {reserves_after[0] - reserves_before[0]}"
        )
        assert reserves_after[1] == reserves_before[1] + equivalent_amount, (
            f"Second reserve should increase by exactly {equivalent_amount}\n"
            f"Before: {reserves_before[1]}, After: {reserves_after[1]}, Expected increase: {equivalent_amount}, Actual: {reserves_after[1] - reserves_before[1]}"
        )
        logger.info(f"✓ Reserves increased by exact amounts: +{amount}, +{equivalent_amount}")

        # 5. Verify pool ratio unchanged (within 0.1% tolerance for rounding)
        ratio_after = reserves_after[0] / reserves_after[1] if reserves_after[1] > 0 else 0
        ratio_change_pct = abs(ratio_after - ratio_before) / ratio_before if ratio_before > 0 else 0

        assert ratio_change_pct < 0.001, (
            f"Pool ratio should remain unchanged (< 0.1% change)\n"
            f"Before: {ratio_before:.6f}, After: {ratio_after:.6f}, Change: {ratio_change_pct:.4%}"
        )
        logger.info(f"✓ Pool ratio maintained: {ratio_before:.6f} → {ratio_after:.6f} (change: {ratio_change_pct:.6%})")

        # 6. CRITICAL: Verify constant product invariant
        k_after = PairAssertions.assert_constant_product_holds(
            pair_contract.address,
            k_before,
            network_providers.proxy
        )
        logger.info(f"✓ Constant product: {k_before} → {k_after}")

        # 7. Verify LP tokens minted and Alice received exactly the expected amount
        lp_balance_after = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
        lp_minted = lp_balance_after - lp_balance_before

        # LP minted = min(amountA * lp_supply / reserveA, amountB * lp_supply / reserveB)
        expected_lp_minted = min(
            amount * reserves_before[2] // reserves_before[0],
            equivalent_amount * reserves_before[2] // reserves_before[1]
        )
        assert lp_minted == expected_lp_minted, (
            f"LP tokens minted should be exactly {expected_lp_minted}, got {lp_minted}"
        )
        logger.info(f"✓ LP tokens minted: {lp_minted} (expected {expected_lp_minted})")

        logger.info("✅ Test passed: Liquidity added to existing pool successfully")

    @pytest.mark.edge_case
    @pytest.mark.parametrize("slippage_pct", [0.01, 0.05, 0.10, 0.50])
    def test_add_liquidity_various_slippage(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        slippage_pct: float
    ):
        """
        SCENARIO: Test add liquidity with various slippage tolerances

        GIVEN: Pair contract with reserves
        WHEN: Alice adds liquidity with different slippage tolerances
        THEN:
            - Transaction succeeds if pool ratio within tolerance
            - Reserves increase appropriately
            - LP tokens minted correctly

        SECURITY: Slippage tolerance protects against front-running.
                  Too high tolerance = vulnerable to sandwich attacks.
                  Too low tolerance = transaction may fail on price movement.

        Parameterized:
            1%  - Very strict (may fail on normal price movement)
            5%  - Standard (recommended for most users)
            10% - Loose (acceptable for volatile pairs)
            50% - Very loose (vulnerable to attacks)
        """
        logger.info(f"TEST: Add liquidity with {slippage_pct:.1%} slippage tolerance")

        # Setup: Ensure pool has liquidity
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(10000)

            # Fund for setup
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)
            logger.info("Pool initialized with liquidity (setup)")

        # Get fresh reserves
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_before = old_reserves[0] * old_reserves[1]

        # Calculate amounts for liquidity with slippage using getEquivalent
        amount = nominated_amount(100)
        min_amount = int(amount * (1 - slippage_pct))

        # Get equivalent amount for second token based on pool ratio
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
        equivalent_amount = pair_data_fetcher.get_data("getEquivalent", [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(amount)])
        equivalent_amount_min = int(equivalent_amount * (1 - slippage_pct))

        # Fund Alice with exact amounts needed
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: amount,
            pair_contract.secondToken: equivalent_amount
        })

        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=amount,
            amountAmin=min_amount,
            tokenB=pair_contract.secondToken,
            amountB=equivalent_amount,
            amountBmin=equivalent_amount_min
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Verify success
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        # Verify reserves increased by exact amounts
        new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert new_reserves[0] - old_reserves[0] == amount, (
            f"First reserve should increase by exactly {amount}\n"
            f"Before: {old_reserves[0]}, After: {new_reserves[0]}, Delta: {new_reserves[0] - old_reserves[0]}"
        )
        assert new_reserves[1] - old_reserves[1] == equivalent_amount, (
            f"Second reserve should increase by exactly {equivalent_amount}\n"
            f"Before: {old_reserves[1]}, After: {new_reserves[1]}, Delta: {new_reserves[1] - old_reserves[1]}"
        )

        # Verify constant product
        PairAssertions.assert_constant_product_holds(
            pair_contract.address,
            k_before,
            network_providers.proxy
        )

        logger.info(f"✅ Test passed: Slippage {slippage_pct:.1%} worked correctly")

    @pytest.mark.edge_case
    @pytest.mark.slow
    def test_add_liquidity_minimum_amounts(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Add liquidity with minimum possible amounts

        GIVEN: Pair contract initialized
        WHEN: Alice adds liquidity with very small amounts (1 unit)
        THEN:
            - Transaction succeeds (or fails gracefully if below minimum)
            - If succeeds, reserves increase by at least 1
            - No integer overflow/underflow

        SECURITY: Tests boundary conditions for integer arithmetic.
                  Ensures contract handles dust amounts correctly.
        """
        logger.info("TEST: Add liquidity with minimum amounts (1 unit)")

        # Setup pool if needed
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)

            # Fund for setup
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)

        # Try adding minimum amount (1 unit = 1 token without decimals)
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        min_amount = 1

        # Get equivalent amount for second token based on pool ratio
        pair_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
        equivalent_amount = pair_data_fetcher.get_data("getEquivalent", [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(min_amount)])

        # Fund Alice with exact minimum amounts
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: min_amount,
            pair_contract.secondToken: equivalent_amount
        })

        # Capture LP balance before
        lp_token_obj = Token(pair_contract.lpToken, 0)
        lp_balance_before = network_providers.proxy.get_token_of_account(alice.address, lp_token_obj).amount

        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=min_amount,
            amountAmin=min_amount,
            tokenB=pair_contract.secondToken,
            amountB=equivalent_amount,
            amountBmin=equivalent_amount
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Check if transaction succeeded or failed
        tx_result = network_providers.proxy.get_transaction(tx_hash)

        if tx_result.status.is_successful:
            # If transaction succeeded, verify exact state changes
            logger.info("Transaction succeeded with minimum amounts")

            new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

            # Reserves should increase by EXACT amounts (no approximation for such small values)
            assert new_reserves[0] == old_reserves[0] + min_amount, (
                f"First reserve should increase by exactly {min_amount}\n"
                f"Before: {old_reserves[0]}, After: {new_reserves[0]}, Actual increase: {new_reserves[0] - old_reserves[0]}"
            )
            assert new_reserves[1] == old_reserves[1] + equivalent_amount, (
                f"Second reserve should increase by exactly {equivalent_amount}\n"
                f"Before: {old_reserves[1]}, After: {new_reserves[1]}, Actual increase: {new_reserves[1] - old_reserves[1]}"
            )

            # Verify LP tokens were minted (delta > 0)
            lp_balance_after = network_providers.proxy.get_token_of_account(alice.address, lp_token_obj).amount
            lp_minted = lp_balance_after - lp_balance_before
            assert lp_minted > 0, "LP tokens should be minted even for minimum amounts"

            logger.info(f"✓ Reserves increased by: {min_amount}, {equivalent_amount}")
            logger.info(f"✓ LP tokens minted: {lp_minted}")
            logger.info("✅ Test passed: Minimum amount add liquidity succeeded")

        else:
            # If transaction failed, verify it's the CORRECT error
            error_msg = TransactionAssertions._extract_error_from_tx(tx_result)
            logger.info(f"Transaction failed as expected: {error_msg}")

            # Verify it's a legitimate minimum liquidity error, not some other error
            valid_errors = [
                "insufficient",
                "minimum",
                "too small",
                "below threshold",
                "invalid NFT quantity"
            ]

            assert any(err.lower() in error_msg.lower() for err in valid_errors), (
                f"Transaction failed but with unexpected error.\n"
                f"Expected one of: {valid_errors}\n"
                f"Got: {error_msg}"
            )

            logger.info("✅ Test passed: Minimum amount correctly rejected with appropriate error")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_add_liquidity_zero_amounts(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Attempt to add liquidity with zero amounts (negative test)

        GIVEN: Pair contract with existing liquidity
        WHEN: Alice attempts to add 0 tokens of both assets
        THEN:
            - Transaction should FAIL
            - Error indicates zero amounts not allowed
            - No state changes (reserves unchanged)

        SECURITY: Contract must validate input amounts.
                  Zero amounts could break LP token calculations.
        """
        logger.info("TEST: Add liquidity with zero amounts (should fail)")

        # Setup pool if needed
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)

        # Capture state before failed attempt
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Attempt to add zero amounts
        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=0,  # ZERO
            amountAmin=0,
            tokenB=pair_contract.secondToken,
            amountB=0,  # ZERO
            amountBmin=0
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Verify transaction FAILED
        TransactionAssertions.assert_transaction_failed(
            tx_hash,
            network_providers.proxy,
            expected_error="invalid NFT quantity for token"  # Expected error contains "zero"
        )

        # Verify reserves unchanged
        new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert new_reserves == old_reserves, (
            f"Reserves should be unchanged after failed transaction:\n"
            f"  Before: {old_reserves}\n"
            f"  After: {new_reserves}"
        )

        logger.info("✅ Test passed: Zero amounts correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_add_liquidity_single_token(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Attempt to add only one token (negative test)

        GIVEN: Pair contract with existing liquidity
        WHEN: Alice sends only token A (0 of token B)
        THEN:
            - Transaction should FAIL
            - Error indicates both tokens required
            - No state changes

        SECURITY: Both tokens must be provided for liquidity addition.
                  Single-sided liquidity could break pool invariants.
        """
        logger.info("TEST: Add liquidity with single token (should fail)")

        # Setup pool if needed
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)

        # Capture state before failed attempt
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Fund Alice with only first token
        amount = nominated_amount(100)
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: amount
        })

        # Attempt to add only first token (zero second token)
        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=amount,
            amountAmin=amount,
            tokenB=pair_contract.secondToken,
            amountB=0,  # ZERO - only sending first token
            amountBmin=0
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Verify transaction FAILED
        TransactionAssertions.assert_transaction_failed(
            tx_hash,
            network_providers.proxy,
            expected_error="invalid NFT quantity for token"  # Expected error about insufficient tokens
        )

        # Verify reserves unchanged
        new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert new_reserves == old_reserves, (
            f"Reserves should be unchanged after failed transaction:\n"
            f"  Before: {old_reserves}\n"
            f"  After: {new_reserves}"
        )

        logger.info("✅ Test passed: Single token correctly rejected")

    @pytest.mark.edge_case
    @pytest.mark.security
    def test_add_liquidity_wrong_token_order(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Send tokens in reversed order (negative test)

        GIVEN: Pair contract with tokens (TOKEN_A, TOKEN_B)
        WHEN: Alice sends tokens in order (TOKEN_B, TOKEN_A)
        THEN:
            - Transaction should ALWAYS FAIL
            - Error should indicate bad payment tokens
            - Reserves should remain unchanged
            - If transaction succeeds, test FAILS (indicates pair bug)

        SECURITY: Token order confusion could lead to incorrect ratios.
                  Contract must enforce correct token order.
        """
        logger.info("TEST: Add liquidity with wrong token order")

        # Setup pool if needed
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)

        # Capture state before attempt
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        # Calculate amounts using getEquivalent
        amount = nominated_amount(100)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        equivalent_amount = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(amount)]
        )

        # Fund Alice with both tokens
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: amount,
            pair_contract.secondToken: equivalent_amount
        })

        # Send tokens in REVERSED order (second token as first, first as second)
        event = AddLiquidityEvent(
            tokenA=pair_contract.secondToken,  # REVERSED
            amountA=equivalent_amount,
            amountAmin=int(equivalent_amount * 0.95),
            tokenB=pair_contract.firstToken,   # REVERSED
            amountB=amount,
            amountBmin=int(amount * 0.95)
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Transaction must ALWAYS fail with wrong token order
        logger.info("Verifying transaction failed with wrong token order")
        TransactionAssertions.assert_transaction_failed(
            tx_hash,
            network_providers.proxy,
            expected_error="Bad payment tokens"
        )

        # Verify reserves unchanged (no state mutation should occur)
        new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert new_reserves == old_reserves, "Reserves should be unchanged after failed transaction"

        logger.info("✅ Test passed: Wrong token order correctly rejected")

    @pytest.mark.edge_case
    def test_add_liquidity_imbalanced_amounts(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Add liquidity with imbalanced token amounts

        GIVEN: Pool with existing reserves at some ratio
        WHEN: Alice sends full tokenA + half of required tokenB (imbalanced)
        THEN:
            - Transaction succeeds
            - Contract uses only proportional amounts
            - Excess tokenA returned to Alice
            - Reserves increase proportionally
            - Pool ratio unchanged

        SECURITY: Contract must handle imbalanced inputs gracefully
                  and return excess without loss of funds.
        """
        logger.info("TEST: Add liquidity with imbalanced amounts")

        # Setup pool if needed
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        if reserves[0] == 0:
            setup_amount = nominated_amount(1000)
            ensure_esdt_amounts(alice, {
                pair_contract.firstToken: setup_amount,
                pair_contract.secondToken: setup_amount
            })

            event_setup = AddLiquidityEvent(
                tokenA=pair_contract.firstToken,
                amountA=setup_amount,
                amountAmin=setup_amount,
                tokenB=pair_contract.secondToken,
                amountB=setup_amount,
                amountBmin=setup_amount
            )
            alice.sync_nonce(network_providers.proxy)
            tx = pair_contract.add_initial_liquidity(network_providers, alice, event_setup)
            blockchain_controller.wait_for_tx(tx)

        # Capture state before imbalanced add
        old_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

        logger.info(f"Initial pool reserves: first={old_reserves[0]}, second={old_reserves[1]}, LP={old_reserves[2]}")

        # Choose a specific amount of tokenA
        amount_first = nominated_amount(100)

        # Calculate equivalent tokenB needed for this tokenA
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        full_equivalent = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(amount_first)]
        )

        # Use only HALF of the required tokenB (imbalanced!)
        amount_second = full_equivalent // 2

        logger.info(f"Imbalanced liquidity: first={amount_first}, second={amount_second}")
        logger.info(f"Full equivalent would be: {full_equivalent}")
        logger.info(f"Sending only half: {amount_second} (imbalance factor: 2x)")

        # Fund Alice with imbalanced amounts
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: amount_first,
            pair_contract.secondToken: amount_second
        })

        # Get Alice's initial token balances
        token_first = Token(pair_contract.firstToken, 0)
        token_second = Token(pair_contract.secondToken, 0)
        old_alice_balance_first = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        old_alice_balance_second = network_providers.proxy.get_token_of_account(alice.address, token_second).amount
        logger.info(f"Alice initial balances: first={old_alice_balance_first}, second={old_alice_balance_second}")


        # Calculate what contract SHOULD actually use (proportional to the limiting token)
        # Since amount_second is half, contract should only use half of amount_first
        expected_first_used = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.secondToken), BigUIntValue(amount_second)]
        )
        expected_second_used = amount_second
        expected_excess_first = amount_first - expected_first_used

        logger.info(f"Expected contract to use: first={expected_first_used}, second={expected_second_used}")
        logger.info(f"Expected excess returned: {expected_excess_first} tokenA")

        # Add imbalanced liquidity with reasonable slippage
        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=amount_first,
            amountAmin=int(expected_first_used * 0.95),  # 5% slippage on what will actually be used
            tokenB=pair_contract.secondToken,
            amountB=amount_second,
            amountBmin=int(amount_second * 0.95)
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Verify transaction succeeded
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info("✓ Transaction succeeded")

        # Verify reserves increased proportionally (not by imbalanced amounts)
        new_reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        actual_first_added = new_reserves[0] - old_reserves[0]
        actual_second_added = new_reserves[1] - old_reserves[1]

        logger.info(f"New reserves: first={new_reserves[0]}, second={new_reserves[1]}, LP={new_reserves[2]}")
        logger.info(f"Actual amounts added: first={actual_first_added}, second={actual_second_added}")

        # Verify proportional addition (contract should use only what maintains ratio)
        tolerance = nominated_amount(5)  # Allow 5 token units tolerance for rounding
        assert abs(actual_first_added - expected_first_used) <= tolerance, (
            f"First token added should be ~{expected_first_used}, got {actual_first_added}\n"
            f"Difference: {abs(actual_first_added - expected_first_used)}"
        )
        assert abs(actual_second_added - expected_second_used) <= tolerance, (
            f"Second token added should be ~{expected_second_used}, got {actual_second_added}\n"
            f"Difference: {abs(actual_second_added - expected_second_used)}"
        )
        logger.info("✓ Contract used proportional amounts")

        # Verify Alice received excess tokenA back
        new_alice_balance_first = network_providers.proxy.get_token_of_account(alice.address, token_first).amount
        new_alice_balance_second = network_providers.proxy.get_token_of_account(alice.address, token_second).amount

        # Calculate net change in Alice's balances
        alice_first_change = new_alice_balance_first - old_alice_balance_first
        alice_second_change = new_alice_balance_second - old_alice_balance_second

        logger.info(f"Alice final balances: first={new_alice_balance_first}, second={new_alice_balance_second}")
        logger.info(f"Alice balance changes: first={alice_first_change}, second={alice_second_change}")

        # Alice should have received excess first token back
        # She started with old_alice_balance_first, sent amount_first to contract,
        # and got excess back. Net spent = amount actually used by contract.
        alice_first_spent = old_alice_balance_first - new_alice_balance_first
        assert abs(alice_first_spent - expected_first_used) <= tolerance, (
            f"Alice should have spent ~{expected_first_used} tokenA (net).\n"
            f"Actually spent: {alice_first_spent}\n"
            f"Difference: {abs(alice_first_spent - expected_first_used)}"
        )
        logger.info("✓ Excess tokenA returned to Alice")

        # Verify pool ratio is maintained (unchanged)
        ratio_before = old_reserves[0] / old_reserves[1]
        ratio_after = new_reserves[0] / new_reserves[1]

        logger.info(f"Pool ratio before: {ratio_before:.10f}")
        logger.info(f"Pool ratio after: {ratio_after:.10f}")

        # Ratio should be virtually unchanged (within 0.1% for rounding)
        ratio_change_pct = abs(ratio_after - ratio_before) / ratio_before * 100
        assert ratio_change_pct < 0.1, (
            f"Pool ratio changed by {ratio_change_pct:.4f}%: {ratio_before:.10f} -> {ratio_after:.10f}"
        )
        logger.info(f"✓ Pool ratio maintained (change: {ratio_change_pct:.6f}%)")

        # Verify constant product invariant
        k_before = old_reserves[0] * old_reserves[1]
        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )
        logger.info("✓ Constant product invariant holds")

        # Verify LP tokens were minted (exact amount: limiting token determines LP)
        lp_minted = new_reserves[2] - old_reserves[2]
        expected_lp_minted = min(
            expected_first_used * old_reserves[2] // old_reserves[0],
            expected_second_used * old_reserves[2] // old_reserves[1]
        )
        assert lp_minted == expected_lp_minted, (
            f"LP tokens minted should be exactly {expected_lp_minted}, got {lp_minted}"
        )
        logger.info(f"✓ LP tokens minted: {lp_minted} (expected {expected_lp_minted})")

        logger.info("✅ Test passed: Imbalanced amounts handled correctly")

    @pytest.mark.edge_case
    def test_add_liquidity_slippage_exceeded(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Add liquidity fails when pool ratio changed beyond slippage tolerance

        GIVEN: Pool with existing reserves, Alice prepares add_liquidity with tight min amounts
        WHEN: Bob swaps first (changing pool ratio), then Alice's add_liquidity executes
              with min amounts that can no longer be satisfied
        THEN:
            - Alice's transaction fails with slippage error
            - Reserves unchanged (no partial execution)
            - Alice retains her tokens

        SECURITY: Slippage protection prevents liquidity providers from receiving
                  worse terms than expected when pool ratio shifts between quote and execution.
        """
        logger.info("TEST: Add liquidity with slippage exceeded")

        # Setup pool if needed
        _setup_pool_with_liquidity(
            pair_contract, alice, nominated_amount(1000),
            network_providers, blockchain_controller, ensure_esdt_amounts
        )

        reserves_before = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        logger.info(f"Initial reserves: first={reserves_before[0]}, second={reserves_before[1]}")

        # Alice prepares to add liquidity: she'll send 100 tokenA + equivalent tokenB
        add_amount_first = nominated_amount(100)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount_first)]
        )

        # Alice sets TIGHT min amounts (no slippage tolerance)
        # This means any ratio change will cause failure
        min_first = add_amount_first
        min_second = equivalent_second

        logger.info(f"Alice plans: first={add_amount_first}, second={equivalent_second}")
        logger.info(f"Min amounts (tight): first={min_first}, second={min_second}")

        # Bob swaps to change the pool ratio BEFORE Alice adds liquidity
        swap_amount = nominated_amount(200)
        ensure_esdt_amounts(bob, {pair_contract.firstToken: swap_amount})

        swap_event = SwapFixedInputEvent(
            tokenA=pair_contract.firstToken,
            amountA=swap_amount,
            tokenB=pair_contract.secondToken,
            amountBmin=1
        )
        bob.sync_nonce(network_providers.proxy)
        swap_tx = pair_contract.swap_fixed_input(network_providers, bob, swap_event)
        blockchain_controller.wait_for_tx(swap_tx)
        TransactionAssertions.assert_transaction_success(swap_tx, network_providers.proxy)
        logger.info("Bob's swap executed - pool ratio changed")

        reserves_after_swap = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        logger.info(f"Reserves after swap: first={reserves_after_swap[0]}, second={reserves_after_swap[1]}")

        # Now Alice tries to add liquidity with the OLD min amounts
        # The pool ratio has shifted, so optimal amounts won't meet minimums
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount_first,
            pair_contract.secondToken: equivalent_second
        })

        event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount_first,
            amountAmin=min_first,
            tokenB=pair_contract.secondToken,
            amountB=equivalent_second,
            amountBmin=min_second
        )

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, event)
        blockchain_controller.wait_for_tx(tx_hash)

        # Transaction should FAIL - the optimal second amount is now less than min_second
        # because Bob's swap increased first_reserve and decreased second_reserve
        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        logger.info("Transaction failed as expected (slippage exceeded)")

        # Reserves should be unchanged from after Bob's swap
        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        assert reserves_final[0] == reserves_after_swap[0], "First reserve should be unchanged"
        assert reserves_final[1] == reserves_after_swap[1], "Second reserve should be unchanged"
        logger.info("Reserves unchanged - no partial execution")

        logger.info("Test passed: Add liquidity correctly rejected when slippage exceeded")

    @pytest.mark.happy_path
    def test_add_liquidity_multiple_users_sequential(
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
        SCENARIO: Alice, Bob, and Charlie add liquidity sequentially

        GIVEN: Pool with initial liquidity from Alice
        WHEN: Bob adds 500 tokens, then Charlie adds 200 tokens
        THEN:
            - Each user receives LP tokens proportional to their contribution
            - Reserves increase correctly after each addition
            - Pool ratio maintained throughout
            - LP distribution is fair (proportional to liquidity added)

        SECURITY: Sequential additions must not create any advantage for
                  earlier or later liquidity providers beyond their actual contribution.
        """
        logger.info("TEST: Multiple users add liquidity sequentially")

        # Ensure pool has liquidity (no-op for loaded mainnet state)
        _setup_pool_with_liquidity(
            pair_contract, alice, nominated_amount(1000),
            network_providers, blockchain_controller, ensure_esdt_amounts
        )

        lp_token = Token(pair_contract.lpToken, 0)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Explicitly add Alice's liquidity so we can track her LP delta
        alice_amount_first = nominated_amount(1000)
        alice_equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(alice_amount_first)]
        )
        alice_lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: alice_amount_first,
            pair_contract.secondToken: alice_equivalent_second
        })

        alice_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=alice_amount_first,
            amountAmin=int(alice_amount_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=alice_equivalent_second,
            amountBmin=int(alice_equivalent_second * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_alice = pair_contract.add_liquidity(network_providers, alice, alice_event)
        blockchain_controller.wait_for_tx(tx_alice, blocks=5)
        TransactionAssertions.assert_transaction_success(tx_alice, network_providers.proxy)

        reserves_after_alice = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        lp_supply_initial = reserves_after_alice[2]
        alice_lp = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount - alice_lp_before
        logger.info(f"After Alice: reserves=({reserves_after_alice[0]}, {reserves_after_alice[1]}), LP={lp_supply_initial}")
        logger.info(f"Alice LP received: {alice_lp}")

        # Bob adds 500 tokens
        bob_amount_first = nominated_amount(500)
        bob_equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(bob_amount_first)]
        )

        ensure_esdt_amounts(bob, {
            pair_contract.firstToken: bob_amount_first,
            pair_contract.secondToken: bob_equivalent_second
        })

        bob_lp_before = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount

        bob_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=bob_amount_first,
            amountAmin=int(bob_amount_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=bob_equivalent_second,
            amountBmin=int(bob_equivalent_second * 0.95)
        )
        bob.sync_nonce(network_providers.proxy)
        tx_bob = pair_contract.add_liquidity(network_providers, bob, bob_event)
        blockchain_controller.wait_for_tx(tx_bob, blocks=5)
        TransactionAssertions.assert_transaction_success(tx_bob, network_providers.proxy)

        reserves_after_bob = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        bob_lp = network_providers.proxy.get_token_of_account(bob.address, lp_token).amount - bob_lp_before
        lp_minted_bob = reserves_after_bob[2] - lp_supply_initial
        logger.info(f"After Bob: reserves=({reserves_after_bob[0]}, {reserves_after_bob[1]}), LP minted={lp_minted_bob}")
        logger.info(f"Bob LP received (delta): {bob_lp}")

        expected_bob_lp = min(
            bob_amount_first * lp_supply_initial // reserves_after_alice[0],
            bob_equivalent_second * lp_supply_initial // reserves_after_alice[1]
        )
        assert bob_lp == expected_bob_lp, (
            f"Bob LP minted should be exactly {expected_bob_lp}, got {bob_lp}"
        )

        # Charlie adds 200 tokens
        charlie_amount_first = nominated_amount(200)
        charlie_equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(charlie_amount_first)]
        )

        ensure_esdt_amounts(charlie, {
            pair_contract.firstToken: charlie_amount_first,
            pair_contract.secondToken: charlie_equivalent_second
        })

        charlie_lp_before = network_providers.proxy.get_token_of_account(charlie.address, lp_token).amount

        charlie_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=charlie_amount_first,
            amountAmin=int(charlie_amount_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=charlie_equivalent_second,
            amountBmin=int(charlie_equivalent_second * 0.95)
        )
        charlie.sync_nonce(network_providers.proxy)
        tx_charlie = pair_contract.add_liquidity(network_providers, charlie, charlie_event)
        blockchain_controller.wait_for_tx(tx_charlie, blocks=5)
        TransactionAssertions.assert_transaction_success(tx_charlie, network_providers.proxy)

        reserves_after_charlie = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        charlie_lp = network_providers.proxy.get_token_of_account(charlie.address, lp_token).amount - charlie_lp_before
        lp_supply_after_bob = reserves_after_bob[2]
        logger.info(f"After Charlie: reserves=({reserves_after_charlie[0]}, {reserves_after_charlie[1]})")
        logger.info(f"Charlie LP received (delta): {charlie_lp}")

        expected_charlie_lp = min(
            charlie_amount_first * lp_supply_after_bob // reserves_after_bob[0],
            charlie_equivalent_second * lp_supply_after_bob // reserves_after_bob[1]
        )
        assert charlie_lp == expected_charlie_lp, (
            f"Charlie LP minted should be exactly {expected_charlie_lp}, got {charlie_lp}"
        )

        # Verify proportional LP distribution
        # Alice added 1000, Bob added 500, Charlie added 200 (of first token)
        # LP minting is proportional to contribution vs total reserves at time of addition
        # For large pools, bob_lp/alice_lp ≈ bob_amount/alice_amount = 0.5
        logger.info(f"LP received: Alice={alice_lp}, Bob={bob_lp}, Charlie={charlie_lp}")

        # Bob should have roughly half of Alice's LP tokens (he added half as much)
        expected_bob_ratio = bob_amount_first / alice_amount_first  # 500/1000 = 0.5
        actual_bob_ratio = bob_lp / alice_lp
        assert abs(actual_bob_ratio - expected_bob_ratio) < 0.05, (
            f"Bob's LP proportion should be ~{expected_bob_ratio:.4f} of Alice's.\n"
            f"Actual ratio: {actual_bob_ratio:.4f}"
        )

        # Pool ratio should be maintained throughout
        ratio_initial = reserves_after_alice[0] / reserves_after_alice[1]
        ratio_final = reserves_after_charlie[0] / reserves_after_charlie[1]
        ratio_change_pct = abs(ratio_final - ratio_initial) / ratio_initial * 100
        assert ratio_change_pct < 0.1, (
            f"Pool ratio should be maintained. Change: {ratio_change_pct:.4f}%"
        )
        logger.info(f"Pool ratio maintained (change: {ratio_change_pct:.6f}%)")

        logger.info("Test passed: Multiple users added liquidity with proportional LP distribution")

    @pytest.mark.happy_path
    def test_add_liquidity_with_fees_accumulated(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Add liquidity after swaps have accumulated fees in the pool

        GIVEN: Pool with initial liquidity, swaps have accumulated fees (k increased)
        WHEN: Alice adds liquidity to the fee-enriched pool
        THEN:
            - Transaction succeeds
            - LP tokens minted reflect the current (fee-enriched) reserves
            - New LP tokens are worth less per token contributed than original LP
              (because reserves grew from fees without new LP minting)
            - Pool ratio maintained

        SECURITY: Fee accumulation must not create unfair LP distribution.
                  New LPs should not dilute existing LP holders' fee earnings.
        """
        logger.info("TEST: Add liquidity after fees accumulated")

        # Setup pool
        _setup_pool_with_liquidity(
            pair_contract, alice, nominated_amount(1000),
            network_providers, blockchain_controller, ensure_esdt_amounts
        )

        reserves_initial = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_initial = reserves_initial[0] * reserves_initial[1]
        lp_supply_initial = reserves_initial[2]

        logger.info(f"Initial: reserves=({reserves_initial[0]}, {reserves_initial[1]}), k={k_initial}, LP={lp_supply_initial}")

        # Value per LP token before swaps
        value_per_lp_before_first = reserves_initial[0] / lp_supply_initial
        value_per_lp_before_second = reserves_initial[1] / lp_supply_initial

        # Bob performs several swaps to accumulate fees
        swap_amount = nominated_amount(50)
        num_swaps = 6
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

        reserves_after_swaps = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        k_after_swaps = reserves_after_swaps[0] * reserves_after_swaps[1]
        lp_supply_after_swaps = reserves_after_swaps[2]

        logger.info(f"After swaps: reserves=({reserves_after_swaps[0]}, {reserves_after_swaps[1]}), k={k_after_swaps}")

        # k should have increased from fees
        assert k_after_swaps > k_initial, "k should increase from accumulated fees"
        k_increase_pct = ((k_after_swaps - k_initial) / k_initial) * 100
        logger.info(f"k increased by {k_increase_pct:.4f}% from fees")

        # LP supply should be unchanged (swaps don't mint/burn LP)
        assert lp_supply_after_swaps == lp_supply_initial, "LP supply should be unchanged after swaps"

        # Value per LP token should have increased (reserves grew, LP supply same)
        value_per_lp_after_first = reserves_after_swaps[0] / lp_supply_after_swaps
        value_per_lp_after_second = reserves_after_swaps[1] / lp_supply_after_swaps

        # At least one dimension should show value increase (depends on swap direction balance)
        # The geometric mean (sqrt(first * second) / LP) should definitely increase
        geo_value_before = (reserves_initial[0] * reserves_initial[1]) ** 0.5 / lp_supply_initial
        geo_value_after = (reserves_after_swaps[0] * reserves_after_swaps[1]) ** 0.5 / lp_supply_after_swaps
        assert geo_value_after > geo_value_before, (
            f"Geometric LP value should increase with fees.\n"
            f"Before: {geo_value_before:.6f}, After: {geo_value_after:.6f}"
        )
        logger.info(f"LP geometric value increased: {geo_value_before:.6f} -> {geo_value_after:.6f}")

        # Now Alice adds more liquidity to the fee-enriched pool
        add_amount_first = nominated_amount(100)
        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )
        equivalent_second = pair_data_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(add_amount_first)]
        )

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_amount_first,
            pair_contract.secondToken: equivalent_second
        })

        lp_token = Token(pair_contract.lpToken, 0)
        alice_lp_before = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount

        add_event = AddLiquidityEvent(
            tokenA=pair_contract.firstToken,
            amountA=add_amount_first,
            amountAmin=int(add_amount_first * 0.95),
            tokenB=pair_contract.secondToken,
            amountB=equivalent_second,
            amountBmin=int(equivalent_second * 0.95)
        )
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, add_event)
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        reserves_final = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        alice_lp_after = network_providers.proxy.get_token_of_account(alice.address, lp_token).amount
        lp_minted = alice_lp_after - alice_lp_before

        logger.info(f"LP minted for Alice's new addition: {lp_minted}")
        logger.info(f"Final reserves: ({reserves_final[0]}, {reserves_final[1]}), LP={reserves_final[2]}")

        # Key invariant: LP minted should be exactly proportional to contribution relative to reserves
        # LP_minted = min(amountA * totalSupply / reserveA, amountB * totalSupply / reserveB)
        expected_lp_from_first = add_amount_first * lp_supply_after_swaps // reserves_after_swaps[0]
        expected_lp_from_second = equivalent_second * lp_supply_after_swaps // reserves_after_swaps[1]
        expected_lp = min(expected_lp_from_first, expected_lp_from_second)

        assert lp_minted == expected_lp, (
            f"LP minted should be exactly {expected_lp}, got {lp_minted}\n"
            f"From first: {expected_lp_from_first}, from second: {expected_lp_from_second}"
        )
        logger.info(f"LP minted matches expected exactly: {lp_minted} == {expected_lp}")

        # Verify pool ratio maintained
        ratio_before = reserves_after_swaps[0] / reserves_after_swaps[1]
        ratio_after = reserves_final[0] / reserves_final[1]
        ratio_change = abs(ratio_after - ratio_before) / ratio_before * 100
        assert ratio_change < 0.1, f"Pool ratio changed by {ratio_change:.4f}%"

        logger.info("Test passed: Liquidity added correctly to fee-enriched pool")



# ============================================================================
# Module-level helper functions (if needed)
# ============================================================================

def _setup_pool_with_liquidity(
    pair_contract: PairContract,
    account: Account,
    amount: int,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts=None
):
    """
    Helper: Initialize pool with liquidity if empty.

    Args:
        pair_contract: Pair contract to initialize
        account: Account to use for initialization
        amount: Amount of each token to add
        network_providers: Network providers (API + Proxy)
        blockchain_controller: Blockchain controller
        ensure_esdt_amounts: Optional callable to fund account with tokens

    Returns:
        tuple: Final reserves after initialization
    """
    reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

    if reserves[0] == 0 and reserves[1] == 0:
        # Fund account with tokens if funding function provided
        if ensure_esdt_amounts:
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
        tx_hash = pair_contract.add_initial_liquidity(network_providers, account, event)
        # Cross-shard MultiESDTNFTTransfer needs multiple blocks
        blockchain_controller.wait_for_tx(tx_hash, blocks=5)

        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        logger.info(f"Pool initialized with {amount} of each token")

    return reserves
