"""
Pytest configuration and fixtures for smart contract integration testing.

This module provides:
- CLI options for environment selection (--env, --docker-path)
- Environment fixtures (test_environment, network_proxy)
- Blockchain control fixtures (blockchain_controller)
- Contract fixtures (dex_context, pair_contract, farm_contract, router_contract)
- Account fixtures (deployer_account, test_accounts, alice, bob)

Fixtures are scoped appropriately:
- session: Shared across all tests (environment, dex_context)
- function: Fresh for each test (blockchain_controller)

Usage:
    pytest --env=chainsim tests/integration/pair/
    pytest --env=devnet tests/integration/pair/
    pytest --env=shadowfork --docker-path=/path/to/simulator tests/
"""

import os
import pytest
import time
from pathlib import Path
from typing import List, Optional

import config
from context import Context
from tests.environments import ChainsimEnvironment, DevnetEnvironment, ShadowforkEnvironment, TestEnvironment
from contracts.pair_contract import PairContract
from contracts.farm_contract import FarmContract
from contracts.router_contract import RouterContract
from tools.chain_simulator_connector import get_shard_chronology_in_folder
from utils.utils_chain import Account, WrapperAddress as Address, nominated_amount
from utils.utils_tx import NetworkProviders
from utils.logger import get_logger
from multiversx_sdk import ProxyNetworkProvider


logger = get_logger(__name__)


# ============================================================================
# PYTEST CLI OPTIONS
# ============================================================================

def pytest_addoption(parser):
    """
    Add custom CLI options for test configuration.

    Options:
        --env: Select test environment (chainsim, devnet, shadowfork)
        --docker-path: Path to chain simulator docker-compose directory
        --skip-deploy: Skip contract deployment (use existing contracts)
    """
    parser.addoption(
        "--env",
        action="store",
        default="chainsim",
        help="Test environment: chainsim (default), devnet, shadowfork"
    )
    parser.addoption(
        "--docker-path",
        action="store",
        default=str(Path(__file__).parent.parent),
        help="Path to chain simulator docker-compose directory (only for chainsim)"
    )
    parser.addoption(
        "--skip-deploy",
        action="store_true",
        default=False,
        help="Skip contract deployment and use existing deployed contracts"
    )


# ============================================================================
# ENVIRONMENT FIXTURES (Session Scope)
# ============================================================================

@pytest.fixture(scope="session")
def test_env_name(request) -> str:
    """
    Get environment name from CLI.

    Returns:
        str: Environment name (chainsim, devnet, or shadowfork)
    """
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def test_environment(test_env_name, request) -> TestEnvironment:
    """
    Initialize and provide the test environment.

    This is the master fixture that creates the appropriate environment
    (chainsim/devnet/shadowfork) based on CLI arguments.

    Lifecycle:
    1. Set MX_DEX_ENV environment variable
    2. Reload config module to apply environment settings
    3. Create environment instance based on --env flag
    4. Call setup() to initialize environment
    5. Yield environment to tests
    6. Call teardown() to cleanup

    Returns:
        TestEnvironment: Configured and initialized environment

    Raises:
        ValueError: If unknown environment specified
        RuntimeError: If environment setup fails
    """
    # Set environment variable for config loading
    os.environ["MX_DEX_ENV"] = test_env_name
    import importlib
    importlib.reload(config)

    logger.info(f"Initializing test environment: {test_env_name}")

    # Create appropriate environment
    if test_env_name == "chainsim":
        docker_path = Path(request.config.getoption("--docker-path"))
        state_path = config.DEFAULT_WORKSPACE / "states" if (config.DEFAULT_WORKSPACE / "states").exists() else None

        if not docker_path.exists():
            logger.warning(f"Chain simulator docker path does not exist: {docker_path}")
            logger.warning("Continuing anyway - docker-compose may handle this")

        if state_path:
            chronology = get_shard_chronology_in_folder(state_path)
            # chronology = None
            if chronology:
                env = ChainsimEnvironment(docker_path, state_path, chronology["block"], chronology["round"], chronology["epoch"])
            else:
                env = ChainsimEnvironment(docker_path, state_path)
        else:
            env = ChainsimEnvironment(docker_path)

    elif test_env_name == "devnet":
        env = DevnetEnvironment(config.DEFAULT_PROXY, config.DEFAULT_API)

    elif test_env_name == "shadowfork":
        if "shadowfork" not in config.DEFAULT_PROXY.lower():
            raise ValueError(
                f"DEFAULT_PROXY must contain 'shadowfork' for shadowfork environment: {config.DEFAULT_PROXY}\n"
                "Set MX_DEX_ENV=shadowfork and configure proxy URL in config or .env"
            )
        env = ShadowforkEnvironment(
            config.DEFAULT_PROXY,
            config.DEFAULT_API,
            config.SF_DEX_REFERENCE_ADDRESS,
            config.DEX_OWNER_ADDRESS
        )

    else:
        raise ValueError(f"Unknown environment: {test_env_name}. Use: chainsim, devnet, shadowfork")

    # Setup environment
    logger.info(f"Setting up {env}")
    env.setup()

    yield env

    # Teardown
    logger.info(f"Tearing down {env}")
    env.teardown()


