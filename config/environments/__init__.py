from enum import Enum
from pathlib import Path

class Environment(Enum):
    MAINNET = "mainnet"
    DEVNET = "devnet"
    TESTNET = "testnet"
    SHADOWFORK4 = "shadowfork4"
    CHAINSIM = "chainsim"
    CUSTOM = "custom"

def get_environment_config(env: Environment):
    """Get environment-specific configuration based on the environment enum."""
    if env == Environment.MAINNET:
        from .mainnet import config
    elif env == Environment.DEVNET:
        from .devnet import config
    elif env == Environment.TESTNET:
        from .testnet import config
    elif env == Environment.SHADOWFORK4:
        from .shadowfork4 import config
    elif env == Environment.CHAINSIM:
        from .chainsim import config
    elif env == Environment.CUSTOM:
        from .custom import config
    else:
        raise ValueError(f"Unknown environment: {env}")
    return config 
