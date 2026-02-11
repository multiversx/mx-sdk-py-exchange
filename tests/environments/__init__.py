"""
Environment abstraction layer for blockchain testing.

This module provides environment adapters that allow tests to run seamlessly
across different blockchain networks:

- ChainsimEnvironment: Local chain simulator (controllable, fast)
- DevnetEnvironment: Live test network (real conditions)
- ShadowforkEnvironment: Mainnet clone (realistic data)

Example:
    >>> from tests.environments import ChainsimEnvironment
    >>> env = ChainsimEnvironment(docker_path=Path("/path/to/simulator"))
    >>> env.setup()
    >>> proxy = env.get_proxy()
    >>> env.advance_blocks(10)  # Only works on chainsim
    >>> env.teardown()
"""

from tests.environments.base_environment import TestEnvironment
from tests.environments.chainsim_environment import ChainsimEnvironment
from tests.environments.devnet_environment import DevnetEnvironment
from tests.environments.shadowfork_environment import ShadowforkEnvironment


__all__ = [
    "TestEnvironment",
    "ChainsimEnvironment",
    "DevnetEnvironment",
    "ShadowforkEnvironment",
]
