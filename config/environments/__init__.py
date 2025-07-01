from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .base import BaseEnvironmentSettings


class Environment(Enum):
    MAINNET = "mainnet"
    DEVNET = "devnet"
    TESTNET = "testnet"
    SHADOWFORK4 = "shadowfork4"
    CHAINSIM = "chainsim"
    CUSTOM = "custom"


class EnvironmentSelector(BaseSettings):
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    MX_DEX_ENV: str = Field(
        default="devnet",
        description="Environment name"
    )

    def get_environment(self) -> Environment:
        return Environment[self.MX_DEX_ENV.upper()]

    def get_environment_settings(self) -> BaseEnvironmentSettings:
        """Get environment-specific Pydantic settings instance."""
        env = self.get_environment()
        if env == Environment.MAINNET:
            from .mainnet import MainnetSettings
            return MainnetSettings()
        elif env == Environment.DEVNET:
            from .devnet import DevnetSettings
            return DevnetSettings()
        elif env == Environment.TESTNET:
            from .testnet import TestnetSettings
            return TestnetSettings()
        elif env == Environment.SHADOWFORK4:
            from .shadowfork4 import Shadowfork4Settings
            return Shadowfork4Settings()
        elif env == Environment.CHAINSIM:
            from .chainsim import ChainSimSettings
            return ChainSimSettings()
        elif env == Environment.CUSTOM:
            from .custom import CustomSettings
            return CustomSettings()
        else:
            raise ValueError(f"Unknown environment: {env}") 
