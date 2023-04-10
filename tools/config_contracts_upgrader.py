from pathlib import Path

HOME = Path().home()
# For Windows:
# HOME = Path("/mnt/c/Users/...")

TOKENS_CONTRACT_ADDRESS = "erd1qqqqqqqqqqqqqqqpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqzllls8a5w6u"
ZERO_CONTRACT_ADDRESS = "erd1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq6gq4hu"
DEFAULT_WORKSPACE = Path(__file__).parent
DEFAULT_OWNER = Path(__file__).parent.absolute() / ".." / ".." / "snippets" / "workspace" / "wallets" / "C1.pem"
DEFAULT_PROXY = "https://devnet-gateway.multiversx.com"
DEFAULT_API = "https://devnet-api.multiversx.com"
GRAPHQL = 'https://graph.xexchange.com/graphql'

# DEX setup
LOCKED_ASSET_FACTORY_BYTECODE_PATH = Path().home() / "dev" / "dex" / "sc-dex-rs" / "locked-asset" / "factory" / "output" / "factory.wasm"
PROXY_BYTECODE_PATH = Path().home() / "dev" / "dex" / "sc-dex-rs" / "locked-asset" / "proxy_dex" / "output" / "proxy_dex.wasm"
STAKING_V2_BYTECODE_PATH = Path().home() / "projects" / "dex" / "dex-v2" / "sc-dex-rs" / "farm-staking" / "farm-staking" / "output" / "farm-staking.wasm"
STAKING_PROXY_BYTECODE_PATH = Path().home() / "dev" / "dex" / "sc-dex-rs" / "dex" / "farm-staking-proxy" / "output" / "farm-staking-proxy.wasm"
ROUTER_V2_BYTECODE_PATH = Path().home() / "projects" / "dex" / "dex-v2" / "sc-dex-rs" / "dex" / "router" / "output" / "router.wasm"
PAIR_V2_BYTECODE_PATH = Path().home() / "projects" / "dex" / "dex-v2" / "sc-dex-rs" / "dex" / "pair" / "output" / "pair.wasm"
FARM_V12_BYTECODE_PATH = Path().home() / "projects" / "dex" / "dex-v2" / "legacy-rs" / "farm.wasm"
FARM_V13_BYTECODE_PATH = Path().home() / "projects" / "dex" / "dex-v2" / "legacy-rs" / "farm_with_lock.wasm"

PROXY_DEX_CONTRACT = "erd1qqqqqqqqqqqqqpgqrc4pg2xarca9z34njcxeur622qmfjp8w2jps89fxnl"
LOCKED_ASSET_FACTORY_CONTRACT = "erd1qqqqqqqqqqqqqpgqjpt0qqgsrdhp2xqygpjtfrpwf76f9nvg2jpsg4q7th"
ROUTER_CONTRACT = "erd1qqqqqqqqqqqqqpgqq66xk9gfr4esuhem3jru86wg5hvp33a62jps2fy57p"
FEES_COLLECTOR_CONTRACT = ""
DEX_OWNER = ""  # only needed for shadowfork

OUTPUT_FOLDER = Path(__file__).parent.absolute() / "outputs_main_dry"

# --------------------------- DO NOT MODIFY BELOW -------------------------------------------

HISTORY_PROXY = ""

DEFAULT_ISSUE_TOKEN_PRICE = 50000000000000000   # TODO: try to override this with testnet define to tidy code up
DEFAULT_GAS_BASE_LIMIT_ISSUE = 60000000
DEFAULT_TOKEN_PREFIX = "TDEX"     # limit yourself to max 6 chars to allow automatic ticker build
DEFAULT_TOKEN_SUPPLY_EXP = 27       # supply to be minted in exponents of 10
DEFAULT_TOKEN_DECIMALS = 18         # decimals on minted tokens in exponents of 10
DEFAULT_MINT_VALUE = 1  # EGLD      # TODO: don't go sub-unitary cause headaches occur. just don't be cheap for now...
DEFAULT_FLOW = "full"

LOCKED_ASSETS = "locked_assets"
PROXIES = "proxies"
PROXIES_V2 = "proxies_v2"
SIMPLE_LOCKS = "simple_locks"
SIMPLE_LOCKS_ENERGY = "simple_locks_energy"
UNSTAKERS = "unstakers"
ROUTER = "router"
ROUTER_V2 = "router_v2"
PAIRS = "pairs"
PAIRS_V2 = "pairs_v2"
PROXY_DEPLOYERS = "proxy_deployers"
FARMS_V2 = "farms_boosted"
FARMS_COMMUNITY = "farms_community"
FARMS_UNLOCKED = "farms_unlocked"
FARMS_LOCKED = "farms_locked"
PRICE_DISCOVERIES = "price_discoveries"
STAKINGS = "stakings"
STAKINGS_V2 = "stakings_v2"
METASTAKINGS = "metastakings"
METASTAKINGS_V2 = "metastakings_v2"
FEES_COLLECTORS = "fees_collectors"

DEFAULT_CONFIG_SAVE_PATH = Path(__file__).parent.absolute() / "deploy" / "configs-devnet"
DEPLOY_STRUCTURE_JSON = DEFAULT_CONFIG_SAVE_PATH / "deploy_structure_main.json"

CROSS_SHARD_DELAY = 60
INTRA_SHARD_DELAY = 10


def get_default_tokens_file():
    return DEFAULT_WORKSPACE / "tokens.json"

