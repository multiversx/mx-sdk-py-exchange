"""
Farm integration test helpers shared across the locked-rewards suite.
"""

import requests
from multiversx_sdk import Address

from contracts.farm_contract import FarmContract
from events.farm_events import (
    ClaimRewardsFarmEvent,
    EnterFarmEvent,
    ExitFarmEvent,
    MergePositionFarmEvent,
)
from tests.environments import ChainsimEnvironment
from utils.contract_data_fetchers import (
    FarmContractDataFetcher,
    SimpleLockEnergyContractDataFetcher,
)
from utils.logger import get_logger
from utils.utils_chain import hex_to_string, nominated_amount

logger = get_logger(__name__)


def _get_farm_state(farm_contract: FarmContract, proxy):
    """Get current farm state via view functions."""
    fetcher = FarmContractDataFetcher(Address.new_from_bech32(farm_contract.address), proxy.url)
    return {
        "farm_token_supply": int(fetcher.get_data("getFarmTokenSupply") or 0),
        "last_reward_block_nonce": int(fetcher.get_data("getLastRewardBlockNonce") or 0),
        "per_block_reward_amount": int(fetcher.get_data("getPerBlockRewardAmount") or 0),
        "per_second_reward_amount": int(fetcher.get_data("getPerSecondRewardAmount") or 0),
        "reward_reserve": int(fetcher.get_data("getRewardReserve") or 0),
        "reward_per_share": int(fetcher.get_data("getRewardPerShare") or 0),
        "state": int(fetcher.get_data("getState") or 0),
        "farming_token_id": hex_to_string(fetcher.get_data("getFarmingTokenId") or ""),
        "farm_token_id": hex_to_string(fetcher.get_data("getFarmTokenId") or ""),
        "reward_token_id": hex_to_string(fetcher.get_data("getRewardTokenId") or ""),
        "division_safety_constant": int(fetcher.get_data("getDivisionSafetyConstant") or 0),
        "current_week": int(fetcher.get_data("getCurrentWeek") or 0),
        "first_week_start_epoch": int(fetcher.get_data("getFirstWeekStartEpoch") or 0),
    }


def _check_farm_has_code(farm_contract: FarmContract, proxy):
    """Check if farm contract has bytecode loaded on chain simulator."""
    resp = requests.get(f"{proxy.url}/address/{farm_contract.address}")
    if resp.status_code != 200:
        return False
    acct = resp.json()["data"]["account"]
    return bool(acct.get("code"))


