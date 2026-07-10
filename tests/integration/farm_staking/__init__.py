"""
Farm Staking Integration Test Helpers

This module provides helper functions for testing farm staking smart contracts.
Follows patterns established in tests/integration/farm/ and tests/integration/pair/.

Usage:
    from tests.integration.farm_staking import (
        _get_staking_state,
        _check_staking_has_code,
        _get_stake_amount,
        _stake_farm,
        _unstake_farm,
        _unbond_farm,
        _claim_rewards,
        _compound_rewards,
        _get_farm_tokens_for_user,
    )
"""

import requests
from multiversx_sdk import Address
from multiversx_sdk.network_providers.resources import TokenAmountOnNetwork
from contracts.staking_contract import StakingContract
from utils.utils_chain import hex_to_string, nominated_amount
from utils.contract_data_fetchers import StakingContractDataFetcher
from utils.logger import get_logger
from tests.helpers import TransactionAssertions

logger = get_logger(__name__)


if not hasattr(TokenAmountOnNetwork, "identifier"):
    TokenAmountOnNetwork.identifier = property(lambda self: self.token.identifier)

if not hasattr(TokenAmountOnNetwork, "balance"):
    TokenAmountOnNetwork.balance = property(lambda self: self.amount)


def _get_staking_state(staking_contract: StakingContract, proxy):
    """Get current staking contract state via view functions.

    Args:
        staking_contract: StakingContract instance
        proxy: ProxyNetworkProvider instance

    Returns:
        Dict with keys:
            - farm_token_supply: Total staked amount (int)
            - reward_reserve: Remaining rewards available (int)
            - reward_per_share: Current RPS (int)
            - state: Contract state (0=paused, 1=active)
            - farming_token_id: Token being staked (str)
            - farm_token_id: Staking receipt token (str)
            - reward_capacity: Total reward capacity (int, staking-specific)
            - accumulated_rewards: Rewards distributed so far (int, staking-specific)
            - max_apr: APR cap in basis points (int, staking-specific)
            - min_unbond_epochs: Unbonding period (int, staking-specific)
    """
    fetcher = StakingContractDataFetcher(
        Address.new_from_bech32(staking_contract.address),
        proxy.url
    )

    return {
        "farm_token_supply": int(fetcher.get_data("getFarmTokenSupply") or 0),
        "reward_reserve": int(fetcher.get_data("getRewardReserve") or 0),
        "reward_per_share": int(fetcher.get_data("getRewardPerShare") or 0),
        "state": int(fetcher.get_data("getState") or 0),
        "farming_token_id": hex_to_string(fetcher.get_data("getFarmingTokenId") or ""),
        "farm_token_id": hex_to_string(fetcher.get_data("getFarmTokenId") or ""),
        # Staking-specific view functions
        "reward_capacity": int(fetcher.get_data("getRewardCapacity") or 0),
        "accumulated_rewards": int(fetcher.get_data("getAccumulatedRewards") or 0),
        "max_apr": int(fetcher.get_data("getAnnualPercentageRewards") or 0),
        "min_unbond_epochs": int(fetcher.get_data("getMinUnbondEpochs") or 0),
    }


def _check_staking_has_code(staking_contract: StakingContract, proxy):
    """Check if staking contract has bytecode loaded on chain simulator.

    Args:
        staking_contract: StakingContract instance
        proxy: ProxyNetworkProvider instance

    Returns:
        bool: True if contract has code, False otherwise
    """
    resp = requests.get(f"{proxy.url}/address/{staking_contract.address}")
    if resp.status_code != 200:
        return False
    acct = resp.json()["data"]["account"]
    return bool(acct.get("code"))


