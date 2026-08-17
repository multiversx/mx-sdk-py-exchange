"""
Test helper utilities for smart contract testing.

This module provides:
- Black-box assertions for state verification
- State snapshot utilities for before/after comparisons

Example:
    from tests.helpers import PairAssertions, ContractStateSnapshot

    # Verify reserves increased
    PairAssertions.assert_reserves_increased(pair_addr, old_reserves, proxy)

    # Capture state snapshots
    snapshot = ContractStateSnapshot(pair_addr, proxy)
    snapshot.capture("before")
    # ... execute transaction ...
    snapshot.capture("after")
    diff = snapshot.compare("before", "after")
"""

from tests.helpers.assertions import (
    PairAssertions,
    AccountAssertions,
    TransactionAssertions,
    FarmAssertions,
    RouterAssertions
)
from tests.helpers.contract_state import (
    ContractStateSnapshot,
    MultiContractSnapshot
)


__all__ = [
    # Assertion helpers
    "PairAssertions",
    "AccountAssertions",
    "TransactionAssertions",
    "FarmAssertions",
    "RouterAssertions",
    # State snapshot helpers
    "ContractStateSnapshot",
    "MultiContractSnapshot",
]
