### This is a collection of base contract that augments
### the base contract class. It is meant to be inherited
### by other contracts that want to use these common features.

import requests

from utils.logger import get_logger
from multiversx_sdk import ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue, U64Value
from contracts.contract_identities import DEXContractInterface, _Endpoint
from utils.utils_chain import Account, WrapperAddress as Address
from utils.contract_data_fetchers import BaseBoostedContractDataFetcher, BaseContractWhitelistDataFetcher, BaseFarmContractDataFetcher
from utils import decoding_structures
from typing import Dict, List, Any
from abc import abstractmethod, ABC


logger = get_logger(__name__)

# The three endpoints no contract declares for itself: they come with a base, and the pair, the
# router, the metastaking contract and the DEX proxy all inherit at least one. Each sends the bech32
# text it was handed rather than converting it — the choice their eight opposite numbers on the fees
# collector and the DEX proxy split down the middle.
_ADD_SC_ADDRESS_TO_WHITELIST = _Endpoint("Add contract to sc whitelist", 30000000,
                                         "addSCAddressToWhitelist")
_REMOVE_SC_ADDRESS_FROM_WHITELIST = _Endpoint("Remove contract from sc whitelist", 30000000,
                                              "removeSCAddressFromWhitelist")
_SET_PERMISSIONS_HUB_ADDRESS = _Endpoint("Set permissions hub address", 10000000,
                                         "setPermissionsHubAddress")


class BaseBoostedContract(DEXContractInterface, ABC):

    def _get_storage_int(self, proxy: ProxyNetworkProvider, *key_names: str) -> int:
        try:
            resp = requests.get(f"{proxy.url}/address/{self.address}/keys")
            keys = resp.json().get("data", {}).get("pairs", {})
            for key_name in key_names:
                key_hex = key_name.encode().hex()
                val_hex = keys.get(key_hex, "")
                if val_hex:
                    return int(val_hex, 16)
        except Exception:
            pass
        return 0
    
    def _sum_farm_token_holdings(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        """The user's farm position summed from their farm tokens — what answers when the view cannot."""
        try:
            all_nfts = proxy.get_non_fungible_tokens_of_account(Address(user_address))
            farm_prefix = self.farmToken.split("-")[0]
            return sum(t.amount for t in all_nfts if t.token.identifier.startswith(farm_prefix))
        except Exception:
            return 0

    def _week_from_epochs(self, proxy: ProxyNetworkProvider) -> int:
        """The current week derived from the epoch — what answers when the view cannot."""
        current_epoch = proxy.get_network_status().current_epoch
        first_week = self.get_first_week_start_epoch(proxy)
        if current_epoch < first_week:
            return 0
        return ((current_epoch - first_week) // 7) + 1

    def get_user_total_farm_position(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getUserTotalFarmPosition',
                                [AddressValue.new_from_address(Address(user_address))],
                                fallback=lambda: self._sum_farm_token_holdings(user_address, proxy))

    def get_current_week(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getCurrentWeek',
                                fallback=lambda: self._week_from_epochs(proxy))

    def get_first_week_start_epoch(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getFirstWeekStartEpoch',
                                fallback=lambda: self._get_storage_int(proxy, "firstWeekStartEpoch", "first_week_start_epoch"))

    def get_next_week_start_epoch(self, proxy: ProxyNetworkProvider) -> int:
        first_week = self.get_first_week_start_epoch(proxy)
        current_week = self.get_current_week(proxy)
        next_week_at_epoch = first_week + current_week * 7

        return next_week_at_epoch

    def get_last_global_update_week(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getLastGlobalUpdateWeek')

    def get_user_energy_for_week(self, user_address: str, proxy: ProxyNetworkProvider, week: int) -> Dict[str, Any]:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getUserEnergyForWeek',
                                [AddressValue.new_from_address(Address(user_address)), U64Value(week)],
                                returns=decoding_structures.ENERGY_ENTRY)

    def get_last_active_week_for_user(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getLastActiveWeekForUser',
                                [AddressValue.new_from_address(Address(user_address))])

    def get_current_claim_progress_for_user(self, user_address: str, proxy: ProxyNetworkProvider) -> Dict[str, Any]:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getCurrentClaimProgress',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=decoding_structures.USER_CLAIM_PROGRESS)

    def get_farm_supply_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getFarmSupplyForWeek',
                                [U64Value(week)],
                                fallback=lambda: self.get_farm_token_supply(proxy))

    def get_total_locked_tokens_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getTotalLockedTokensForWeek',
                                [U64Value(week)])

    def get_accumulated_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getAccumulatedRewardsForWeek',
                                [U64Value(week)])

    def get_total_energy_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        # Alone among the boosted getters, this one reports a failed query as 0 rather than passing
        # the sentinel on.
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getTotalEnergyForWeek',
                                [U64Value(week)],
                                fallback=lambda: 0)

    def get_total_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getTotalRewardsForWeek',
                                [U64Value(week)])

    def get_remaining_boosted_rewards_to_distribute(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getRemainingBoostedRewardsToDistribute',
                                [U64Value(week)])

    def get_undistributed_boosted_rewards(self, proxy: ProxyNetworkProvider, week: int) -> int:
        return self._query_view(proxy, BaseBoostedContractDataFetcher, 'getUndistributedBoostedRewards',
                                [U64Value(week)])

    def get_all_boosted_global_stats(self, proxy: ProxyNetworkProvider, week: int = None) -> Dict[str, Any]:
        """Fetches all global stats for a given week. If no week is provided, it will fetch the current week."""
        if week is None:
            week = self.get_current_week(proxy)

        logger.debug(f"Fetching global boosted stats for {self.address} on week {week}")
        
        staking_stats = {
            "first_week": self.get_first_week_start_epoch(proxy),
            "current_week": self.get_current_week(proxy),
            "farm_supply_for_week": self.get_farm_supply_for_week(proxy, week),
            "total_rewards_for_week": self.get_total_rewards_for_week(proxy, week),
            "total_locked_tokens_for_week": self.get_total_locked_tokens_for_week(proxy, week),
            "accumulated_rewards_for_week": self.get_accumulated_rewards_for_week(proxy, week),
            "total_energy_for_week": self.get_total_energy_for_week(proxy, week)
        }
        return staking_stats
        
    def get_all_user_boosted_stats(self, user_address: str, proxy: ProxyNetworkProvider, week: int = None) -> Dict[str, Any]:
        """Fetches all user stats for a given week. If no week is provided, it will fetch the current week."""
        if week is None:
            week = self.get_current_week(proxy)

        logger.debug(f"Fetching user boosted stats for {user_address} on week {week} on {self.address}")

        user_stats = {
            "user_total_farm_position": self.get_user_total_farm_position(user_address, proxy),
            "user_energy_for_week": self.get_user_energy_for_week(user_address, proxy, week),
            "last_active_week": self.get_last_active_week_for_user(user_address, proxy),
            "current_claim_progress": self.get_current_claim_progress_for_user(user_address, proxy)
        }
        return user_stats


