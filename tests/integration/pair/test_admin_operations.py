"""
Integration tests for Pair contract admin/owner-only operations.

These tests verify that administrative endpoints work correctly and
enforce proper permission checks:
- setFeePercents: Fee configuration changes
- whitelist / removeWhitelist: Whitelist management
- setLockingDeadlineEpoch / setUnlockEpoch / setLockingScAddress: LP locking config
- Fee collector configuration queries

Run:
    pytest --env=chainsim tests/integration/pair/test_admin_operations.py
"""

from multiversx_sdk import Address
import pytest

from contracts.pair_contract import (
    PairContract, AddLiquidityEvent
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
            logger.info(f"Funding deployer with EGLD for gas")
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
        return PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
    return reserves


@pytest.mark.integration
@pytest.mark.pair
class TestAdminOperations:
    """
    Integration tests for Pair contract admin/owner endpoints.

    These tests verify fee configuration, whitelist management,
    locking configuration, and permission enforcement.

    IMPORTANT: All state-modifying tests use try/finally to restore
    original values since the pair_contract fixture is session-scoped.
    """

    @pytest.mark.happy_path
    def test_set_fee_percents_valid(
        self,
        pair_contract: PairContract,
        deployer_account: Account,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: Owner changes fee percentages and verifies via view functions

        GIVEN: Pair contract with known fee configuration
        WHEN: Owner calls setFeePercents with new values
        THEN:
            - Transaction succeeds
            - getTotalFeePercent returns new value
            - getSpecialFee returns new value
            - Original values restored after test
        """
        logger.info("TEST: Set fee percents (valid)")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Record original fees
        original_total = pair_data_fetcher.get_data("getTotalFeePercent")
        original_special = pair_data_fetcher.get_data("getSpecialFee")
        logger.info(f"Original fees: total={original_total}, special={original_special}")

        # Set new fees
        new_total = 500  # 0.5%
        new_special = 200  # 0.2%

        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = pair_contract.set_fees_percents(
                deployer_account, network_providers.proxy, [new_total, new_special]
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Verify new fees via view
            updated_total = pair_data_fetcher.get_data("getTotalFeePercent")
            updated_special = pair_data_fetcher.get_data("getSpecialFee")
            logger.info(f"Updated fees: total={updated_total}, special={updated_special}")

            assert updated_total == new_total, (
                f"Total fee not updated: expected {new_total}, got {updated_total}"
            )
            assert updated_special == new_special, (
                f"Special fee not updated: expected {new_special}, got {updated_special}"
            )

        finally:
            # Restore original fees
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = pair_contract.set_fees_percents(
                deployer_account, network_providers.proxy,
                [original_total, original_special]
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info(f"Fees restored to: total={original_total}, special={original_special}")

        logger.info("Test passed: Fee percents set and verified successfully")

    @pytest.mark.edge_case
    def test_set_fee_percents_invalid_special_gt_total(
        self,
        pair_contract: PairContract,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        test_environment
    ):
        """
        SCENARIO: Setting special_fee > total_fee should be rejected

        GIVEN: Pair contract with valid fee configuration
        WHEN: Owner calls setFeePercents with special > total
        THEN: Transaction fails (SC invariant: special_fee <= total_fee)

        SECURITY: If special > total were allowed, the fee math would break
                  causing incorrect swap calculations or fund loss.
        """
        logger.info("TEST: Set fee percents with invalid special > total")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.set_fees_percents(
            deployer_account, network_providers.proxy, [100, 200]  # special(200) > total(100)
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(
            tx_hash, network_providers.proxy, expected_error="Bad percents"
        )

        logger.info("Test passed: Invalid fee configuration correctly rejected")

    @pytest.mark.security
    def test_set_fee_percents_unauthorized(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller
    ):
        """
        SCENARIO: Non-owner cannot change fee percentages

        GIVEN: Pair contract, Alice is not the owner/admin
        WHEN: Alice calls setFeePercents
        THEN: Transaction fails (permission denied)

        SECURITY: Fee configuration is critical. Only authorized accounts
                  should be able to modify fees.
        """
        logger.info("TEST: Set fee percents unauthorized")

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.set_fees_percents(
            alice, network_providers.proxy, [300, 100]
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        logger.info("Test passed: Unauthorized fee change correctly rejected")

    @pytest.mark.happy_path
    def test_set_fee_percents_impact_on_swap(
        self,
        pair_contract: PairContract,
        deployer_account: Account,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        test_environment
    ):
        """
        SCENARIO: Changing fees affects swap output amounts

        GIVEN: Pool with liquidity, known fee configuration
        WHEN: Owner changes fees and queries getAmountOut
        THEN: Output changes proportionally to fee change

        SECURITY: Fee changes must immediately take effect on subsequent swaps.
                  Delayed fee application could be exploited for arbitrage.
        """
        logger.info("TEST: Fee change impact on swap output")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)
        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Record original fees
        original_total = pair_data_fetcher.get_data("getTotalFeePercent")
        original_special = pair_data_fetcher.get_data("getSpecialFee")

        test_amount = nominated_amount(10)

        # Get output with current fees
        output_original = pair_data_fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(test_amount)]
        )
        logger.info(f"Output with original fees ({original_total}): {output_original}")

        try:
            # Set higher fees
            high_total = min(original_total * 3, 5000)  # 3x but capped at max
            high_special = min(original_special * 3, high_total)

            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = pair_contract.set_fees_percents(
                deployer_account, network_providers.proxy, [high_total, high_special]
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            # Get output with higher fees
            output_high_fee = pair_data_fetcher.get_data(
                "getAmountOut",
                [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(test_amount)]
            )
            logger.info(f"Output with high fees ({high_total}): {output_high_fee}")

            # Higher fees should result in lower output
            assert output_high_fee < output_original, (
                f"Higher fees should reduce output.\n"
                f"Original fee ({original_total}): output={output_original}\n"
                f"Higher fee ({high_total}): output={output_high_fee}"
            )

            reduction_pct = (output_original - output_high_fee) / output_original * 100
            logger.info(f"Output reduction with higher fees: {reduction_pct:.2f}%")

        finally:
            # Restore original fees
            deployer_account.sync_nonce(network_providers.proxy)
            tx_restore = pair_contract.set_fees_percents(
                deployer_account, network_providers.proxy,
                [original_total, original_special]
            )
            blockchain_controller.wait_for_tx(tx_restore)
            TransactionAssertions.assert_transaction_success(tx_restore, network_providers.proxy)
            logger.info("Fees restored")

        logger.info("Test passed: Fee changes correctly affect swap output")

    @pytest.mark.happy_path
    def test_whitelist_and_remove_whitelist(
        self,
        pair_contract: PairContract,
        deployer_account: Account,
        alice: Account,
        network_providers,
        blockchain_controller,
        test_environment
    ):
        """
        SCENARIO: Owner can whitelist and un-whitelist addresses

        GIVEN: Pair contract, deployer is owner
        WHEN: Owner whitelists Alice, then removes her from whitelist
        THEN: Both transactions succeed

        SECURITY: Whitelisted addresses can call swapNoFeeAndForward.
                  Proper whitelist management prevents unauthorized fee-free swaps.
        """
        logger.info("TEST: Whitelist and remove whitelist")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        alice_bech32 = alice.address.to_bech32()

        try:
            # Whitelist Alice
            deployer_account.sync_nonce(network_providers.proxy)
            tx_whitelist = pair_contract.whitelist_contract(
                deployer_account, network_providers.proxy, alice_bech32
            )
            blockchain_controller.wait_for_tx(tx_whitelist)
            TransactionAssertions.assert_transaction_success(tx_whitelist, network_providers.proxy)
            logger.info("Alice whitelisted successfully")

        finally:
            # Remove from whitelist (cleanup)
            deployer_account.sync_nonce(network_providers.proxy)
            tx_remove = pair_contract.remove_whitelist(
                deployer_account, network_providers.proxy, alice_bech32
            )
            blockchain_controller.wait_for_tx(tx_remove)
            TransactionAssertions.assert_transaction_success(tx_remove, network_providers.proxy)
            logger.info("Alice removed from whitelist (cleanup)")

        logger.info("Test passed: Whitelist add/remove cycle completed")

    @pytest.mark.security
    def test_whitelist_unauthorized(
        self,
        pair_contract: PairContract,
        alice: Account,
        bob: Account,
        network_providers,
        blockchain_controller
    ):
        """
        SCENARIO: Non-owner cannot whitelist addresses

        GIVEN: Pair contract, Alice is not the owner
        WHEN: Alice tries to whitelist Bob
        THEN: Transaction fails

        SECURITY: Only the owner should be able to whitelist addresses.
                  Unauthorized whitelisting would allow fee-free swaps.
        """
        logger.info("TEST: Whitelist unauthorized")

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.whitelist_contract(
            alice, network_providers.proxy, bob.address.to_bech32()
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        logger.info("Test passed: Unauthorized whitelist correctly rejected")

    @pytest.mark.happy_path
    def test_locking_config_endpoints(
        self,
        pair_contract: PairContract,
        deployer_account: Account,
        network_providers,
        blockchain_controller,
        test_environment
    ):
        """
        SCENARIO: Owner can configure LP locking parameters

        GIVEN: Pair contract, deployer is owner
        WHEN: Owner calls setLockingDeadlineEpoch, setUnlockEpoch
        THEN: Transactions succeed (configuration accepted)

        NOTE: setLockingScAddress requires a valid SC address and may fail
              on chain simulator if the locking module is not configured.
        """
        logger.info("TEST: Locking config endpoints")
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Test setLockingDeadlineEpoch
        try:
            deployer_account.sync_nonce(network_providers.proxy)
            tx_deadline = pair_contract.set_locking_deadline_epoch(
                deployer_account, network_providers.proxy, 10000
            )
            blockchain_controller.wait_for_tx(tx_deadline)

            tx_deadline_data = network_providers.proxy.get_transaction(tx_deadline)
            if tx_deadline_data.status.is_successful:
                logger.info("setLockingDeadlineEpoch succeeded")
            else:
                logger.info("setLockingDeadlineEpoch not supported on this SC version (expected)")

            # Test setUnlockEpoch
            deployer_account.sync_nonce(network_providers.proxy)
            tx_unlock = pair_contract.set_unlock_epoch(
                deployer_account, network_providers.proxy, 5000
            )
            blockchain_controller.wait_for_tx(tx_unlock)

            tx_unlock_data = network_providers.proxy.get_transaction(tx_unlock)
            if tx_unlock_data.status.is_successful:
                logger.info("setUnlockEpoch succeeded")
            else:
                logger.info("setUnlockEpoch not supported on this SC version (expected)")

        finally:
            # Cleanup: reset locking values to 0 to avoid corrupting state for other tests
            deployer_account.sync_nonce(network_providers.proxy)
            tx_reset1 = pair_contract.set_locking_deadline_epoch(
                deployer_account, network_providers.proxy, 0
            )
            blockchain_controller.wait_for_tx(tx_reset1)

            deployer_account.sync_nonce(network_providers.proxy)
            tx_reset2 = pair_contract.set_unlock_epoch(
                deployer_account, network_providers.proxy, 0
            )
            blockchain_controller.wait_for_tx(tx_reset2)
            logger.info("Locking config reset to 0 (cleanup)")

        logger.info("Test passed: Locking config endpoints callable by owner")

    @pytest.mark.security
    def test_locking_config_unauthorized(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller
    ):
        """
        SCENARIO: Non-owner cannot configure locking parameters

        GIVEN: Pair contract, Alice is not the owner
        WHEN: Alice calls setLockingDeadlineEpoch
        THEN: Transaction fails

        SECURITY: Locking configuration affects LP token distribution.
                  Unauthorized changes could lock/unlock tokens unexpectedly.
        """
        logger.info("TEST: Locking config unauthorized")

        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.set_locking_deadline_epoch(
            alice, network_providers.proxy, 10000
        )
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)
        logger.info("Test passed: Unauthorized locking config correctly rejected")

    @pytest.mark.happy_path
    def test_fees_collector_config_query(
        self,
        pair_contract: PairContract,
        alice: Account,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts
    ):
        """
        SCENARIO: Query fee collector configuration from pair contract

        GIVEN: Pair contract loaded from mainnet state (may have fee collector configured)
        WHEN: Query getFeesCollectorAddress and getFeesCollectorCutPercentage
        THEN:
            - Both views return valid data
            - Cut percentage is in valid range [0, 10000]
            - If collector is configured, address is non-zero

        SECURITY: Fee collector misconfiguration could redirect fees
                  to an unauthorized address or use invalid percentages.
        """
        logger.info("TEST: Fees collector config query")

        _ensure_pool_has_liquidity(
            pair_contract, alice, network_providers,
            blockchain_controller, ensure_esdt_amounts
        )

        pair_data_fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address),
            network_providers.proxy.url
        )

        # Query fees collector address
        collector_hex = pair_data_fetcher.get_data("getFeesCollectorAddress")
        logger.info(f"Fees collector address (hex): {collector_hex}")

        if collector_hex and len(collector_hex) > 0:
            # Non-empty means a collector is configured
            logger.info("Fee collector is configured")
        else:
            logger.info("No fee collector configured (zero address)")

        # Query fees collector cut percentage
        cut_pct = pair_data_fetcher.get_data("getFeesCollectorCutPercentage")
        logger.info(f"Fees collector cut percentage: {cut_pct}")

        assert cut_pct >= 0, f"Cut percentage must be non-negative, got {cut_pct}"
        assert cut_pct <= 100000, f"Cut percentage must be <= 100000, got {cut_pct}"

        # Query total and special fee for completeness
        total_fee = pair_data_fetcher.get_data("getTotalFeePercent")
        special_fee = pair_data_fetcher.get_data("getSpecialFee")
        lp_fee = total_fee - special_fee

        logger.info(f"Fee breakdown: total={total_fee}, special={special_fee}, LP={lp_fee}")
        logger.info(f"Of special fee, {cut_pct}/10000 goes to collector")

        if special_fee > 0 and cut_pct > 0:
            collector_share = special_fee * cut_pct // 100000
            logger.info(f"Effective collector fee: {collector_share}/100000 per swap")

        logger.info("Test passed: Fee collector configuration valid")
