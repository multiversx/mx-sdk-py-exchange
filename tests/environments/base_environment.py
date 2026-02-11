"""
Base environment abstraction for blockchain testing.

This module defines the abstract interface that all test environments must implement,
enabling tests to run seamlessly across chain simulator, devnet, and shadowfork.
"""

from abc import ABC, abstractmethod
from utils.utils_tx import NetworkProviders
from utils.logger import get_logger


logger = get_logger(__name__)


class TestEnvironment(ABC):
    """
    Abstract base class for blockchain test environments.

    Implementations must support:
    - Setup/teardown lifecycle
    - Network proxy access
    - Block/epoch progression (where supported)
    - State management capabilities
    """

    @abstractmethod
    def setup(self) -> None:
        """
        Initialize the test environment.

        For chainsim: Start docker containers, optionally load state
        For devnet/shadowfork: Verify network connectivity

        Raises:
            RuntimeError: If environment setup fails
        """
        pass

    @abstractmethod
    def teardown(self) -> None:
        """
        Cleanup the test environment.

        For chainsim: Stop docker containers
        For devnet/shadowfork: No action (persistent networks)
        """
        pass

    @abstractmethod
    def get_network_providers(self) -> NetworkProviders:
        """
        Get network providers for blockchain interactions.

        Returns:
            NetworkProviders: Configured network providers (API + Proxy) for this environment
        """
        pass

    @abstractmethod
    def supports_time_control(self) -> bool:
        """
        Check if this environment supports block/epoch manipulation.

        Returns:
            bool: True for chainsim, False for devnet/shadowfork
        """
        pass

    @abstractmethod
    def has_pre_existing_state(self) -> bool:
        """
        Check if environment has pre-deployed contracts and state.

        Returns:
            bool: False for clean chainsim, True for devnet/shadowfork
        """
        pass

    @abstractmethod
    def advance_blocks(self, count: int) -> None:
        """
        Generate new blocks (if supported).

        For chainsim: POST to simulator API
        For devnet/shadowfork: Wait for natural block time

        Args:
            count: Number of blocks to advance

        Raises:
            NotImplementedError: If time control not supported (use wait_blocks)
        """
        pass

    @abstractmethod
    def advance_to_epoch(self, epoch: int) -> None:
        """
        Advance blockchain to specific epoch (if supported).

        For chainsim: Calculate blocks needed and generate
        For devnet/shadowfork: Not supported

        Args:
            epoch: Target epoch number

        Raises:
            NotImplementedError: If epoch control not supported
        """
        pass

    @abstractmethod
    def get_current_epoch(self) -> int:
        """
        Get current blockchain epoch.

        Returns:
            int: Current epoch number
        """
        pass

    @abstractmethod
    def get_current_block(self) -> int:
        """
        Get current blockchain nonce (block number).

        Returns:
            int: Current block nonce
        """
        pass

    def wait_for_transaction(self, tx_hash: str, blocks: int = 1) -> None:
        """
        Wait for transaction to be processed.

        For chainsim: Advance blocks
        For devnet/shadowfork: Sleep for block time

        Args:
            tx_hash: Transaction hash to wait for
            blocks: Number of blocks to wait (default 1)
        """
        if self.supports_time_control():
            self.advance_blocks(blocks)
            logger.debug(f"Advanced {blocks} block(s) for tx {tx_hash}")
        else:
            import time
            wait_time = blocks * 6  # ~6 seconds per block
            logger.debug(f"Waiting {wait_time}s for tx {tx_hash}")
            time.sleep(wait_time)

    def __repr__(self) -> str:
        """String representation of environment"""
        return f"{self.__class__.__name__}(time_control={self.supports_time_control()}, pre_existing_state={self.has_pre_existing_state()})"