class BaseFarmContract(DEXContractInterface, ABC):

    def _get_storage_int(self, proxy: ProxyNetworkProvider, *key_names: str) -> int:
        try:
            resp = requests.get(f"{proxy.url}/address/{self.address}/keys")
            keys = resp.json().get("data", {}).get("pairs", {})
            for key_name in key_names:
                key_hex = key_name.encode().hex()
                val_hex = keys.get(key_hex, "")
                if val_hex:
                    return int(val_hex, 16)
        except Exception:
            pass
        return 0
    
    def get_farm_token_supply(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getFarmTokenSupply',
                                fallback=lambda: self._get_storage_int(proxy, 'farm_token_supply', 'farmTokenSupply'))

    def get_reward_reserve(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getRewardReserve',
                                fallback=lambda: self._get_storage_int(proxy, 'reward_reserve', 'rewardReserve'))

    def get_last_reward_block_nonce(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getLastRewardBlockNonce',
                                fallback=lambda: self._get_storage_int(proxy, 'last_reward_block_nonce', 'lastRewardBlockNonce'))

    def get_last_reward_timestamp(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getLastRewardTimestamp')

    def get_per_block_reward_amount(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getPerBlockRewardAmount',
                                fallback=lambda: self._get_storage_int(proxy, 'per_block_reward_amount', 'perBlockRewardAmount'))

    def get_per_second_reward_amount(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getPerSecondRewardAmount',
                                fallback=lambda: self._get_storage_int(proxy, 'per_second_reward_amount', 'perSecondRewardAmount'))

    def get_reward_per_share(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getRewardPerShare',
                                fallback=lambda: self._get_storage_int(proxy, 'reward_per_share', 'rewardPerShare'))

    def get_division_safety_constant(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getDivisionSafetyConstant',
                                fallback=lambda: self._get_storage_int(proxy, 'division_safety_constant', 'divisionSafetyConstant'))

    def get_farm_token_id(self, proxy: ProxyNetworkProvider) -> str:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getFarmTokenId', returns=str)

    def get_farming_token_id(self, proxy: ProxyNetworkProvider) -> str:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getFarmingTokenId', returns=str)

    def get_state(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, BaseFarmContractDataFetcher, 'getState',
                                fallback=lambda: self._get_storage_int(proxy, 'state'))

    def get_produce_rewards_enabled(self, proxy: ProxyNetworkProvider) -> bool:
        """Whether per-block reward production is currently enabled.

        There is no view for this flag, so it is read straight from storage.
        A SingleValueMapper<bool> clears its entry when set to false, so an
        absent key means production is stopped.
        """
        return self._get_storage_int(proxy, 'produce_rewards_enabled') == 1

    def get_all_farm_global_stats(self, proxy: ProxyNetworkProvider) -> Dict[str, Any]:
        """Fetches all global stats for a farm."""

        logger.debug(f"Fetching global farm stats for {self.address}")
        
        farm_stats = {
            "farm_token_supply": self.get_farm_token_supply(proxy),
            "reward_reserve": self.get_reward_reserve(proxy),
            "reward_per_share": self.get_reward_per_share(proxy),
            "last_reward_block_nonce": self.get_last_reward_block_nonce(proxy),
            "last_reward_timestamp": self.get_last_reward_timestamp(proxy),
            "state": self.get_state(proxy)
        }
        return farm_stats
    

class BaseSCWhitelistContract(DEXContractInterface, ABC):
    
    def add_contract_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str) -> str:
        return self._call_endpoint(_ADD_SC_ADDRESS_TO_WHITELIST, deployer, proxy,
                                   [whitelisted_sc_address])

    def remove_contract_from_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str) -> str:
        return self._call_endpoint(_REMOVE_SC_ADDRESS_FROM_WHITELIST, deployer, proxy,
                                   [whitelisted_sc_address])

    def is_contract_whitelisted(self, address: str, proxy: ProxyNetworkProvider) -> bool:
        return self._query_view(proxy, BaseContractWhitelistDataFetcher, 'isSCAddressWhitelisted',
                                [AddressValue.new_from_address(Address(address))],
                                returns=bool)
    

class BasePermissionsHubContract(DEXContractInterface, ABC):

    def set_permissions_hub_address(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        """Only V3.
        """
        return self._call_endpoint(_SET_PERMISSIONS_HUB_ADDRESS, deployer, proxy, [address])
    
