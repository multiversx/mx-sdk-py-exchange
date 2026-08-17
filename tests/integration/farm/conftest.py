"""
Farm-package pytest fixtures.

Re-exports the shard-1 `alice`/`bob` overrides shared with farm_staking (see
tests/integration/shared_fixtures.py) so pytest picks them up for every test
in this package.
"""

from tests.integration.shared_fixtures import alice, bob

__all__ = ["alice", "bob"]
