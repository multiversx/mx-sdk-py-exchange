from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseEnvironmentSettings(BaseSettings):
    """Base environment settings with Pydantic configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Network configuration
    DEFAULT_PROXY: str = Field(
        default="https://gateway.multiversx.com",
        description="Gateway proxy URL"
    )
    DEFAULT_API: str = Field(
        default="https://api.multiversx.com",
        description="API URL"
    )
    GRAPHQL: str = Field(
        default="https://graph.xexchange.com/graphql",
        description="GraphQL service URL"
    )
    HISTORY_PROXY: str = Field(
        default="",
        description="DeepHistory proxy URL (optional)"
    )
    
    # Wallet configuration
    DEFAULT_OWNER: str = Field(
        default="wallets/C1.pem",
        description="Owner wallet path"
    )
    DEFAULT_ADMIN: str = Field(
        default="wallets/C1.pem",
        description="Admin wallet path"
    )
    DEFAULT_ACCOUNTS: str = Field(
        default="wallets/C10.pem",
        description="User accounts wallet path"
    )
    DEFAULT_MULTISIG_ADDRESS: str = Field(
        default="",
        description="Multisig context address"
    )
    
    # DEX configuration
    SF_DEX_REFERENCE_ADDRESS: str = Field(
        default="",
        description="Shadowfork DEX reference address"
    )
    DEX_OWNER_ADDRESS: str = Field(
        default="",
        description="DEX owner address"
    )
    DEX_ADMIN_ADDRESS: str = Field(
        default="",
        description="DEX admin address"
    )
    SHADOWFORK_FUNDING_ADDRESS: str = Field(
        default="",
        description="Shadowfork funding address"
    )
    
    # Deploy configuration
    DEFAULT_CONFIG_SAVE_PATH: str = Field(
        default="deploy/configs-mainnet",
        description="Configuration save path"
    )
    DEPLOY_STRUCTURE_JSON: str = Field(
        default="deploy_structure.json",
        description="Deploy structure JSON filename"
    )
    
    # Operation settings
    FORCE_CONTINUE_PROMPT: bool = Field(
        default=False,
        description="Force continue prompt for all operations"
    )
    # Logging configuration
    LOG_LEVEL: str = Field(
        default="DEBUG",
        description="Logging level"
    )
    LOG_FILE: str = Field(
        default="logs/trace.log",
        description="Logging file"
    )

    DEFAULT_ISSUE_TOKEN_PRICE: int = Field(
        default=50000000000000000,
        description="Default token issue price"
    )
