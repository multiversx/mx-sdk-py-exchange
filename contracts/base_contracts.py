### This is a collection of base contract that augments
### the base contract class. It is meant to be inherited
### by other contracts that want to use these common features.

from utils.logger import get_logger
from multiversx_sdk import ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue, U64Value
from contracts.contract_identities import DEXContractInterface
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils.utils_generic import log_unexpected_args
from utils.utils_tx import endpoint_call
from utils.contract_data_fetchers import BaseBoostedContractDataFetcher, BaseContractWhitelistDataFetcher, BaseFarmContractDataFetcher
from utils import decoding_structures
from typing import Dict, List, Any
from abc import abstractmethod, ABC


logger = get_logger(__name__)


class BaseBoostedContract(DEXContractInterface, ABC):
    
    def get_user_total_farm_position(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getUserTotalFarmPosition', [AddressValue.new_from_address(Address(user_address))])
        if not raw_results:
            return 0
        user_farm_position = int(raw_results)

        return user_farm_position
    
    def get_current_week(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getCurrentWeek')
        if not raw_results:
            return 0
        current_week = int(raw_results)

        return current_week
    
    def get_first_week_start_epoch(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getFirstWeekStartEpoch')
        if not raw_results:
            return 0
        result = int(raw_results)

        return result

    def get_next_week_start_epoch(self, proxy: ProxyNetworkProvider) -> int:
        first_week = self.get_first_week_start_epoch(proxy)
        current_week = self.get_current_week(proxy)
        next_week_at_epoch = first_week + current_week * 7

        return next_week_at_epoch
    
    def get_last_global_update_week(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getLastGlobalUpdateWeek')
        if not raw_results:
            return 0
        result = int(raw_results)

        return result
    
    def get_user_energy_for_week(self, user_address: str, proxy: ProxyNetworkProvider, week: int) -> Dict[str, Any]:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getUserEnergyForWeek', [AddressValue.new_from_address(Address(user_address)), U64Value(week)])
        if not raw_results:
            return {}
        user_energy_for_week = decode_merged_attributes(raw_results, decoding_structures.ENERGY_ENTRY)

        return user_energy_for_week
    
    def get_last_active_week_for_user(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getLastActiveWeekForUser', [AddressValue.new_from_address(Address(user_address))])
        if not raw_results:
            return 0
        week = int(raw_results)

        return week
    
    def get_current_claim_progress_for_user(self, user_address: str, proxy: ProxyNetworkProvider) -> Dict[str, Any]:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getCurrentClaimProgress', [AddressValue.new_from_address(Address(user_address))])
        if not raw_results:
            return {}
        response = decode_merged_attributes(raw_results, decoding_structures.USER_CLAIM_PROGRESS)

        return response
    
    def get_farm_supply_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getFarmSupplyForWeek', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_total_locked_tokens_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getTotalLockedTokensForWeek', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)

    def get_accumulated_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getAccumulatedRewardsForWeek', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_total_energy_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getTotalEnergyForWeek', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_total_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getTotalRewardsForWeek', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_remaining_boosted_rewards_to_distribute(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getRemainingBoostedRewardsToDistribute', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_undistributed_boosted_rewards(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = BaseBoostedContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getUndistributedBoostedRewards', [U64Value(week)])
        if not raw_results:
            return 0
        return int(raw_results)

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
    
    def get_farm_token_supply(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getFarmTokenSupply')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_reward_reserve(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getRewardReserve')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_last_reward_block_nonce(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getLastRewardBlockNonce')
        if not raw_results:
            return 0
        return int(raw_results)

    def get_last_reward_timestamp(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getLastRewardTimestamp')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_per_block_reward_amount(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getPerBlockRewardAmount')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_reward_per_share(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getRewardPerShare')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_division_safety_constant(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getDivisionSafetyConstant')
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_farm_token_id(self, proxy: ProxyNetworkProvider) -> str:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getFarmTokenId')
        if not raw_results:
            return ""
        return hex_to_string(raw_results)
    
    def get_farming_token_id(self, proxy: ProxyNetworkProvider) -> str:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getFarmingTokenId')
        if not raw_results:
            return ""
        return hex_to_string(raw_results)
    
    def get_state(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = BaseFarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getState')
        if not raw_results:
            return 0
        return int(raw_results)
    
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
        function_purpose = "Add contract to sc whitelist"
        logger.info(function_purpose)
        
        gas_limit = 30000000
        sc_args = [whitelisted_sc_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addSCAddressToWhitelist", sc_args)
    
    def remove_contract_from_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str) -> str:
        function_purpose = "Remove contract from sc whitelist"
        logger.info(function_purpose)
        
        gas_limit = 30000000
        sc_args = [whitelisted_sc_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeSCAddressFromWhitelist", sc_args)
    
    def is_contract_whitelisted(self, address: str, proxy: ProxyNetworkProvider) -> bool:
        data_fetcher = BaseContractWhitelistDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('isSCAddressWhitelisted', [AddressValue.new_from_address(Address(address))])
        if not raw_results:
            return False
        return bool(raw_results)
    

class BasePermissionsHubContract(DEXContractInterface, ABC):

    def set_permissions_hub_address(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        """Only V3.
        """
        function_purpose = "Set permissions hub address"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = [address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setPermissionsHubAddress", sc_args)
    
