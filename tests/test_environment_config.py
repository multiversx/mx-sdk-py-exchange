#!/usr/bin/env python3
"""
Test script for the environment-based configuration system.
"""

import os
import sys
import unittest
from pathlib import Path

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent.parent))

class TestEnvironmentConfig(unittest.TestCase):
    """Test cases for environment configuration."""
    
    def setUp(self):
        """Set up test environment."""
        # Clear any existing environment variable
        if "MX_DEX_ENV" in os.environ:
            del os.environ["MX_DEX_ENV"]
    
    def test_default_environment(self):
        """Test that the default environment is devnet."""
        import importlib
        import config
        importlib.reload(config)
        
        self.assertEqual(config.CURRENT_ENV.value, "devnet")
    
    def test_mainnet_configuration(self):
        """Test mainnet configuration values."""
        os.environ["MX_DEX_ENV"] = "mainnet"
        
        # Reload config
        import importlib
        import config
        importlib.reload(config)

        self.assertIn("gateway.multiversx.com", config.DEFAULT_PROXY)
        self.assertIn("api.multiversx.com", config.DEFAULT_API)
        self.assertIn("graph.xexchange.com", config.GRAPHQL)
    
    def test_devnet_configuration(self):
        """Test devnet configuration values."""
        os.environ["MX_DEX_ENV"] = "devnet"
        
        # Reload config
        import importlib
        import config
        importlib.reload(config)
        
        self.assertEqual(config.CURRENT_ENV.value, "devnet")
        self.assertIn("devnet-gateway.multiversx.com", config.DEFAULT_PROXY)
        self.assertIn("devnet-api.multiversx.com", config.DEFAULT_API)
        self.assertIn("devnet-graph.xexchange.com", config.GRAPHQL)
    
    def test_chainsim_configuration(self):
        """Test chainsim configuration values."""
        os.environ["MX_DEX_ENV"] = "chainsim"
        
        # Reload config
        import importlib
        import config
        importlib.reload(config)
        
        self.assertEqual(config.CURRENT_ENV.value, "chainsim")
        self.assertEqual(config.DEFAULT_PROXY, "http://localhost:8085")
        self.assertEqual(config.DEFAULT_API, "http://localhost:3001")
        self.assertEqual(config.GRAPHQL, "https://graph.xexchange.com/graphql")
    
    def test_config_save_paths(self):
        """Test that config save paths are environment-specific."""
        # Test mainnet
        os.environ["MX_DEX_ENV"] = "mainnet"
        import importlib
        import config
        importlib.reload(config)
        
        self.assertIn("configs-mainnet", str(config.DEFAULT_CONFIG_SAVE_PATH))
        
        # Test devnet
        os.environ["MX_DEX_ENV"] = "devnet"
        importlib.reload(config)
        
        self.assertIn("configs-devnet", str(config.DEFAULT_CONFIG_SAVE_PATH))
        
        # Test localnet
        os.environ["MX_DEX_ENV"] = "chainsim"
        importlib.reload(config)
        
        self.assertIn("configs-mainnet", str(config.DEFAULT_CONFIG_SAVE_PATH))

    def test_envars_override(self):
        """Test that environment variables override config values."""
        os.environ["DEFAULT_PROXY"] = "https://envvar-gateway.example.com"
        import importlib
        import config
        importlib.reload(config)
        
        self.assertEqual(config.DEFAULT_PROXY, "https://envvar-gateway.example.com")
        
        # Clean up
        del os.environ["DEFAULT_PROXY"]
    
    def test_env_file_override(self):
        """Test that .env file overrides config values."""
        with open(".env", "w") as f:
            f.write("DEFAULT_PROXY=https://env-file-gateway.example.com")
        import importlib
        import config
        importlib.reload(config)

        self.assertEqual(config.DEFAULT_PROXY, "https://env-file-gateway.example.com")
        
        # Clean up
        os.remove(".env")

    def test_envars_priority_override(self):
        """Test that environment variables and .env file override config values."""
        os.environ["DEFAULT_PROXY"] = "https://envvar-gateway.example.com"
        with open(".env", "w") as f:
            f.write("DEFAULT_PROXY=https://env-file-gateway.example.com")
        import importlib
        import config
        importlib.reload(config)

        self.assertEqual(config.DEFAULT_PROXY, "https://envvar-gateway.example.com")
        
        # Clean up
        os.remove(".env")
        del os.environ["DEFAULT_PROXY"]

def run_tests():
    """Run the test suite."""
    unittest.main(verbosity=2)

if __name__ == "__main__":
    run_tests() 