@pytest.fixture(scope="session")
def network_providers(test_environment) -> NetworkProviders:
    """
    Get network providers for blockchain interactions.

    Returns:
        NetworkProviders: Configured network providers (API + Proxy) from test environment
    """
    return test_environment.get_network_providers()


@pytest.fixture(scope="session")
def network_proxy(network_providers) -> ProxyNetworkProvider:
    """
    Get network proxy for blockchain interactions.

    Deprecated: Use network_providers instead. This fixture is kept for backward
    compatibility with existing code that expects ProxyNetworkProvider.

    Returns:
        ProxyNetworkProvider: Configured proxy from network providers
    """
    return network_providers.proxy


# ============================================================================
# BLOCKCHAIN CONTROL FIXTURES (Function Scope)
# ============================================================================

@pytest.fixture
def blockchain_controller(test_environment):
    """
    Provide blockchain control helper.

    This helper adapts to the environment's capabilities:
    - Chainsim: Generates blocks instantly
    - Devnet/Shadowfork: Waits for natural block progression

    Usage:
        def test_swap(pair_contract, alice, blockchain_controller):
            tx_hash = pair_contract.swap(...)
            blockchain_controller.wait_for_tx(tx_hash)

    Returns:
        BlockchainController: Helper for time control
    """

    class BlockchainController:
        """Helper class for controlling blockchain progression"""

        def __init__(self, env: TestEnvironment):
            self.env = env

        def wait_for_tx(self, tx_hash: str, blocks: int = 1):
            """
            Wait for transaction to be processed.

            For chain simulator: uses generate-blocks-until-transaction-processed
            endpoint which handles cross-shard finalization automatically.
            Falls back to generating fixed block count if endpoint unavailable.

            Args:
                tx_hash: Transaction hash
                blocks: Number of blocks to wait (used as max for chainsim,
                        multiplied by 6s for live networks)
            """
            if self.env.supports_time_control():
                from tests.environments import ChainsimEnvironment
                if isinstance(self.env, ChainsimEnvironment):
                    max_blocks = max(blocks, 30)
                    logger.debug(f"Generating blocks until tx {tx_hash} processed (max {max_blocks})")
                    self.env.generate_blocks_until_tx_processed(tx_hash, max_blocks)
                else:
                    logger.debug(f"Advancing {blocks} block(s) for tx {tx_hash}")
                    self.env.advance_blocks(blocks)
            else:
                wait_time = blocks * 6  # ~6 seconds per block
                logger.debug(f"Waiting {wait_time}s for tx {tx_hash}")
                time.sleep(wait_time)

        def wait_blocks(self, count: int):
            """
            Wait for N blocks to pass.

            Args:
                count: Number of blocks to wait
            """
            if self.env.supports_time_control():
                logger.debug(f"Advancing {count} block(s)")
                self.env.advance_blocks(count)
            else:
                wait_time = count * 6
                logger.debug(f"Waiting {wait_time}s for {count} block(s)")
                time.sleep(wait_time)

        def advance_to_epoch(self, epoch: int):
            """
            Advance to specific epoch (chainsim only).

            Args:
                epoch: Target epoch number

            Raises:
                NotImplementedError: If environment doesn't support epoch control
            """
            if not self.env.supports_time_control():
                raise NotImplementedError(
                    f"Epoch control not supported on {self.env.__class__.__name__}"
                )
            logger.info(f"Advancing to epoch {epoch}")
            self.env.advance_to_epoch(epoch)

        def get_current_epoch(self) -> int:
            """Get current blockchain epoch"""
            return self.env.get_current_epoch()

        def get_current_block(self) -> int:
            """Get current blockchain block"""
            return self.env.get_current_block()

    return BlockchainController(test_environment)


