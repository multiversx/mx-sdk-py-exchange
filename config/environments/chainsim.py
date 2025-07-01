from .base import BaseEnvironmentSettings


class ChainSimSettings(BaseEnvironmentSettings):
    """Chain simulator environment settings."""
    
    # Override defaults for chain simulator
    DEFAULT_PROXY: str = "http://localhost:8085"
    DEFAULT_API: str = "http://localhost:3001"
    GRAPHQL: str = "https://graph.xexchange.com/graphql"

    DEFAULT_OWNER: str = "wallets/C1.pem"
    DEFAULT_ADMIN: str = "wallets/C1.pem"

    DEFAULT_CONFIG_SAVE_PATH: str = "deploy/configs-mainnet"

    SF_DEX_REFERENCE_ADDRESS: str = "erd1qqqqqqqqqqqqqpgqq66xk9gfr4esuhem3jru86wg5hvp33a62jps2fy57p"
    DEX_OWNER_ADDRESS: str = "erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97"
    DEX_ADMIN_ADDRESS: str = "erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97"
    SHADOWFORK_FUNDING_ADDRESS: str = "erd1rf4hv70arudgzus0ymnnsnc4pml0jkywg2xjvzslg0mz4nn2tg7q7k0t6p"
