"""
Contract state snapshot utilities for before/after comparisons.

This module provides helpers to capture contract state at specific points
and compare snapshots to detect changes.

Usage:
    snapshot = ContractStateSnapshot(pair_address, proxy)
    snapshot.capture("before")

    # Execute transaction
    pair_contract.swap(...)

    snapshot.capture("after")
    diff = snapshot.compare("before", "after")
"""

from typing import Dict, Any, List, Optional
from multiversx_sdk import ProxyNetworkProvider, Address

from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger


logger = get_logger(__name__)


class ContractStateSnapshot:
    """
    Capture and compare contract state at different points in time.

    This is useful for:
    - Verifying state transitions
    - Debugging unexpected changes
    - Documenting contract behavior
    """

    def __init__(self, contract_address: str, proxy: ProxyNetworkProvider):
        """
        Initialize snapshot manager.

        Args:
            contract_address: Bech32 contract address
            proxy: Network proxy
        """
        self.address = contract_address
        self.proxy = proxy
        self.snapshots: Dict[str, Dict[str, Any]] = {}

    def capture(self, label: str = "default"):
        """
        Capture current contract state.

        Captures:
        - Account info (balance, nonce, code hash)
        - Contract-specific state (depends on contract type)

        Args:
            label: Identifier for this snapshot

        Example:
            >>> snapshot.capture("before_swap")
            >>> # Execute swap
            >>> snapshot.capture("after_swap")
        """
        # Get account info
        addr = Address.new_from_bech32(self.address)
        account = self.proxy.get_account(addr)

        state = {
            "balance": account.balance,
            "nonce": account.nonce,
            "code_hash": account.code_hash,
            "owner": account.contract_owner_address.to_bech32() if account.contract_owner_address else None,
        }

        # Try to fetch pair-specific state
        try:
            fetcher = PairContractDataFetcher(addr, self.proxy.url)
            reserves = fetcher.get_data("getReservesAndTotalSupply")
            if reserves and len(reserves) >= 3:
                state["pair_reserves"] = {
                    "first_token": reserves[0],
                    "second_token": reserves[1],
                    "lp_supply": reserves[2],
                    "k": reserves[0] * reserves[1]
                }
        except Exception as e:
            logger.debug(f"Could not fetch pair reserves: {e}")

        self.snapshots[label] = state
        logger.debug(f"Captured state snapshot '{label}' for {self.address}")

    def get(self, label: str) -> Dict[str, Any]:
        """
        Get a specific snapshot.

        Args:
            label: Snapshot identifier

        Returns:
            Dict: Snapshot data

        Raises:
            KeyError: If snapshot doesn't exist
        """
        if label not in self.snapshots:
            raise KeyError(
                f"Snapshot '{label}' not found. Available: {list(self.snapshots.keys())}"
            )
        return self.snapshots[label]

    def compare(self, before_label: str, after_label: str) -> Dict[str, Any]:
        """
        Compare two snapshots and return differences.

        Args:
            before_label: Label of earlier snapshot
            after_label: Label of later snapshot

        Returns:
            Dict: Differences between snapshots

        Example:
            >>> diff = snapshot.compare("before", "after")
            >>> print(diff["pair_reserves"]["first_token"])
            {'before': 1000, 'after': 1100, 'change': +100}
        """
        before = self.get(before_label)
        after = self.get(after_label)

        diff = {}

        # Compare simple fields
        for key in ["balance", "nonce"]:
            if key in before and key in after:
                if before[key] != after[key]:
                    diff[key] = {
                        "before": before[key],
                        "after": after[key],
                        "change": after[key] - before[key]
                    }

        # Compare pair reserves
        if "pair_reserves" in before and "pair_reserves" in after:
            reserves_diff = {}
            for key in ["first_token", "second_token", "lp_supply", "k"]:
                before_val = before["pair_reserves"][key]
                after_val = after["pair_reserves"][key]
                if before_val != after_val:
                    reserves_diff[key] = {
                        "before": before_val,
                        "after": after_val,
                        "change": after_val - before_val,
                        "change_pct": ((after_val - before_val) / before_val * 100) if before_val > 0 else 0
                    }
            if reserves_diff:
                diff["pair_reserves"] = reserves_diff

        return diff

    def assert_no_unexpected_changes(
        self,
        before_label: str,
        after_label: str,
        expected_changes: Optional[List[str]] = None
    ):
        """
        Verify only expected fields changed.

        Args:
            before_label: Label of earlier snapshot
            after_label: Label of later snapshot
            expected_changes: List of expected changed fields

        Raises:
            AssertionError: If unexpected changes detected

        Example:
            >>> # We expect only nonce to change (transaction sent)
            >>> snapshot.assert_no_unexpected_changes("before", "after", ["nonce"])
        """
        if expected_changes is None:
            expected_changes = []

        diff = self.compare(before_label, after_label)
        unexpected = [key for key in diff.keys() if key not in expected_changes]

        if unexpected:
            raise AssertionError(
                f"Unexpected state changes detected:\n"
                f"  Expected changes: {expected_changes}\n"
                f"  Actual changes: {list(diff.keys())}\n"
                f"  Unexpected: {unexpected}\n"
                f"  Details: {diff}"
            )

        logger.debug(f"No unexpected changes: only {expected_changes} changed as expected")


class MultiContractSnapshot:
    """
    Capture state for multiple contracts simultaneously.

    Useful for testing cross-contract interactions.
    """

    def __init__(self, contract_addresses: List[str], proxy: ProxyNetworkProvider):
        """
        Initialize multi-contract snapshot manager.

        Args:
            contract_addresses: List of bech32 contract addresses
            proxy: Network proxy
        """
        self.snapshots = {
            addr: ContractStateSnapshot(addr, proxy)
            for addr in contract_addresses
        }

    def capture_all(self, label: str = "default"):
        """
        Capture state for all contracts.

        Args:
            label: Identifier for this snapshot
        """
        for snapshot in self.snapshots.values():
            snapshot.capture(label)

    def get(self, address: str, label: str) -> Dict[str, Any]:
        """
        Get snapshot for specific contract.

        Args:
            address: Contract bech32 address
            label: Snapshot identifier

        Returns:
            Dict: Snapshot data
        """
        return self.snapshots[address].get(label)

    def compare_all(self, before_label: str, after_label: str) -> Dict[str, Dict[str, Any]]:
        """
        Compare snapshots for all contracts.

        Args:
            before_label: Label of earlier snapshot
            after_label: Label of later snapshot

        Returns:
            Dict: Differences for each contract
        """
        return {
            addr: snapshot.compare(before_label, after_label)
            for addr, snapshot in self.snapshots.items()
        }