# ============================================================================
# DEX INFRASTRUCTURE FIXTURES (Session Scope)
# ============================================================================

@pytest.fixture(scope="session")
def dex_context(test_environment, network_proxy, request) -> Context:
    """
    Load or deploy DEX infrastructure.

    Behavior:
    - If environment has pre-existing state (devnet/shadowfork):
      Load deployed contracts from deployed_*.json files

    - If environment is clean slate (chainsim without state):
      Deploy full DEX infrastructure (tokens + contracts)

    - If --skip-deploy flag provided:
      Only load existing contracts, fail if not found

    Returns:
        Context: Initialized DEX context with deployed contracts

    Raises:
        RuntimeError: If contracts not found when required
    """
    skip_deploy = request.config.getoption("--skip-deploy")

    logger.info("Initializing DEX context...")
    context = Context()

    # Determine if we need to deploy
    needs_deployment = (
        not test_environment.has_pre_existing_state() and
        not skip_deploy
    )

    if needs_deployment:
        logger.info("Deploying DEX infrastructure (clean slate)...")

        # Sync deployer nonce
        context.deployer_account.sync_nonce(network_proxy)

        # Deploy tokens
        logger.info("Deploying tokens...")
        context.deploy_structure.deploy_tokens(
            context.deployer_account,
            context.network_provider,
            True
        )

        # Wait for token issuance
        if test_environment.supports_time_control():
            test_environment.advance_blocks(2)
        else:
            time.sleep(12)

        # Deploy contracts
        logger.info("Deploying contracts...")
        context.deploy_structure.deploy_structure(
            context.deployer_account,
            context.network_provider,
            True
        )

        # Wait for deployment
        if test_environment.supports_time_control():
            test_environment.advance_blocks(2)
        else:
            time.sleep(12)

        # Start/initialize contracts
        logger.info("Starting contracts...")
        context.deploy_structure.start_deployed_contracts(
            context.deployer_account,
            context.network_provider,
            True
        )

        # Wait for initialization
        if test_environment.supports_time_control():
            test_environment.advance_blocks(2)
        else:
            time.sleep(12)

        logger.info("DEX infrastructure deployment complete")

    else:
        logger.info("Using pre-deployed DEX infrastructure")

    # Verify we have contracts
    context.deploy_structure.print_deployed_contracts()

    # Ensure pair template has bytecode (needed for Router.createPair on chain simulator)
    if test_environment.supports_time_control() and test_environment.has_pre_existing_state():
        _ensure_pair_template_loaded(context, test_environment)
        _ensure_farm_state_loaded(context, test_environment)
        _ensure_staking_state_loaded(context, test_environment)

    return context


def _ensure_pair_template_loaded(context: Context, env):
    """Ensure the Router's pair template contract has bytecode loaded on chain simulator.

    When mainnet state is loaded, the Router references a pair template address for
    deployFromSourceContract, but the template's own bytecode may not be in the state dump.
    This copies bytecode from an existing pair contract to the template address.
    """
    routers = context.get_contracts(config.ROUTER_V2)
    pairs = context.get_contracts(config.PAIRS_V2)
    if routers and pairs and hasattr(env, 'chain_sim') and env.chain_sim:
        env.chain_sim.ensure_pair_template_has_code(routers[0].address, pairs[0].address)


