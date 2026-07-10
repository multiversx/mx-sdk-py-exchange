"""
Farm-package pytest fixtures.

Overrides the primary test user (`alice`) so that every farm test uses the
same shard-1 account. Farm operations (enter/exit/claim, boosted yields) are
exercised consistently from a single, deterministic shard-1 account; multi-user
tests still get distinct `bob`/`charlie` accounts from the shared pool.
"""

import pytest

from tests.conftest import _ensure_account_has_egld
from utils.utils_chain import Account


@pytest.fixture
def alice(shard1_account) -> Account:
    """
    Primary farm-test user, pinned to a shard-1 account.

    This overrides the session-wide `alice` fixture for the farm package only,
    so all farm tests share the same shard-1 account as their main actor.
    """
    return shard1_account


@pytest.fixture
def bob(dex_context, test_environment, network_providers) -> Account:
    """
    Primary farm-test user, pinned to a shard-1 account.

    This overrides the session-wide `alice` fixture for the farm package only,
    so all farm tests share the same shard-1 account as their main actor.
    """
    shard1_accounts = dex_context.accounts.get_in_shard(1)
    if not shard1_accounts:
        pytest.skip("No test account available in shard 1")

    account = shard1_accounts[1]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(account, test_environment, network_providers.proxy)

    account.sync_nonce(network_providers.proxy)
    return account
