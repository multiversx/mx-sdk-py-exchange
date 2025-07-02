#!/usr/bin/env python3
"""
Script to display current configuration status and environment information.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent))

def show_config_status():
    """Display current configuration status."""
    try:
        import config
        from config.environments import Environment
        
        print("Configuration Status")
        print("=" * 50)
        print(f"Current Environment: {config.CURRENT_ENV.value.upper()}")
        print(f"Environment Variable MX_DEX_ENV: {os.getenv('MX_DEX_ENV', f'Not set (defaults to {config.CURRENT_ENV.value.upper()})')}")
        print()
        
        print("Network Configuration:")
        print(f"  Proxy: {config.DEFAULT_PROXY}")
        print(f"  API: {config.DEFAULT_API}")
        print(f"  GraphQL: {config.GRAPHQL}")
        print()
        
        print("Wallet Configuration:")
        print(f"  Owner: {config.DEFAULT_OWNER}")
        print(f"  Admin: {config.DEFAULT_ADMIN}")
        print(f"  Accounts: {config.DEFAULT_ACCOUNTS}")
        print()
        
        print("Deploy Configuration:")
        print(f"  Config Save Path: {config.DEFAULT_CONFIG_SAVE_PATH}")
        print(f"  Deploy Structure: {config.DEPLOY_STRUCTURE_JSON}")
        print()
        
        print("Available Environments:")
        for env in Environment:
            print(f"  - {env.value}")
        
        print()
        print("To switch environments, set the MX_DEX_ENV environment variable:")
        print("  export MX_DEX_ENV=devnet")
        print("  export MX_DEX_ENV=chainsim")
        print("  export MX_DEX_ENV=mainnet")
        
    except ImportError as e:
        print(f"Error importing configuration: {e}")
        print("Make sure you're running this script from the project root directory.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    show_config_status()