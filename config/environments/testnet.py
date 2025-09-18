from .base import BaseEnvironmentSettings


class TestnetSettings(BaseEnvironmentSettings):
    """Testnet environment settings."""
    
    # Override defaults for testnet
    DEFAULT_PROXY: str = "https://testnet-gateway.multiversx.com"
    DEFAULT_API: str = "https://testnet-api.multiversx.com"
    GRAPHQL: str = "https://testnet-graph.xexchange.com/graphql"
    
    DEFAULT_OWNER: str = "wallets/testnet-dex-owner.pem"
    DEFAULT_ADMIN: str = "wallets/testnet-dex-owner.pem"

    DEFAULT_CONFIG_SAVE_PATH: str = "deploy/configs-testnet"