def _ensure_farm_state_loaded(context: Context, env):
    """Ensure farm contract state is loaded on chain simulator.

    Farm contracts are not included in the default state dump. This fetches
    their full state (bytecode + storage) from mainnet and loads it onto the
    chain simulator via set-state API.
    """
    from tests.environments import ChainsimEnvironment
    if not isinstance(env, ChainsimEnvironment) or not env.chain_sim:
        return

    farms = context.get_contracts(config.FARMS_LOCKED)
    if not farms:
        logger.debug("No farms_locked contracts configured, skipping farm state loading")
        return

    for farm in farms:
        try:
            env.chain_sim.ensure_contract_state_from_mainnet(
                farm.address,
                filter_boosted_yields_weeks=True,
            )
        except Exception as e:
            logger.warning(f"Could not load farm state for {farm.address}: {e}")


def _ensure_staking_state_loaded(context: Context, env):
    """Ensure staking contract state is loaded on chain simulator.

    Staking contracts are not included in the default state dump. This fetches
    their full state (bytecode + storage) from mainnet and loads it onto the
    chain simulator via set-state API.

    Filters:
    - filter_first_week_epoch=True: Override firstWeekStartEpoch to 0
    - filter_boosted_yields_weeks=True: Remove week-dependent keys (CRITICAL for both V2 and V3Boosted)

    Note: Even V2 staking contracts need boosted yields week filtering because
    they store week-related state that's incompatible with chain sim epochs.
    """
    from tests.environments import ChainsimEnvironment
    if not isinstance(env, ChainsimEnvironment) or not env.chain_sim:
        return

    # Try V2 staking contracts first
    stakings = context.get_contracts(config.STAKINGS_V2)
    if not stakings:
        # Try V3Boosted staking contracts
        stakings = context.get_contracts(config.STAKINGS_BOOSTED)

    if not stakings:
        logger.debug("No staking contracts configured, skipping staking state loading")
        return

    for staking in stakings:
        try:
            env.chain_sim.ensure_contract_state_from_mainnet(
                staking.address,
                filter_first_week_epoch=True,       # Override week start for chain sim
                filter_boosted_yields_weeks=True,   # CRITICAL: Remove week keys for both V2 and V3
            )
        except Exception as e:
            logger.warning(f"Could not load staking state for {staking.address}: {e}")


# ============================================================================
# CONTRACT FIXTURES (Function Scope)
# ============================================================================

@pytest.fixture
def pair_contract(dex_context) -> PairContract:
    """
    Get a Pair contract for testing.

    Returns:
        PairContract: First deployed Pair contract

    Raises:
        pytest.skip: If no pairs deployed
    """
    pairs = dex_context.get_contracts(config.PAIRS_V2)
    if not pairs:
        pytest.skip("No Pair contracts deployed")
    return pairs[1]


@pytest.fixture
def all_pair_contracts(dex_context) -> List[PairContract]:
    """
    Get all deployed Pair contracts.

    Returns:
        List[PairContract]: All deployed Pair contracts

    Raises:
        pytest.skip: If no pairs deployed
    """
    pairs = dex_context.get_contracts(config.PAIRS_V2)
    if not pairs:
        pytest.skip("No Pair contracts deployed")
    return pairs


@pytest.fixture
def farm_contract(dex_context) -> FarmContract:
    """
    Get a Farm contract for testing.

    Returns:
        FarmContract: First deployed Farm contract

    Raises:
        pytest.skip: If no farms deployed
    """
    farms = dex_context.get_contracts(config.FARMS_LOCKED)
    if not farms:
        pytest.skip("No Farm contracts deployed")
    return farms[0]


@pytest.fixture
def staking_contract(dex_context):
    """
    Get a Staking contract for testing.

    Returns:
        StakingContract: First deployed Staking contract (V2 or V3Boosted)

    Raises:
        pytest.skip: If no staking contracts deployed
    """
    # Try V2 staking contracts first
    stakings = dex_context.get_contracts(config.STAKINGS_V2)
    if not stakings:
        # Try V3Boosted staking contracts
        stakings = dex_context.get_contracts(config.STAKINGS_BOOSTED)
    if not stakings:
        pytest.skip("No Staking contracts deployed")
    return stakings[0]