def _get_stake_amount(staking_contract: StakingContract, proxy):
    """Calculate a reserve-relative stake amount for testing.

    Uses 0.1% of current farm token supply or a minimum of 1 token.
    This ensures tests work with pre-existing mainnet state where
    supply varies across test runs.

    Args:
        staking_contract: StakingContract instance
        proxy: ProxyNetworkProvider instance

    Returns:
        int: Stake amount in denominated units
    """
    staking_state = _get_staking_state(staking_contract, proxy)
    supply = staking_state["farm_token_supply"]

    if supply > 0:
        # 0.1% of supply or 1 token minimum
        return max(supply // 1000, nominated_amount(1))

    # No pre-existing supply, use default amount
    return nominated_amount(100)


def _stake_farm(staking_contract, user, farming_token, stake_amount, network_providers,
                blockchain_controller, farm_nonce=0, farm_amount=0):
    """Execute stakeFarm and return tx_hash.

    Does NOT assert success — the test decides whether to use
    assert_transaction_success() or assert_transaction_failed().

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        farming_token: Farming token identifier (e.g., "RIDE-7d18e9")
        stake_amount: Amount to stake in denominated units
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController instance
        farm_nonce: Existing farm token nonce (0 for initial stake)
        farm_amount: Existing farm token amount (0 for initial stake)

    Returns:
        str: Transaction hash
    """
    from events.farm_events import EnterFarmEvent

    user.sync_nonce(network_providers.proxy)

    enter_event = EnterFarmEvent(
        farming_token=farming_token,
        farming_nonce=0,
        farming_amount=stake_amount,
        farm_token=staking_contract.farm_token,
        farm_nonce=farm_nonce,
        farm_amount=farm_amount,
    )

    initial = (farm_nonce == 0 and farm_amount == 0)
    tx_hash = staking_contract.stake_farm(network_providers, user, enter_event, initial=initial)
    blockchain_controller.wait_for_tx(tx_hash)

    return tx_hash


def _unstake_farm(staking_contract, user, farm_token_nonce, farm_token_amount,
                  network_providers, blockchain_controller):
    """Execute unstakeFarm and return tx_hash.

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        farm_token_nonce: Farm token nonce to unstake
        farm_token_amount: Farm token amount to unstake
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController instance

    Returns:
        str: Transaction hash
    """
    from events.farm_events import ExitFarmEvent

    user.sync_nonce(network_providers.proxy)

    exit_event = ExitFarmEvent(
        farm_token=staking_contract.farm_token,
        amount=farm_token_amount,
        nonce=farm_token_nonce,
        attributes="",
    )

    tx_hash = staking_contract.unstake_farm(network_providers, user, exit_event)
    blockchain_controller.wait_for_tx(tx_hash)

    return tx_hash


def _unbond_farm(staking_contract, user, unbond_token_nonce, unbond_token_amount,
                 network_providers, blockchain_controller):
    """Execute unbondFarm and return tx_hash.

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        unbond_token_nonce: Unbond token nonce
        unbond_token_amount: Unbond token amount
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController instance

    Returns:
        str: Transaction hash
    """
    from events.farm_events import ExitFarmEvent

    user.sync_nonce(network_providers.proxy)

    # Unbond uses ExitFarmEvent with farm_token = staking contract's farm token
    # The nonce is the unbond token nonce (not the farm token nonce)
    exit_event = ExitFarmEvent(
        farm_token=staking_contract.farm_token,
        amount=unbond_token_amount,
        nonce=unbond_token_nonce,
        attributes="",
    )

    tx_hash = staking_contract.unbond_farm(network_providers, user, exit_event)
    blockchain_controller.wait_for_tx(tx_hash)

    return tx_hash


def _claim_rewards(staking_contract, user, farm_token_nonce, farm_token_amount,
                   network_providers, blockchain_controller):
    """Execute claimRewards and return tx_hash.

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        farm_token_nonce: Farm token nonce
        farm_token_amount: Farm token amount
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController instance

    Returns:
        str: Transaction hash
    """
    from events.farm_events import ClaimRewardsFarmEvent

    user.sync_nonce(network_providers.proxy)

    claim_event = ClaimRewardsFarmEvent(
        amount=farm_token_amount,
        nonce=farm_token_nonce,
        attributes="",
    )

    tx_hash = staking_contract.claim_rewards(network_providers, user, claim_event)
    blockchain_controller.wait_for_tx(tx_hash)

    return tx_hash


def _compound_rewards(staking_contract, user, farm_token_nonce, farm_token_amount,
                      network_providers, blockchain_controller):
    """Execute compoundRewards and return tx_hash.

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        farm_token_nonce: Farm token nonce
        farm_token_amount: Farm token amount
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController instance

    Returns:
        str: Transaction hash
    """
    from events.farm_events import CompoundRewardsFarmEvent

    user.sync_nonce(network_providers.proxy)

    compound_event = CompoundRewardsFarmEvent(
        nonce=farm_token_nonce,
        amount=farm_token_amount,
    )

    tx_hash = staking_contract.compound_rewards(network_providers, user, compound_event)
    blockchain_controller.wait_for_tx(tx_hash)

    return tx_hash


def _get_farm_tokens_for_user(staking_contract, user, proxy):
    """Get active farm position NFTs held by user.

    Args:
        staking_contract: StakingContract instance
        user: Account instance
        proxy: ProxyNetworkProvider instance

    Returns:
        List of AccountNFT objects that decode as active farm positions
    """
    all_nfts = proxy.get_non_fungible_tokens_of_account(user.address)
    farm_token_id = staking_contract.farm_token  # e.g. "SRIDE-4ab1d4"
    farm_tokens = []
    for token in all_nfts:
        # token.token.identifier includes nonce hex (e.g. "SRIDE-4ab1d4-01")
        # Extract collection (base ID) by stripping the nonce suffix
        collection = token.token.identifier.rsplit('-', 1)[0]
        if collection != farm_token_id:
            continue
        # Unbond tokens share the same collection but have exactly 8 bytes
        # attributes (a single u64 unlock_epoch). Active farm tokens have
        # longer attributes (reward_per_share + compounded_reward + other fields).
        if len(token.attributes) == 8:
            continue
        farm_tokens.append(token)
    return farm_tokens


def _get_unbond_tokens_for_user(staking_contract, user, proxy):
    """Get unbond NFTs held by user."""
    all_nfts = proxy.get_non_fungible_tokens_of_account(user.address)
    farm_token_id = staking_contract.farm_token
    unbond_tokens = []
    for token in all_nfts:
        collection = token.token.identifier.rsplit('-', 1)[0]
        if collection != farm_token_id:
            continue
        # Unbond tokens have exactly 8 bytes attributes (u64 unlock_epoch).
        if len(token.attributes) == 8:
            unbond_tokens.append(token)
    return unbond_tokens


def _ensure_rewards_available(staking_contract, deployer_account, test_environment,
                               network_providers, blockchain_controller, ensure_esdt_amounts):
    """Ensure staking contract has sufficient reward capacity, topping up if exhausted.

    The mainnet state loaded on chain simulator may have fully depleted reward capacity
    (capacity == accumulated). This helper detects that and calls topUpRewards so that
    reward-dependent tests (claim, compound, unstake) produce non-zero results.

    Args:
        staking_contract: StakingContract instance
        deployer_account: Account with admin rights on the contract
        test_environment: Test environment (used to detect chain sim)
        network_providers: NetworkProviders instance
        blockchain_controller: BlockchainController for tx finalization
        ensure_esdt_amounts: ensure_esdt_amounts fixture callable
    """
    if not _check_staking_has_code(staking_contract, network_providers.proxy):
        return

    rewards_capacity = staking_contract.get_reward_capacity(network_providers.proxy)
    accumulated_rewards = staking_contract.get_accumulated_rewards(network_providers.proxy)
    remained_rewards = rewards_capacity - accumulated_rewards

    min_reserve = nominated_amount(100_000)  # 100k tokens
    if remained_rewards >= min_reserve:
        return

    top_up_amount = nominated_amount(100_000)  # 100k tokens
    farming_token = staking_contract.farming_token

    logger.info(
        f"Reward reserve depleted (reserve={remained_rewards}), "
        f"topping up staking contract with {top_up_amount} {farming_token}"
    )

    _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)
    ensure_esdt_amounts(deployer_account, {farming_token: top_up_amount})

    deployer_account.sync_nonce(network_providers.proxy)
    tx_hash = staking_contract.topup_rewards(deployer_account, network_providers.proxy, top_up_amount)
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

    logger.info("✓ Staking contract reward capacity topped up")


def _ensure_deployer_has_egld(deployer_account, test_environment, network_providers, min_egld=None):
    """Ensure deployer account has EGLD for gas fees on chain simulator.

    deployer_account fixture does NOT auto-fund on chain sim. This helper
    must be called explicitly before admin operations (pause, resume, topup, etc.).

    Args:
        deployer_account: Account instance
        test_environment: Test environment instance
        network_providers: NetworkProviders instance
        min_egld: Minimum EGLD balance (default: 10 EGLD)
    """
    from tests.environments import ChainsimEnvironment

    if min_egld is None:
        min_egld = nominated_amount(10)

    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        account_data = network_providers.proxy.get_account(deployer_account.address)
        if account_data.balance < min_egld:
            logger.info(f"Funding deployer with {min_egld} EGLD for gas")
            test_environment.chain_sim.fund_users_w_egld(
                [deployer_account.address.to_bech32()],
                min_egld
            )
