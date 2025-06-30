"""Local environment configuration."""

config = {
    "DEFAULT_PROXY": "http://localhost:8085",
    "DEFAULT_API": "http://localhost:3001",
    "GRAPHQL": "https://graph.xexchange.com/graphql",
    "HISTORY_PROXY": "",
    
    "DEFAULT_OWNER": "wallets/C1.pem",
    "DEFAULT_ADMIN": "wallets/C1.pem",
    "DEFAULT_ACCOUNTS": "wallets/C10.pem",

    "DEFAULT_MULTISIG_ADDRESS": "",

    "SF_DEX_REFERENCE_ADDRESS": "erd1qqqqqqqqqqqqqpgqq66xk9gfr4esuhem3jru86wg5hvp33a62jps2fy57p",
    "DEX_OWNER_ADDRESS": "erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97",
    "DEX_ADMIN_ADDRESS": "erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97",
    "SHADOWFORK_FUNDING_ADDRESS": "erd1rf4hv70arudgzus0ymnnsnc4pml0jkywg2xjvzslg0mz4nn2tg7q7k0t6p",

    "DEFAULT_CONFIG_SAVE_PATH": "deploy/configs-mainnet",
    "DEPLOY_STRUCTURE_JSON": "deploy_structure.json",
    
    "FORCE_CONTINUE_PROMPT": False,
    
    "DEFAULT_ISSUE_TOKEN_PRICE": 50000000000000000,
} 