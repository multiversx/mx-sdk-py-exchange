"""
Black-box assertion helpers for smart contract testing.

This module provides assertion functions that verify smart contract state
using ONLY external interfaces (view functions, account queries, transaction status).

Key Principle: BLACK-BOX ONLY
- Query state via view functions
- Check account balances via proxy
- Verify transaction outcomes via proxy
- DO NOT access contract internals or Python implementation details

Usage:
    from tests.helpers.assertions import PairAssertions

    PairAssertions.assert_reserves_increased(
        pair_address, old_reserves, network_proxy
    )
"""

import base64
from typing import Tuple, Optional
from multiversx_sdk import ProxyNetworkProvider, Address

from utils.contract_data_fetchers import (
    PairContractDataFetcher,
    FarmContractDataFetcher,
    RouterContractDataFetcher
)
from utils.utils_chain import WrapperAddress, get_current_tokens_for_address
from utils.logger import get_logger


logger = get_logger(__name__)


class PairAssertions:
    """
    Black-box assertions for Pair contract state verification.

    All methods verify state via view functions only.
    """

    @staticmethod
    def assert_reserves_increased(
        pair_address: str,
        old_reserves: Tuple[int, int, int],
        proxy: ProxyNetworkProvider,
        min_increase_pct: float = 0.0
    ) -> Tuple[int, int, int]:
        """
        Verify pair reserves increased after add liquidity.

        Args:
            pair_address: Pair contract bech32 address
            old_reserves: (first_token_reserve, second_token_reserve, lp_total_supply)
            proxy: Network proxy
            min_increase_pct: Minimum increase percentage (default 0.0)

        Returns:
            Tuple[int, int, int]: New reserves (first, second, lp_supply)

        Raises:
            AssertionError: If reserves didn't increase as expected

        Example:
            >>> old = (1000, 1000, 1000)
            >>> new = PairAssertions.assert_reserves_increased(pair_addr, old, proxy)
            >>> # new[0] > 1000, new[1] > 1000, new[2] > 1000
        """
        fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_address),
            proxy.url
        )
        new_reserves = fetcher.get_data("getReservesAndTotalSupply")

        if not new_reserves or len(new_reserves) < 3:
            raise AssertionError(
                f"Failed to fetch reserves for pair {pair_address}. "
                f"Contract may not be initialized."
            )

        old_first, old_second, old_lp = old_reserves
        new_first, new_second, new_lp = new_reserves

        # Check first token reserve increased
        min_first = int(old_first * (1 + min_increase_pct))
        assert new_first > min_first, (
            f"First token reserve didn't increase sufficiently:\n"
            f"  Old: {old_first}\n"
            f"  New: {new_first}\n"
            f"  Min expected: {min_first} (+{min_increase_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        # Check second token reserve increased
        min_second = int(old_second * (1 + min_increase_pct))
        assert new_second > min_second, (
            f"Second token reserve didn't increase sufficiently:\n"
            f"  Old: {old_second}\n"
            f"  New: {new_second}\n"
            f"  Min expected: {min_second} (+{min_increase_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        # Check LP token supply increased
        min_lp = int(old_lp * (1 + min_increase_pct))
        assert new_lp > min_lp, (
            f"LP token supply didn't increase sufficiently:\n"
            f"  Old: {old_lp}\n"
            f"  New: {new_lp}\n"
            f"  Min expected: {min_lp} (+{min_increase_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        logger.debug(
            f"Reserves increased: {old_first}->{new_first}, "
            f"{old_second}->{new_second}, LP: {old_lp}->{new_lp}"
        )

        return (new_first, new_second, new_lp)

    @staticmethod
    def assert_reserves_decreased(
        pair_address: str,
        old_reserves: Tuple[int, int, int],
        proxy: ProxyNetworkProvider,
        min_decrease_pct: float = 0.0
    ) -> Tuple[int, int, int]:
        """
        Verify pair reserves decreased after remove liquidity.

        Args:
            pair_address: Pair contract bech32 address
            old_reserves: (first_token_reserve, second_token_reserve, lp_total_supply)
            proxy: Network proxy
            min_decrease_pct: Minimum decrease percentage (default 0.0)

        Returns:
            Tuple[int, int, int]: New reserves (first, second, lp_supply)

        Raises:
            AssertionError: If reserves didn't decrease as expected
        """
        fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_address),
            proxy.url
        )
        new_reserves = fetcher.get_data("getReservesAndTotalSupply")

        old_first, old_second, old_lp = old_reserves
        new_first, new_second, new_lp = new_reserves

        # Check first token reserve decreased
        max_first = int(old_first * (1 - min_decrease_pct))
        assert new_first < max_first, (
            f"First token reserve didn't decrease sufficiently:\n"
            f"  Old: {old_first}\n"
            f"  New: {new_first}\n"
            f"  Max expected: {max_first} (-{min_decrease_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        # Check second token reserve decreased
        max_second = int(old_second * (1 - min_decrease_pct))
        assert new_second < max_second, (
            f"Second token reserve didn't decrease sufficiently:\n"
            f"  Old: {old_second}\n"
            f"  New: {new_second}\n"
            f"  Max expected: {max_second} (-{min_decrease_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        # Check LP token supply decreased
        max_lp = int(old_lp * (1 - min_decrease_pct))
        assert new_lp < max_lp, (
            f"LP token supply didn't decrease sufficiently:\n"
            f"  Old: {old_lp}\n"
            f"  New: {new_lp}\n"
            f"  Max expected: {max_lp} (-{min_decrease_pct:.1%})\n"
            f"  Pair: {pair_address}"
        )

        logger.debug(
            f"Reserves decreased: {old_first}->{new_first}, "
            f"{old_second}->{new_second}, LP: {old_lp}->{new_lp}"
        )

        return (new_first, new_second, new_lp)

    @staticmethod
    def assert_constant_product_holds(
        pair_address: str,
        k_before: int,
        proxy: ProxyNetworkProvider,
        tolerance_pct: float = 0.001
    ) -> int:
        """
        Verify AMM invariant: x * y >= k (constant product formula).

        The product should never decrease (except for fee precision).
        Small increases are acceptable due to trading fees.

        Args:
            pair_address: Pair contract bech32 address
            k_before: Previous k value (reserve_a * reserve_b)
            proxy: Network proxy
            tolerance_pct: Acceptable decrease tolerance (default 0.1%)

        Returns:
            int: New k value

        Raises:
            AssertionError: If constant product invariant violated

        Security:
            If k decreases significantly, arbitrage drain is possible.
            This is CRITICAL for AMM security.
        """
        fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_address),
            proxy.url
        )
        reserves = fetcher.get_data("getReservesAndTotalSupply")

        if not reserves or len(reserves) < 2:
            raise AssertionError(f"Failed to fetch reserves for {pair_address}")

        k_after = reserves[0] * reserves[1]
        min_allowed_k = int(k_before * (1 - tolerance_pct))

        assert k_after >= min_allowed_k, (
            f"Constant product invariant violated (k = x * y):\n"
            f"  k_before: {k_before}\n"
            f"  k_after:  {k_after}\n"
            f"  Change:   {((k_after - k_before) / k_before * 100):.4f}%\n"
            f"  Min allowed: {min_allowed_k} (-{tolerance_pct:.3%})\n"
            f"  Reserves: {reserves[0]} * {reserves[1]}\n"
            f"  Pair: {pair_address}\n"
            f"CRITICAL: k should NEVER decrease. This indicates potential arbitrage drain."
        )

        if k_after > k_before:
            logger.debug(f"Constant product increased: {k_before} -> {k_after} (+{((k_after - k_before) / k_before * 100):.4f}%)")
        else:
            logger.debug(f"Constant product maintained: {k_before}")

        return k_after

    @staticmethod
    def assert_slippage_within_bounds(
        expected_output: int,
        actual_output: int,
        max_slippage_pct: float
    ):
        """
        Verify swap slippage is within acceptable bounds.

        Args:
            expected_output: Expected output tokens (no slippage)
            actual_output: Actual output tokens received
            max_slippage_pct: Maximum acceptable slippage (e.g., 0.05 for 5%)

        Raises:
            AssertionError: If slippage exceeds maximum

        Example:
            >>> # User expects 1000 tokens, accepts 5% slippage
            >>> assert_slippage_within_bounds(1000, 955, 0.05)  # OK
            >>> assert_slippage_within_bounds(1000, 940, 0.05)  # FAIL
        """
        if actual_output > expected_output:
            # Got more than expected - always acceptable
            logger.debug(f"Positive slippage: received {actual_output} > expected {expected_output}")
            return

        slippage = (expected_output - actual_output) / expected_output

        assert slippage <= max_slippage_pct, (
            f"Slippage exceeds maximum:\n"
            f"  Expected output: {expected_output}\n"
            f"  Actual output:   {actual_output}\n"
            f"  Slippage:        {slippage:.2%}\n"
            f"  Max allowed:     {max_slippage_pct:.2%}\n"
            f"  User lost:       {expected_output - actual_output} tokens more than expected"
        )

        logger.debug(f"Slippage within bounds: {slippage:.2%} <= {max_slippage_pct:.2%}")

    @staticmethod
    def get_reserves(pair_address: str, proxy: ProxyNetworkProvider) -> Tuple[int, int, int]:
        """
        Fetch current pair reserves.

        Args:
            pair_address: Pair contract bech32 address
            proxy: Network proxy

        Returns:
            Tuple[int, int, int]: (first_reserve, second_reserve, lp_supply)

        Raises:
            RuntimeError: If reserves fetch fails
        """
        fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_address),
            proxy.url
        )
        reserves = fetcher.get_data("getReservesAndTotalSupply")

        if not reserves or len(reserves) < 3:
            raise RuntimeError(
                f"Failed to fetch reserves for {pair_address}. "
                f"Contract may not be initialized."
            )

        return tuple(reserves[:3])


