"""Devnet environment configuration."""

config = {
    "DEFAULT_PROXY": "https://devnet-gateway.multiversx.com",
    "DEFAULT_API": "https://devnet-api.multiversx.com",
    "GRAPHQL": "https://devnet-graph.xexchange.com/graphql",
    "HISTORY_PROXY": "",
    
    "DEFAULT_OWNER": "wallets/devnet-dex-owner.pem",
    "DEFAULT_ADMIN": "wallets/devnet-dex-owner.pem",
    "DEFAULT_ACCOUNTS": "wallets/C10.pem",

    "DEFAULT_MULTISIG_ADDRESS": "",

    "SF_DEX_REFERENCE_ADDRESS": "",
    "DEX_OWNER_ADDRESS": "",
    "DEX_ADMIN_ADDRESS": "",
    "SHADOWFORK_FUNDING_ADDRESS": "",

    "DEFAULT_CONFIG_SAVE_PATH": "deploy/configs-devnet",
    "DEPLOY_STRUCTURE_JSON": "deploy_structure.json",
    
    "FORCE_CONTINUE_PROMPT": False,
    
    "DEFAULT_ISSUE_TOKEN_PRICE": 50000000000000000,
} 