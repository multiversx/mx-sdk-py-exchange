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

def run_tests():
    """Run the test suite."""
    unittest.main(verbosity=2)

if __name__ == "__main__":
    run_tests() 