class AccountAssertions:
    """
    Black-box assertions for account state verification.

    Verifies token balances, nonces, and transaction outcomes.
    """

    @staticmethod
    def assert_token_balance_increased(
        user_address: Address,
        token_id: str,
        old_balance: int,
        proxy: ProxyNetworkProvider,
        min_increase: int = 1
    ) -> int:
        """
        Verify user's token balance increased.

        Args:
            user_address: User's bech32 address
            token_id: Token identifier (e.g., "WEGLD-123456")
            old_balance: Previous balance
            proxy: Network proxy
            min_increase: Minimum increase required (default 1)

        Returns:
            int: New balance

        Raises:
            AssertionError: If balance didn't increase
        """
        tokens = get_current_tokens_for_address(user_address, proxy)

        if token_id not in tokens:
            new_balance = 0
        else:
            new_balance = int(tokens[token_id]['balance'])

        assert new_balance >= old_balance + min_increase, (
            f"Token balance didn't increase for {user_address.to_bech32()}:\n"
            f"  Token: {token_id}\n"
            f"  Old balance: {old_balance}\n"
            f"  New balance: {new_balance}\n"
            f"  Min expected: {old_balance + min_increase}\n"
            f"  Difference: {new_balance - old_balance}"
        )

        logger.debug(f"Balance increased: {old_balance} -> {new_balance} (+{new_balance - old_balance})")
        return new_balance

    @staticmethod
    def assert_token_balance_decreased(
        user_address: Address,
        token_id: str,
        old_balance: int,
        proxy: ProxyNetworkProvider,
        min_decrease: int = 1
    ) -> int:
        """
        Verify user's token balance decreased.

        Args:
            user_address: User's bech32 address
            token_id: Token identifier
            old_balance: Previous balance
            proxy: Network proxy
            min_decrease: Minimum decrease required (default 1)

        Returns:
            int: New balance

        Raises:
            AssertionError: If balance didn't decrease
        """
        tokens = get_current_tokens_for_address(user_address, proxy)

        if token_id not in tokens:
            new_balance = 0
        else:
            new_balance = int(tokens[token_id]['balance'])

        assert new_balance <= old_balance - min_decrease, (
            f"Token balance didn't decrease for {user_address.to_bech32()}:\n"
            f"  Token: {token_id}\n"
            f"  Old balance: {old_balance}\n"
            f"  New balance: {new_balance}\n"
            f"  Max expected: {old_balance - min_decrease}\n"
            f"  Difference: {old_balance - new_balance}"
        )

        logger.debug(f"Balance decreased: {old_balance} -> {new_balance} (-{old_balance - new_balance})")
        return new_balance

    @staticmethod
    def assert_token_balance_exact(
        user_address: Address,
        token_id: str,
        expected_balance: int,
        proxy: ProxyNetworkProvider,
        tolerance: int = 0
    ):
        """
        Verify user's token balance equals expected value.

        Args:
            user_address: User's bech32 address
            token_id: Token identifier
            expected_balance: Expected exact balance
            proxy: Network proxy
            tolerance: Acceptable difference (default 0)

        Raises:
            AssertionError: If balance doesn't match
        """
        tokens = get_current_tokens_for_address(user_address, proxy)

        if token_id not in tokens:
            actual_balance = 0
        else:
            actual_balance = int(tokens[token_id]['balance'])

        min_allowed = expected_balance - tolerance
        max_allowed = expected_balance + tolerance

        assert min_allowed <= actual_balance <= max_allowed, (
            f"Token balance mismatch for {user_address.to_bech32()}:\n"
            f"  Token: {token_id}\n"
            f"  Expected: {expected_balance}\n"
            f"  Actual: {actual_balance}\n"
            f"  Tolerance: ±{tolerance}\n"
            f"  Difference: {actual_balance - expected_balance}"
        )


