"""
Shared pytest fixtures for the farm and farm_staking test packages.

Overrides the primary test users (`alice`, `bob`) so that farm and staking
operations are exercised consistently from deterministic shard-1 accounts;
multi-user tests still get a distinct `charlie` from the shared pool.
"""

import pytest

from tests.conftest import _ensure_account_has_egld
from utils.utils_chain import Account


@pytest.fixture
def alice(shard1_account) -> Account:
    """
    Primary test user, pinned to a shard-1 account.

    Overrides the session-wide `alice` fixture for the farm and farm_staking
    packages, so their tests share the same shard-1 account as the main actor.
    """
    return shard1_account


@pytest.fixture
def bob(dex_context, test_environment, network_providers) -> Account:
    """
    Secondary test user, pinned to a (different) shard-1 account.

    Overrides the session-wide `bob` fixture for the farm and farm_staking
    packages, so their tests share a second shard-1 account as a supporting
    actor.
    """
    shard1_accounts = dex_context.accounts.get_in_shard(1)
    if not shard1_accounts:
        pytest.skip("No test account available in shard 1")

    account = shard1_accounts[1]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(account, test_environment, network_providers.proxy)

    account.sync_nonce(network_providers.proxy)
    return account
