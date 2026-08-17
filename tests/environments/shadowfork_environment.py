"""
Shadowfork test environment.

Provides access to shadowfork (mainnet clone) with:
- Complete mainnet state snapshot
- Address impersonation capabilities
- Real contract deployments and data
- Isolated from mainnet (safe testing)
"""

from typing import Optional
from multiversx_sdk import Address

from tests.environments.devnet_environment import DevnetEnvironment
from utils.logger import get_logger


logger = get_logger(__name__)


class ShadowforkEnvironment(DevnetEnvironment):
    """
    Shadowfork environment - mainnet clone for realistic testing.

    Features:
    - Cloned mainnet state (all contracts, balances, storage)
    - Address impersonation (act as any address without PEM)
    - Real DEX contracts with actual liquidity data
    - Isolated network (no mainnet impact)

    Use Cases:
    - Test against production contract versions
    - Validate upgrades with real state
    - Debug mainnet issues in safe environment
    - Stress test with realistic data

    Limitations:
    - Same as devnet (no time control, ~6s blocks)
    - Requires shadowfork infrastructure running
    - State snapshot may be stale (not live)

    Security Considerations:
    - Shadowfork state includes real user addresses and balances
    - Use ONLY for testing, never production operations
    - Impersonation is powerful - verify you're on shadowfork, not mainnet
    - Shadowfork transactions are NOT on mainnet (isolated network)
    """

    def __init__(self,
                 proxy_url: str,
                 api_url: str,
                 reference_address: Optional[str] = None,
                 dex_owner_address: Optional[str] = None):
        """
        Initialize shadowfork environment.

        Args:
            proxy_url: Shadowfork gateway URL (must contain 'shadowfork')
            api_url: Shadowfork API URL
            reference_address: Optional reference contract to verify shadowfork state
            dex_owner_address: Optional DEX owner address for impersonation

        Example:
            >>> env = ShadowforkEnvironment(
            ...     proxy_url="https://shadowfork-gateway.example.com",
            ...     api_url="https://shadowfork-api.example.com",
            ...     reference_address="erd1qqqqqqqqqqqqqpgq..."  # Known mainnet contract
            ... )
            >>> env.setup()

        Raises:
            ValueError: If proxy_url doesn't contain 'shadowfork' (safety check)
        """
        # Safety check: ensure we're connecting to shadowfork, not mainnet
        if "shadowfork" not in proxy_url.lower():
            raise ValueError(
                f"Shadowfork URL must contain 'shadowfork': {proxy_url}\n"
                "This is a safety check to prevent accidental mainnet usage."
            )

        super().__init__(proxy_url, api_url)

        self.reference_address = reference_address
        self.dex_owner_address = dex_owner_address

        logger.info(f"Initialized ShadowforkEnvironment with proxy_url={proxy_url}")
        if reference_address:
            logger.info(f"Reference contract: {reference_address}")
        if dex_owner_address:
            logger.info(f"DEX owner for impersonation: {dex_owner_address}")

    def setup(self) -> None:
        """
        Connect to shadowfork and verify state is loaded.

        Process:
        1. Connect to shadowfork gateway (via DevnetEnvironment.setup)
        2. If reference_address provided, verify contract exists
        3. If reference_address is a contract, fetch owner for impersonation
        4. Verify chain ID is NOT mainnet (safety check)

        Raises:
            RuntimeError: If shadowfork unreachable or state invalid
            ValueError: If accidentally connected to mainnet
        """
        logger.info("Connecting to shadowfork...")

        # Connect via parent class
        super().setup()

        # CRITICAL: Verify we're NOT on mainnet
        chain_id = self._proxy.get_network_config().chain_id
        if chain_id == "1":  # Mainnet chain ID
            raise ValueError(
                "DANGER: Connected to MAINNET, not shadowfork!\n"
                f"Chain ID: {chain_id}\n"
                "Aborting to prevent mainnet transactions."
            )

        logger.info(f"Verified shadowfork connection (chain ID: {chain_id})")

        # Verify reference contract exists (if provided)
        if self.reference_address:
            self._verify_reference_contract()

    def _verify_reference_contract(self) -> None:
        """
        Verify reference contract exists in shadowfork state.

        This confirms shadowfork has loaded mainnet state correctly.
        If reference contract is missing, shadowfork may not be ready.

        Raises:
            RuntimeError: If reference contract not found
        """
        try:
            address = Address.new_from_bech32(self.reference_address)
            account = self._proxy.get_account(address)

            logger.info(f"Reference contract verified: {self.reference_address}")
            logger.debug(f"Balance: {account.balance}, Nonce: {account.nonce}")

            # If it's a smart contract, get owner for impersonation
            if address.is_smart_contract():
                owner = account.contract_owner_address
                if owner:
                    logger.info(f"Contract owner: {owner.to_bech32()}")

                    # Auto-set dex_owner_address if not provided
                    if not self.dex_owner_address:
                        self.dex_owner_address = owner.to_bech32()
                        logger.info(f"Auto-detected DEX owner: {self.dex_owner_address}")

        except Exception as e:
            raise RuntimeError(
                f"Failed to verify reference contract {self.reference_address}: {e}\n"
                "Shadowfork may not have loaded mainnet state correctly."
            )

    def get_dex_owner_address(self) -> Optional[str]:
        """
        Get DEX owner address for impersonation.

        This address can be used to execute privileged operations on
        shadowfork without needing the actual PEM file.

        Returns:
            Optional[str]: DEX owner bech32 address, or None if not set

        Example:
            >>> owner_addr = env.get_dex_owner_address()
            >>> deployer_account.address = Address(owner_addr)
            >>> # Now deployer_account can call owner-only functions
        """
        return self.dex_owner_address

    def supports_impersonation(self) -> bool:
        """
        Check if address impersonation is available.

        Returns:
            bool: True if shadowfork supports impersonation
        """
        return True  # Shadowfork allows acting as any address

    def has_mainnet_state(self) -> bool:
        """
        Check if this environment has mainnet state.

        Returns:
            bool: Always True for shadowfork
        """
        return True

    def __repr__(self) -> str:
        """String representation with shadowfork-specific info"""
        return (
            f"ShadowforkEnvironment("
            f"proxy={self.proxy_url}, "
            f"reference={self.reference_address}, "
            f"owner={self.dex_owner_address})"
        )