@pytest.fixture
def all_staking_contracts(dex_context):
    """
    Get all deployed Staking contracts.

    Returns:
        List[StakingContract]: All deployed Staking contracts (V2 or V3Boosted)

    Raises:
        pytest.skip: If no staking contracts deployed
    """
    # Try V2 staking contracts first
    stakings = dex_context.get_contracts(config.STAKINGS_V2)
    if not stakings:
        # Try V3Boosted staking contracts
        stakings = dex_context.get_contracts(config.STAKINGS_BOOSTED)
    if not stakings:
        pytest.skip("No Staking contracts deployed")
    return stakings


@pytest.fixture
def router_contract(dex_context) -> RouterContract:
    """
    Get Router contract for testing.

    Returns:
        RouterContract: Deployed Router contract

    Raises:
        pytest.skip: If no router deployed
    """
    routers = dex_context.get_contracts(config.ROUTER_V2)
    if not routers:
        pytest.skip("No Router contract deployed")
    return routers[0]


# ============================================================================
# ACCOUNT FIXTURES (Session and Function Scope)
# ============================================================================

@pytest.fixture(scope="session")
def deployer_account(dex_context, test_environment) -> Account:
    """
    Get deployer account (contract owner).

    For shadowfork: Address is automatically impersonated to contract owner
    For chainsim/devnet: Uses configured PEM file

    Returns:
        Account: Deployer account with admin permissions
    """
    account = dex_context.deployer_account

    # For shadowfork, override address with DEX owner (impersonation)
    if isinstance(test_environment, ShadowforkEnvironment):
        owner_addr = test_environment.get_dex_owner_address()
        if owner_addr:
            logger.info(f"Impersonating DEX owner: {owner_addr}")
            account.address = Address(owner_addr)

    return account


def _ensure_account_has_egld(account: Account, test_environment: TestEnvironment, proxy: ProxyNetworkProvider, min_egld: Optional[int] = None) -> None:
    """
    Helper: Ensure account has EGLD for gas fees.

    For chainsim: Funds account if balance is below minimum
    For devnet/shadowfork: Skips (assumes accounts pre-funded)

    Args:
        account: Account to check/fund
        test_environment: Test environment instance
        proxy: Network proxy for balance check
        min_egld: Minimum EGLD required (default: 1 EGLD)
    """
    if min_egld is None:
        min_egld = nominated_amount(1)  # 1 EGLD default

    # Only fund on chainsim (clean slate)
    if not test_environment.supports_time_control():
        return

    # Ensure account has address
    if not account.address:
        logger.warning("Account has no address, cannot check/fund EGLD")
        return

    # Check current balance
    account_data = proxy.get_account(account.address)
    current_balance = account_data.balance

    if current_balance >= min_egld:
        logger.debug(f"Account {account.address.to_bech32()} has sufficient EGLD: {current_balance / 10**18:.4f}")
        return

    # Fund account via chain simulator
    logger.info(f"Funding account {account.address.to_bech32()} with {min_egld / 10**18} EGLD")

    # Access chain simulator from environment
    from tests.environments import ChainsimEnvironment
    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        test_environment.chain_sim.fund_users_w_egld([account.address.to_bech32()], min_egld)
        logger.info(f"Account funded successfully")
    else:
        logger.warning("Cannot fund account: environment doesn't support funding")


@pytest.fixture(scope="session")
def test_accounts(dex_context, test_environment, network_proxy) -> List[Account]:
    """
    Get funded test user accounts.

    For clean slate (chainsim): Mints tokens for test accounts
    For pre-existing state: Uses existing accounts from config

    Returns:
        List[Account]: Up to 5 funded test accounts
    """
    accounts = dex_context.accounts.get_all()

    # If clean slate, fund accounts with tokens
    if not test_environment.has_pre_existing_state():
        logger.info("Funding test accounts with tokens...")

        deployer = dex_context.deployer_account
        tokens = dex_context.deploy_structure.tokens[:2]  # First 2 tokens

        for acc in accounts[:5]:  # Fund first 5 accounts
            acc.sync_nonce(network_proxy)

            # Mint tokens via minter account
            for token in tokens:
                # TODO: Implement token minting logic
                # This would use builtin ESDT contract to mint tokens
                pass

        # Wait for minting transactions
        if test_environment.supports_time_control():
            test_environment.advance_blocks(2)
        else:
            time.sleep(12)

        logger.info("Test accounts funded")

    return accounts[:5]


