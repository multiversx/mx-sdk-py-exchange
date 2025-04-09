from pathlib import Path
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider
from context import Context


USERS = ["erd1xd0e3vvn0f8gpyqmah5c5ngssg68uy397km2kegtta0jnf0jmn7stk2vlx", 
        "erd1ndyxz4gpfncmz82qm39yqramgd826mkalhqw8tfmmy0g9jecqc5sa20vek", # user with farming token
        "erd1qqqqqqqqqqqqqqqpqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqzllls8a5w6u", # user with both farm and farming positions 
        "erd1gqyspww4pssv6ck6pl8vtnl9tnwe9hy5d2324mya4rz5ma9dtp9snjgd7f", # user with only farm position
        "erd15gzp9k56cnn8qtfxwlghcxgs74v8jmfk4crex9alygxldmpg9f5s3fd4pl", # user with old farm position
        "erd1yhuhzm8uu4efdts924e50wvaquhx8xg2c038sdu7n8uyh3cgxqeqww97m9", # user with lots of xmex
        "erd1p05np06d4hvcsr2t9ca4nw4rhg52px8qm2j23fh02sqs7rjguhhssksde2",
        "erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97"  # DEX owner address

    ]

TOKENS = [
]

tx_hash = ""
SIMULATOR_URL = "http://localhost:8085"
SIMULATOR_API = "http://localhost:3001"
GENERATE_BLOCKS_URL = f"{SIMULATOR_URL}/simulator/generate-blocks"
GENERATE_BLOCKS_UNTIL_EPOCH_REACHED_URL = f"{SIMULATOR_URL}/simulator/generate-blocks-until-epoch-reached"
PROJECT_ROOT = Path.cwd().parent.parent
proxy = ProxyNetworkProvider(SIMULATOR_URL)
api = ApiNetworkProvider(SIMULATOR_API)
DOCKER_URL = PROJECT_ROOT / "docker"

context = Context()
context.network_provider.proxy = proxy
context.network_provider.api = api