def _get_stake_amount(farm_contract: FarmContract, proxy):
    """Calculate a reserve-relative stake amount for testing."""
    farm_state = _get_farm_state(farm_contract, proxy)
    supply = farm_state["farm_token_supply"]
    if supply > 0:
        return max(supply // 1000, nominated_amount(1))
    return nominated_amount(100)


def _enter_farm(
    farm_contract,
    user,
    farming_token,
    stake_amount,
    network_providers,
    blockchain_controller,
    farm_nonce=0,
    farm_amount=0,
):
    """Execute enterFarm and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    enter_event = EnterFarmEvent(
        farming_token=farming_token,
        farming_nonce=0,
        farming_amount=stake_amount,
        farm_token=farm_contract.farmToken,
        farm_nonce=farm_nonce,
        farm_amount=farm_amount,
    )
    tx_hash = farm_contract.enterFarm(network_providers, user, enter_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _exit_farm(farm_contract, user, farm_token_nonce, farm_token_amount, network_providers, blockchain_controller):
    """Execute exitFarm and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    exit_event = ExitFarmEvent(
        farm_token=farm_contract.farmToken,
        amount=farm_token_amount,
        nonce=farm_token_nonce,
        attributes="",
    )
    tx_hash = farm_contract.exitFarm(network_providers, user, exit_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _claim_rewards(farm_contract, user, farm_token_nonce, farm_token_amount, network_providers, blockchain_controller):
    """Execute claimRewards and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    claim_event = ClaimRewardsFarmEvent(
        amount=farm_token_amount,
        nonce=farm_token_nonce,
        attributes="",
    )
    tx_hash = farm_contract.claimRewards(network_providers, user, claim_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _claim_boosted_rewards(farm_contract, user, network_providers, blockchain_controller, for_user=None):
    """Execute claimBoostedRewards and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    claim_event = ClaimRewardsFarmEvent(
        amount=0,
        nonce=0,
        attributes="",
        user=for_user,
    )
    tx_hash = farm_contract.claim_boosted_rewards(network_providers, user, claim_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _enter_farm_on_behalf(
    farm_contract,
    user,
    farming_token,
    stake_amount,
    on_behalf,
    network_providers,
    blockchain_controller,
    farm_nonce=0,
    farm_amount=0,
):
    """Execute enterFarmOnBehalf and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    enter_event = EnterFarmEvent(
        farming_token=farming_token,
        farming_nonce=0,
        farming_amount=stake_amount,
        farm_token=farm_contract.farmToken,
        farm_nonce=farm_nonce,
        farm_amount=farm_amount,
        on_behalf=on_behalf,
    )
    tx_hash = farm_contract.enter_farm_on_behalf(network_providers, user, enter_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _claim_rewards_on_behalf(
    farm_contract,
    user,
    farm_token_nonce,
    farm_token_amount,
    network_providers,
    blockchain_controller,
):
    """Execute claimRewardsOnBehalf and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    claim_event = ClaimRewardsFarmEvent(
        amount=farm_token_amount,
        nonce=farm_token_nonce,
        attributes="",
    )
    tx_hash = farm_contract.claim_rewards_on_behalf(network_providers, user, claim_event)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _merge_farm_positions(
    farm_contract,
    user,
    farm_tokens,
    network_providers,
    blockchain_controller,
    original_caller="",
):
    """Execute mergeFarmTokens and return tx_hash."""
    user.sync_nonce(network_providers.proxy)
    if not isinstance(farm_tokens, list):
        farm_tokens = [farm_tokens]
    merge_events = [
        MergePositionFarmEvent(
            amount=token.amount,
            nonce=token.token.nonce,
            original_caller=original_caller,
        )
        for token in farm_tokens
    ]
    tx_hash = farm_contract.mergePositions(network_providers, user, merge_events)
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _whitelist_address(
    farm_contract,
    deployer_account,
    proxy,
    address_to_whitelist,
    blockchain_controller,
):
    """Whitelist an address via addSCAddressToWhitelist."""
    deployer_account.sync_nonce(proxy)
    tx_hash = farm_contract.add_contract_to_whitelist(
        deployer_account,
        proxy,
        address_to_whitelist,
    )
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _remove_from_whitelist(
    farm_contract,
    deployer_account,
    proxy,
    address_to_remove,
    blockchain_controller,
):
    """Remove an address from the SC whitelist."""
    deployer_account.sync_nonce(proxy)
    tx_hash = farm_contract.remove_contract_from_whitelist(
        deployer_account,
        proxy,
        address_to_remove,
    )
    blockchain_controller.wait_for_tx(tx_hash)
    return tx_hash


def _get_farm_tokens_for_user(farm_contract, user, proxy):
    """Get all farm token NFTs held by user."""
    all_nfts = proxy.get_non_fungible_tokens_of_account(user.address)
    farm_token_prefix = farm_contract.farmToken.split("-")[0]
    return [t for t in all_nfts if t.token.identifier.startswith(farm_token_prefix)]


def _get_minimum_farming_epochs(farm_contract, proxy):
    """Get minimum farming epochs from farm contract storage."""
    resp = requests.get(f"{proxy.url}/address/{farm_contract.address}/keys")
    keys = resp.json().get("data", {}).get("pairs", {})
    key_hex = "minimum_farming_epochs".encode().hex()
    val_hex = keys.get(key_hex, "")
    if val_hex:
        return int(val_hex, 16)
    return 0


def _get_farming_token_balance(farm_contract, user, proxy):
    """Get user's balance of the farming token (LP token)."""
    all_tokens = proxy.get_fungible_tokens_of_account(user.address)
    for t in all_tokens:
        if t.token.identifier == farm_contract.farmingToken:
            return t.amount
    return 0


def _get_user_total_farm_position(farm_contract, user, proxy):
    """Get user's total farm position via contract view."""
    position = farm_contract.get_user_total_farm_position(user.address.to_bech32(), proxy)
    if position >= 0:
        return position
    return sum(token.amount for token in _get_farm_tokens_for_user(farm_contract, user, proxy))


def _get_current_week(farm_contract, proxy):
    """Get current boosted-yields week via contract view."""
    current_week = farm_contract.get_current_week(proxy)
    if current_week >= 0:
        return current_week

    current_epoch = proxy.get_network_status().current_epoch
    first_week_start_epoch = farm_contract.get_first_week_start_epoch(proxy)
    if first_week_start_epoch < 0:
        first_week_start_epoch = 0
    if current_epoch < first_week_start_epoch:
        return 0
    return ((current_epoch - first_week_start_epoch) // 7) + 1


def _get_claim_progress(farm_contract, user, proxy):
    """Get claim progress for a user."""
    return farm_contract.get_current_claim_progress_for_user(user.address.to_bech32(), proxy)


def _get_boosted_yields_percentage(farm_contract, proxy):
    """Get boosted rewards percentage, with storage fallback."""
    fetcher = FarmContractDataFetcher(Address.new_from_bech32(farm_contract.address), proxy.url)
    boosted_pct = fetcher.get_data("getBoostedYieldsRewardsPercentage")
    if boosted_pct >= 0:
        return boosted_pct
    # Fallback to storage key
    resp = requests.get(f"{proxy.url}/address/{farm_contract.address}/keys")
    keys = resp.json().get("data", {}).get("pairs", {})
    key_hex = "boostedYieldsRewardsPercentage".encode().hex()
    val_hex = keys.get(key_hex, "")
    if val_hex:
        return int(val_hex, 16)
    return 0


def _get_locked_token_id(farm_contract, proxy):
    """Get the locked reward token ID (XMEX) from the farm's locking SC."""
    fetcher = FarmContractDataFetcher(Address.new_from_bech32(farm_contract.address), proxy.url)
    locking_hex = fetcher.get_data("getLockingScAddress")
    if not locking_hex:
        resp = requests.get(f"{proxy.url}/address/{farm_contract.address}/keys")
        keys = resp.json().get("data", {}).get("pairs", {})
        locking_key = "lockingScAddress".encode().hex()
        locking_hex = keys.get(locking_key)
    if not locking_hex:
        return None
    locking_addr = Address(bytes.fromhex(locking_hex), "erd").to_bech32()

    lock_fetcher = SimpleLockEnergyContractDataFetcher(
        Address.new_from_bech32(locking_addr), proxy.url
    )
    locked_token_hex = lock_fetcher.get_data("getLockedTokenId")
    if locked_token_hex:
        return hex_to_string(locked_token_hex)

    resp2 = requests.get(f"{proxy.url}/address/{locking_addr}/keys")
    keys2 = resp2.json().get("data", {}).get("pairs", {})
    for key_name in ["lockedTokenId", "locked_token_id"]:
        hex_key = key_name.encode().hex()
        if hex_key in keys2:
            return hex_to_string(keys2[hex_key])
    return None


def _get_locked_tokens_for_user(farm_contract, user, proxy):
    """Get locked reward tokens (XMEX) held by user."""
    locked_token_id = _get_locked_token_id(farm_contract, proxy)
    all_nfts = proxy.get_non_fungible_tokens_of_account(user.address)
    if locked_token_id:
        locked_prefix = locked_token_id.split("-")[0]
        return [t for t in all_nfts if t.token.identifier.startswith(locked_prefix)]

    farm_prefix = farm_contract.farmToken.split("-")[0]
    return [t for t in all_nfts if not t.token.identifier.startswith(farm_prefix)]


def _ensure_deployer_has_egld(deployer_account, test_environment, network_providers):
    """Ensure deployer account has EGLD for gas fees on chain simulator."""
    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        account_data = network_providers.proxy.get_account(deployer_account.address)
        min_egld = nominated_amount(10)
        if account_data.balance < min_egld:
            logger.info("Funding deployer with EGLD for gas")
            test_environment.chain_sim.fund_users_w_egld(
                [deployer_account.address.to_bech32()],
                min_egld,
            )