class TransactionAssertions:
    """
    Black-box assertions for transaction outcomes.

    Verifies transaction success/failure and status.
    """

    @staticmethod
    def _extract_error_from_tx(tx) -> str:
        try:
            # Validate transaction has logs
            if not hasattr(tx, 'logs') or not tx.logs:
                return "No transaction logs available"

            events = tx.logs.events if hasattr(tx.logs, 'events') else []
            if not events:
                return "No events in transaction logs"

            # Priority 1: internalVMErrors (most detailed)
            for event in events:
                if event.identifier == "internalVMErrors" and event.data:
                    if isinstance(event.data, bytes):
                        data_str = event.data.decode('utf-8', errors='ignore')
                    else:
                        data_str = str(event.data)
                    return data_str

            # Priority 2: signalError (standard contract errors)
            for event in events:
                if event.identifier == "signalError" and event.data:
                    if isinstance(event.data, bytes):
                        data_str = event.data.decode('utf-8', errors='ignore')
                    else:
                        data_str = str(event.data)
                    return bytearray.fromhex(data_str[1:]).decode('utf-8', errors='ignore')

            return "No error message found in transaction events"

        except Exception as e:
            logger.error(f"Unexpected error extracting transaction error: {e}", exc_info=True)
            return f"Error during extraction: {str(e)}"

    @staticmethod
    def assert_transaction_success(tx_hash: str, proxy: ProxyNetworkProvider):
        """
        Verify transaction succeeded.

        Args:
            tx_hash: Transaction hash
            proxy: Network proxy

        Raises:
            AssertionError: If transaction failed or pending
        """
        tx = proxy.get_transaction(tx_hash)

        if not tx.status.is_successful:
            # Extract error message from signalError event if available
            error_msg = TransactionAssertions._extract_error_from_tx(tx)

            assert False, (
                f"Transaction failed: {tx_hash}\n"
                f"  Status: {tx.status}\n"
                f"  Sender: {tx.sender}\n"
                f"  Receiver: {tx.receiver}\n"
                f"  Function: {tx.raw.get('function', 'N/A')}\n"
                f"  Error: {error_msg}\n"
                f"Check transaction on explorer for details."
            )

        logger.debug(f"Transaction succeeded: {tx_hash}")

    @staticmethod
    def assert_transaction_failed(
        tx_hash: str,
        proxy: ProxyNetworkProvider,
        expected_error: Optional[str] = None
    ):
        """
        Verify transaction failed with expected error.

        Args:
            tx_hash: Transaction hash
            proxy: Network proxy
            expected_error: Optional substring of expected error message

        Raises:
            AssertionError: If transaction succeeded or error doesn't match
        """
        tx = proxy.get_transaction(tx_hash)

        assert not tx.status.is_successful, (
            f"Transaction should have failed but succeeded: {tx_hash}\n"
            f"  Status: {tx.status}\n"
            f"Expected failure with error: {expected_error}"
        )

        if expected_error:
            # Extract error message from signalError event
            error_msg = TransactionAssertions._extract_error_from_tx(tx)

            assert expected_error.lower() in error_msg.lower(), (
                f"Transaction failed with unexpected error: {tx_hash}\n"
                f"  Expected error containing: {expected_error}\n"
                f"  Actual error: {error_msg}"
            )

        logger.debug(f"Transaction failed as expected: {tx_hash}")


class FarmAssertions:
    """
    Black-box assertions for Farm contract state verification.

    TODO: Implement farm-specific assertions when needed
    """
    pass


class RouterAssertions:
    """
    Black-box assertions for Router contract state verification.

    TODO: Implement router-specific assertions when needed
    """
    pass
