from .base import BaseEnvironmentSettings


class CustomSettings(BaseEnvironmentSettings):
    """Custom environment settings - all values can be overridden via environment variables."""
    
    # All values will use environment variables if set, otherwise fall back to base defaults
    pass
