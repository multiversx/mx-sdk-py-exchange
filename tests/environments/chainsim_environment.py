"""
Chain Simulator test environment.

Provides a controllable local blockchain for testing with:
- Full control over block/epoch progression
- State loading/saving capabilities
- Fast transaction finalization
- Isolated testing environment
"""

from pathlib import Path
from typing import Optional, List
from multiversx_sdk import NetworkProviderConfig, ProxyNetworkProvider

from tests.environments.base_environment import TestEnvironment
from tools.chain_simulator_connector import ChainSimulator
from utils.utils_tx import NetworkProviders
from utils.logger import get_logger


logger = get_logger(__name__)


class ChainsimEnvironment(TestEnvironment):
    """
    Chain Simulator environment - controllable, clean slate blockchain.

    Features:
    - Start/stop local blockchain via docker-compose
    - Generate blocks on demand (POST /simulator/generate-blocks)
    - Advance epochs programmatically
    - Optionally load pre-saved state from folder
    - ~50 second startup time for full chain

    Security Consideration:
    Chain simulator runs in a docker container. Ensure docker daemon is running
    and user has proper permissions. State files may contain sensitive addresses.
    """

    def __init__(self,
                 docker_path: Path,
                 state_path: Optional[Path] = None,
                 initial_block: int = 0,
                 initial_round: int = 0,
                 initial_epoch: int = 0,
                 proxy_url: str = "http://localhost:8085",
                 api_url: str = "http://localhost:3001"):
        """
        Initialize chain simulator environment.

        Args:
            docker_path: Path to chain simulator docker-compose directory
            state_path: Optional path to folder with pre-saved blockchain state
            initial_block: Starting block nonce (default 0)
            initial_epoch: Starting epoch (default 0)
            proxy_url: Chain simulator proxy URL (default: http://localhost:8085)
            api_url: Chain simulator API URL (default: http://localhost:3001)

        Example:
            >>> docker_path = Path.home() / "Projects/chain-simulator"
            >>> env = ChainsimEnvironment(docker_path)
            >>> env.setup()
        """
        self.docker_path = docker_path
        self.state_path = state_path
        self.initial_block = initial_block
        self.initial_round = initial_round
        self.initial_epoch = initial_epoch
        self.proxy_url = proxy_url
        self.api_url = api_url
        self.chain_sim: Optional[ChainSimulator] = None
        self.loaded_accounts: List[str] = []
        self._proxy: Optional[ProxyNetworkProvider] = None
        self._network_providers: Optional[NetworkProviders] = None
        self._externally_started: bool = False
        self._state_loaded: bool = False

        logger.info(f"Initialized ChainsimEnvironment with docker_path={docker_path}")
        if state_path:
            logger.info(f"Will load state from: {state_path}")

    def setup(self) -> None:
        """
        Start chain simulator and optionally load state.

        Process:
        1. Initialize ChainSimulator with docker path
        2. Check if chain simulator is already running
        3. If not running, start docker containers (blocks until ready, ~50s)
        4. Advance to epoch 1+ to ensure all protocol features (ESDT, etc.) are enabled
        5. If state_path provided, load state via simulator API
        6. Initialize network proxy

        Raises:
            RuntimeError: If docker fails to start or state loading fails
        """
        self.chain_sim = ChainSimulator(self.docker_path)

        # Check if chain simulator is already running (e.g. started externally via docker-compose)
        if self.chain_sim.is_running():
            logger.info("Chain simulator already running, connecting to existing instance")
            self._externally_started = True
        else:
            logger.info("Starting chain simulator...")
            self.chain_sim.start(
                block=self.initial_block,
                round=self.initial_round,
                epoch=self.initial_epoch
            )

            if not self.chain_sim.is_running():
                raise RuntimeError("Chain simulator failed to start")

        # Advance past epoch 0 (ESDT disabled) to epoch 10.
        # firstWeekStartEpoch is overridden to 0 during state loading, so
        # epoch 7+ gives week >= 1 for fees collector. Epoch 10 adds margin.
        target_epoch = 10
        logger.info(f"Advancing to epoch {target_epoch}...")
        self.chain_sim.advance_epochs_to_epoch(target_epoch)

        logger.info("Chain simulator ready")

        # Initialize proxy (for internal use)
        self._proxy = ProxyNetworkProvider(self.chain_sim.proxy_url, None, NetworkProviderConfig("py-sdk-exchange"))
        assert self._proxy is not None, "Failed to initialize proxy"

        # Initialize network providers
        self._network_providers = NetworkProviders(self.api_url, self.proxy_url)

        # Load pre-saved state if provided
        if self.state_path and self.state_path.exists():
            logger.info(f"Loading state from {self.state_path}")
            self.loaded_accounts = self.chain_sim.init_state_from_folder(
                self.state_path, filter_safe_price=True
            )
            self._state_loaded = True
            logger.info(f"Loaded state for {len(self.loaded_accounts)} accounts")

            # Generate a block to finalize state loading
            self.advance_blocks(1)

        # Verify connectivity
        status = self._proxy.get_network_status()
        logger.info(f"Chain simulator ready at epoch {status.current_epoch}, block {status.highest_final_block_nonce}")

    def teardown(self) -> None:
        """
        Stop chain simulator and cleanup docker containers.

        If the simulator was started externally (detected as already running
        during setup), this only clears internal references without stopping
        the docker containers.

        Note: Does NOT save current blockchain state. Use chain_sim.save_state()
        explicitly if you need to preserve state for future tests.
        """
        if self.chain_sim:
            if self._externally_started:
                logger.info("Chain simulator was externally started, leaving it running")
            else:
                logger.info("Stopping chain simulator...")
                self.chain_sim.stop()
                logger.info("Chain simulator stopped")
            self.chain_sim = None
            self._proxy = None
            self._network_providers = None

    def get_network_providers(self) -> NetworkProviders:
        """
        Get network providers for blockchain interactions.

        Returns:
            NetworkProviders: Network providers (API + Proxy) configured for chain simulator

        Raises:
            RuntimeError: If setup() was not called or simulator is not running
        """
        if not self._network_providers:
            raise RuntimeError("Chain simulator not running. Call setup() first.")
        return self._network_providers

    def supports_time_control(self) -> bool:
        """
        Check if this environment supports block/epoch manipulation.

        Returns:
            bool: Always True for chain simulator
        """
        return True

    def has_pre_existing_state(self) -> bool:
        """
        Check if environment has pre-deployed contracts.

        Returns:
            bool: True if state_path was provided and state was loaded, False for clean slate
        """
        return self.state_path is not None and self._state_loaded

    def advance_blocks(self, count: int) -> None:
        """
        Generate new blocks immediately.

        Uses POST /simulator/generate-blocks/{count} to produce blocks instantly.
        This is CRITICAL for test speed - no waiting for block time.

        Args:
            count: Number of blocks to generate

        Raises:
            RuntimeError: If simulator not running

        Security Note:
        Generated blocks have deterministic timestamps. If testing time-sensitive
        logic, be aware blocks are instant, not spaced by real time.
        """
        if not self.chain_sim:
            raise RuntimeError("Chain simulator not running")

        logger.debug(f"Generating {count} block(s)")
        self.chain_sim.advance_blocks(count)

        # Log new state
        new_block = self.get_current_block()
        new_epoch = self.get_current_epoch()
        logger.debug(f"Advanced to block {new_block}, epoch {new_epoch}")

    def advance_to_epoch(self, epoch: int) -> None:
        """
        Advance blockchain to specific epoch.

        Calculates blocks needed based on blocks_per_epoch and generates them.
        If already at or past target epoch, does nothing.

        Args:
            epoch: Target epoch number

        Raises:
            RuntimeError: If simulator not running
            ValueError: If epoch is negative

        Example:
            >>> env.advance_to_epoch(10)  # Jump to epoch 10
            >>> env.advance_to_epoch(5)   # No-op, already past epoch 5
        """
        if not self.chain_sim:
            raise RuntimeError("Chain simulator not running")

        if epoch < 0:
            raise ValueError(f"Target epoch must be non-negative: {epoch}")

        current_epoch = self.get_current_epoch()

        if current_epoch >= epoch:
            logger.debug(f"Already at epoch {current_epoch} >= {epoch}, skipping")
            return

        logger.info(f"Advancing from epoch {current_epoch} to {epoch}")
        self.chain_sim.advance_epochs_to_epoch(epoch)

        new_epoch = self.get_current_epoch()
        logger.info(f"Advanced to epoch {new_epoch}")

    def get_current_epoch(self) -> int:
        """
        Get current blockchain epoch.

        Returns:
            int: Current epoch number

        Raises:
            RuntimeError: If simulator not running
        """
        if not self._proxy:
            raise RuntimeError("Chain simulator not running")

        return self._proxy.get_network_status().current_epoch

    def get_current_block(self) -> int:
        """
        Get current blockchain nonce (block number).

        Returns:
            int: Current block nonce

        Raises:
            RuntimeError: If simulator not running
        """
        if not self._proxy:
            raise RuntimeError("Chain simulator not running")

        return self._proxy.get_network_status().highest_final_block_nonce

    def get_loaded_accounts(self) -> List[str]:
        """
        Get list of accounts loaded from state.

        Returns:
            List[str]: Bech32 addresses of loaded accounts (empty if no state loaded)
        """
        return self.loaded_accounts

    def generate_blocks_until_tx_processed(self, tx_hash: str, max_num_blocks: int = 30):
        """
        Generate blocks until a specific transaction is fully processed.

        Uses the chain simulator's dedicated endpoint that handles cross-shard
        transaction finalization automatically.

        Args:
            tx_hash: Transaction hash to wait for
            max_num_blocks: Maximum blocks to generate (default 30)

        Raises:
            RuntimeError: If simulator not running
        """
        if not self.chain_sim:
            raise RuntimeError("Chain simulator not running")

        logger.debug(f"Generating blocks until tx processed: {tx_hash}")
        self.chain_sim.generate_blocks_until_tx_processed(tx_hash, max_num_blocks)

    def is_running(self) -> bool:
        """
        Check if chain simulator is running.

        Returns:
            bool: True if simulator is responsive
        """
        if not self.chain_sim:
            return False
        return self.chain_sim.is_running()
