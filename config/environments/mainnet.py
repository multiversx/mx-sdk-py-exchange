from .base import BaseEnvironmentSettings


class MainnetSettings(BaseEnvironmentSettings):
    """Mainnet environment settings."""
    
    # Override defaults for mainnet
    DEFAULT_PROXY: str = "https://gateway.multiversx.com"
    DEFAULT_API: str = "https://api.multiversx.com"
    GRAPHQL: str = "https://graph.xexchange.com/graphql"
    
    DEFAULT_CONFIG_SAVE_PATH: str = "deploy/configs-mainnet"


# Create instance for backward compatibility
config = MainnetSettings().to_dict() 