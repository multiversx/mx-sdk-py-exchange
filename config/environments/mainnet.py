"""Mainnet environment configuration."""

config = {
    "DEFAULT_PROXY": "https://gateway.multiversx.com",
    "DEFAULT_API": "https://api.multiversx.com",
    "GRAPHQL": "https://graph.xexchange.com/graphql",
    "HISTORY_PROXY": "",

    "DEFAULT_OWNER": "wallets/C1.pem",
    "DEFAULT_ADMIN": "wallets/C1.pem",
    "DEFAULT_ACCOUNTS": "wallets/C10.pem",

    "DEFAULT_MULTISIG_ADDRESS": "",

    "SF_DEX_REFERENCE_ADDRESS": "erd1qqqqqqqqqqqqqpgqq66xk9gfr4esuhem3jru86wg5hvp33a62jps2fy57p",
    "DEX_OWNER_ADDRESS": "",
    "DEX_ADMIN_ADDRESS": "",
    "SHADOWFORK_FUNDING_ADDRESS": "",

    "DEFAULT_CONFIG_SAVE_PATH": "deploy/configs-mainnet",
    "DEPLOY_STRUCTURE_JSON": "deploy_structure.json",
    
    "FORCE_CONTINUE_PROMPT": False,

    "DEFAULT_ISSUE_TOKEN_PRICE": 50000000000000000,
} 