@pytest.fixture
def alice(test_accounts, test_environment, network_providers) -> Account:
    """
    First test user (Alice).

    Nonce is synced before each test for isolation.
    For chainsim: Ensures account has at least 1 EGLD for gas.

    Returns:
        Account: Alice's account
    """
    alice = test_accounts[0]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(alice, test_environment, network_providers.proxy)

    alice.sync_nonce(network_providers.proxy)
    return alice


@pytest.fixture
def bob(test_accounts, test_environment, network_providers) -> Account:
    """
    Second test user (Bob).

    Nonce is synced before each test for isolation.
    For chainsim: Ensures account has at least 1 EGLD for gas.

    Returns:
        Account: Bob's account
    """
    bob = test_accounts[1]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(bob, test_environment, network_providers.proxy)

    bob.sync_nonce(network_providers.proxy)
    return bob


@pytest.fixture
def charlie(test_accounts, test_environment, network_providers) -> Account:
    """
    Third test user (Charlie).

    Nonce is synced before each test for isolation.
    For chainsim: Ensures account has at least 1 EGLD for gas.

    Returns:
        Account: Charlie's account
    """
    charlie = test_accounts[2]

    # Ensure account has EGLD for gas (chainsim only)
    _ensure_account_has_egld(charlie, test_environment, network_providers.proxy)

    charlie.sync_nonce(network_providers.proxy)
    return charlie


def _ensure_account_has_esdt_amounts(
    account: Account,
    token_amounts: dict,
    test_environment: TestEnvironment,
    proxy: ProxyNetworkProvider
) -> None:
    """
    Helper: Ensure account has specific ESDT token amounts.

    Checks account balances and funds with the exact amounts needed.
    Only works on chainsim environment.

    Args:
        account: Account to check/fund
        token_amounts: Dict mapping token_id -> required_amount
        test_environment: Test environment instance
        proxy: Network proxy for balance check
    """
    # Only fund on chainsim
    if not test_environment.supports_time_control():
        return

    # Ensure account has address
    if not account.address:
        logger.warning("Account has no address, cannot check/fund ESDT")
        return

    # Get current token balances from chain
    account_tokens = proxy.get_fungible_tokens_of_account(account.address)

    # Create a mapping of token_id -> balance for quick lookup
    token_balances = {tokenOnNetwork.token.identifier: tokenOnNetwork.amount for tokenOnNetwork in account_tokens}

    # Check and fund each token if needed
    if not isinstance(test_environment, ChainsimEnvironment) or not test_environment.chain_sim:
        logger.warning("Cannot fund ESDT: environment doesn't support funding")
        return

    tokens_to_fund = {}

    # Check each required token
    for token_id, required_amount in token_amounts.items():
        current_balance = token_balances.get(token_id, 0)
        if current_balance < required_amount:
            amount_needed = required_amount - current_balance
            logger.info(
                f"Account needs {token_id}: "
                f"current={current_balance / 10**18:.4f}, "
                f"required={required_amount / 10**18:.4f}, "
                f"will fund={amount_needed / 10**18:.4f}"
            )
            tokens_to_fund[token_id] = required_amount
        else:
            logger.debug(f"Account has sufficient {token_id}: {current_balance / 10**18:.4f}")

    # Fund tokens if needed
    if tokens_to_fund:
        logger.info(f"Funding account {account.address.to_bech32()} with {len(tokens_to_fund)} token(s)")
        for token_id, amount in tokens_to_fund.items():
            test_environment.chain_sim.fund_users_w_esdt_from_mainnet(
                [account.address.to_bech32()],
                token_id,
                amount
            )
        logger.info(f"Account funded with {len(tokens_to_fund)} token(s)")
    else:
        logger.debug("Account has sufficient token balances")


@pytest.fixture
def ensure_esdt_amounts(test_environment, network_providers):
    """
    Helper fixture to ensure account has specific ESDT token amounts.

    Returns a callable that tests can use to fund accounts with exact token amounts.

    Usage:
        def test_add_liquidity(alice, pair_contract, ensure_esdt_amounts):
            # Fund Alice with exact amounts needed for the transaction
            ensure_esdt_amounts(alice, {
                "WEGLD-bd4d79": nominated_amount(1000),
                "MEX-455c57": nominated_amount(500)
            })

            # Now perform operations with those exact amounts
            pair_contract.add_liquidity(...)

    Args (when called):
        account: Account to check/fund
        token_amounts: Dict mapping token_id -> required_amount
    """
    def _ensure(account: Account, token_amounts: dict):
        _ensure_account_has_esdt_amounts(
            account,
            token_amounts,
            test_environment,
            network_providers.proxy
        )

    return _ensure


# ============================================================================
# PYTEST HOOKS
# ============================================================================

def pytest_configure(config):
    """
    Register custom markers.

    This allows using markers like @pytest.mark.integration without warnings.
    """
    config.addinivalue_line("markers", "integration: Integration tests (requires blockchain)")
    config.addinivalue_line("markers", "security: Security-focused adversarial tests")
    config.addinivalue_line("markers", "slow: Tests that take >30 seconds")
    config.addinivalue_line("markers", "chainsim: Requires chain simulator")
    config.addinivalue_line("markers", "devnet: Requires devnet connection")
    config.addinivalue_line("markers", "shadowfork: Requires shadowfork environment")
    config.addinivalue_line("markers", "skip_on_live: Skip on real networks (destructive tests)")


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip tests based on environment capabilities.

    - Skip @pytest.mark.chainsim tests when not on chainsim
    - Skip @pytest.mark.skip_on_live tests when on devnet/shadowfork
    """
    env_name = config.getoption("--env")

    for item in items:
        # Skip chainsim-only tests on other environments
        if "chainsim" in item.keywords and env_name != "chainsim":
            item.add_marker(pytest.mark.skip(reason="Requires chain simulator"))

        # Skip destructive tests on live networks
        if "skip_on_live" in item.keywords and env_name in ["devnet", "shadowfork"]:
            item.add_marker(pytest.mark.skip(reason="Destructive test, skip on live networks"))


# ============================================================================
# ISOLATED PAIR FIXTURE (Function Scope)
# ============================================================================

@pytest.fixture
def isolated_pair_factory(
    router_contract,
    network_providers,
    blockchain_controller,
    test_environment
):
    """
    Factory fixture that creates fresh, isolated pair contracts for tests
    that need to perform operations like full liquidity removal.

    Returns a callable that creates a new pair with fresh tokens.

    Usage:
        def test_full_removal(isolated_pair_factory, alice):
            pair, first_token, second_token = isolated_pair_factory(alice)
            # Now use pair for testing full removal scenarios

    Args (when called):
        owner: Account that will own the pair and tokens
        liquidity_amount: Optional initial token supply (default: 1000 * 10^18)

    Returns:
        Tuple[PairContract, str, str]: (pair_contract, first_token_id, second_token_id)
    """
    from contracts.builtin_contracts import ESDTContract
    from contracts.pair_contract import PairContract, PairContractVersion
    from multiversx_sdk import find_events_by_identifier, Address as SdkAddress
    from utils.utils_chain import hex_to_string
    from utils.contract_data_fetchers import PairContractDataFetcher

    # Track created pairs for potential cleanup
    created_pairs = []

    def _create_isolated_pair(owner: Account, liquidity_amount: int = None):
        """
        Create a fresh pair with newly issued tokens.

        Args:
            owner: Account to own the pair and tokens
            liquidity_amount: Token supply to issue (default: 1000 * 10^18)

        Returns:
            Tuple of (PairContract, first_token_id, second_token_id)
        """
        if liquidity_amount is None:
            liquidity_amount = nominated_amount(1000)

        # Ensure owner has EGLD for fees (token issuance costs ~0.05 EGLD each)
        if test_environment.supports_time_control():
            from tests.environments import ChainsimEnvironment
            if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim and owner.address:
                required_egld = nominated_amount(3)  # 3 EGLD for safety
                test_environment.chain_sim.fund_users_w_egld([owner.address.to_bech32()], required_egld)

        esdt_contract = ESDTContract(config.TOKENS_CONTRACT_ADDRESS)

        # Issue first token
        owner.sync_nonce(network_providers.proxy)
        logger.info("Issuing first test token for isolated pair")
        tx_hash_1 = esdt_contract.issue_fungible_token(
            owner,
            network_providers.proxy,
            ["IsoTestA", "ISOA", liquidity_amount, 18]
        )
        blockchain_controller.wait_for_tx(tx_hash_1, blocks=8)

        tx_data_1 = network_providers.proxy.get_transaction(tx_hash_1)
        issue_events_1 = find_events_by_identifier(tx_data_1, "issue")
        assert issue_events_1, f"No 'issue' events found for token issuance tx {tx_hash_1}. Status: {tx_data_1.status}"
        issue_event_1 = issue_events_1[0]
        first_token = issue_event_1.topics[0].decode('utf-8') if isinstance(issue_event_1.topics[0], bytes) else str(issue_event_1.topics[0])
        logger.info(f"First token issued: {first_token}")

        # Issue second token
        owner.sync_nonce(network_providers.proxy)
        logger.info("Issuing second test token for isolated pair")
        tx_hash_2 = esdt_contract.issue_fungible_token(
            owner,
            network_providers.proxy,
            ["IsoTestB", "ISOB", liquidity_amount, 18]
        )
        blockchain_controller.wait_for_tx(tx_hash_2, blocks=8)

        tx_data_2 = network_providers.proxy.get_transaction(tx_hash_2)
        issue_events_2 = find_events_by_identifier(tx_data_2, "issue")
        assert issue_events_2, f"No 'issue' events found for token issuance tx {tx_hash_2}. Status: {tx_data_2.status}"
        issue_event_2 = issue_events_2[0]
        second_token = issue_event_2.topics[0].decode('utf-8') if isinstance(issue_event_2.topics[0], bytes) else str(issue_event_2.topics[0])
        logger.info(f"Second token issued: {second_token}")

        # Deploy new pair via router
        owner.sync_nonce(network_providers.proxy)
        deploy_args = [
            first_token,
            second_token,
            owner.address.to_bech32() if owner.address else "",
            300,  # 3% total fee
            0     # 0% special fee
        ]

        logger.info(f"Deploying isolated pair: {first_token} / {second_token}")
        tx_hash, pair_address = router_contract.pair_contract_deploy(owner, network_providers.proxy, deploy_args)

        if not pair_address:
            raise RuntimeError(f"Failed to deploy pair. Transaction: {tx_hash}")

        blockchain_controller.wait_for_tx(tx_hash, blocks=8)
        logger.info(f"Isolated pair deployed at: {pair_address}")

        # Issue LP token
        lp_token_name = f"{first_token[:4]}{second_token[:4]}LP"
        lp_token_ticker = f"{first_token[:4]}{second_token[:4]}"

        owner.sync_nonce(network_providers.proxy)
        tx_hash = router_contract.issue_lp_token(owner, network_providers.proxy, [pair_address, lp_token_name, lp_token_ticker])
        blockchain_controller.wait_for_tx(tx_hash, blocks=8)

        # Get LP token identifier
        pair_data_fetcher = PairContractDataFetcher(SdkAddress.new_from_bech32(pair_address), network_providers.proxy.url)
        lp_token_hex = pair_data_fetcher.get_data("getLpTokenIdentifier")
        lp_token = hex_to_string(lp_token_hex)
        logger.info(f"LP token issued: {lp_token}")

        # Set LP token local roles
        owner.sync_nonce(network_providers.proxy)
        tx_hash = router_contract.set_lp_token_local_roles(owner, network_providers.proxy, pair_address)
        blockchain_controller.wait_for_tx(tx_hash, blocks=8)

        # Create PairContract instance
        pair = PairContract(first_token, second_token, PairContractVersion.V2, lpToken=lp_token, address=pair_address)
        created_pairs.append(pair)

        logger.info(f"Isolated pair ready: {pair_address}")
        return pair, first_token, second_token

    return _create_isolated_pair
