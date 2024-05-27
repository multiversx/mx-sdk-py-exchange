import sys
import traceback

from contracts.base_contracts import BaseBoostedContract
from utils import decoding_structures
from utils.contract_data_fetchers import FeeCollectorContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ApiNetworkProvider, ProxyNetworkProvider


logger = get_logger(__name__)


class FeesCollectorContract(BaseBoostedContract):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return FeesCollectorContract(address=config_dict['address'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
            type[str]: locked token
            type[str]: energy factory address
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            args[0],
            Address(args[1])
        ]
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address
    
    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None,
                         no_init: bool = False):
        """ Expected as args:
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            # implement below in case of upgrade args needed
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)

        return tx_hash

    def add_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Add known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownContracts", sc_args)

    def add_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Add known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownTokens", args)

    def remove_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Remove known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownContracts", sc_args)

    def remove_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Remove known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownTokens", sc_args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, factory_address: str):
        """ Expected as args:
                    type[str]: energy factory address
        """
        function_purpose = f"Set Energy factory address in fees collector contract"
        logger.info(function_purpose)

        if not factory_address:
            log_unexpected_args(function_purpose, factory_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(factory_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress", sc_args)

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """ Expected as args:
            type[str]: locking address
        """
        function_purpose = f"Set locking address in fees collector"
        logger.info(function_purpose)

        if not locking_address:
            log_unexpected_args(function_purpose, locking_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(locking_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingScAddress", sc_args)

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        function_purpose = f"Set lock epochs in fees collector"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            lock_epochs
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockEpochs", sc_args)

    def set_locked_tokens_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, locked_tokens_per_block: int):
        function_purpose = f"Set locked tokens per block"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            locked_tokens_per_block
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockedTokensPerBlock", sc_args)

    def claim_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimRewards", sc_args)
    
    def claim_boosted_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimBoostedRewards", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed fees collector contract: {self.address}")

    def allow_external_claim(self, user: Account, proxy: ProxyNetworkProvider, allow_external_claim: bool):
        fn = 'setAllowExternalClaimRewards'
        sc_args = [
            allow_external_claim
        ]
        logger.info(f"{fn}")
        # logger.debug(f"Account: {user.address}")

        gas_limit = 80000000

        return endpoint_call(proxy, gas_limit ,user, Address(self.address), "setAllowExternalClaimRewards", sc_args)
    
    
    def get_user_energy_for_week(self, user: str, proxy: ProxyNetworkProvider, week: int) -> dict:
        user_address = Address(user)
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url) 

        raw_results = data_fetcher.get_data('getUserEnergyForWeek', [Address(user), week])
        print(raw_results)
        if not raw_results:
            return {}
        user_energy_for_week = decode_merged_attributes(raw_results, decoding_structures.ENERGY_ENTRY)

        return user_energy_for_week
    
    def get_current_week(self, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getCurrentWeek')
        if not raw_results:
            return 0
        current_week = int(raw_results)

        return current_week
    
    def get_last_active_week_for_user(self, user_address: str, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getLastActiveWeekForUser', [Address(user_address).get_public_key()])
        if not raw_results:
            return 0
        week = int(raw_results)

        return week

    def get_total_energy_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getTotalEnergyForWeek', [week])
        if not raw_results:
            return 0
        return int(raw_results)
    
    def get_total_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int) -> int:
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getTotalRewardsForWeek', [week])
        if not raw_results:
            return {}
        for data in raw_results:
            tokens_list = [decode_merged_attributes(data, decoding_structures.TOTAL_REWARDS_FOR_WEEK)]
            return tokens_list
        
        print(raw_results)
        print(tokens_list)

        return tokens_list
    
    def get_all_stats(self, proxy: ProxyNetworkProvider,user: Account, week: int):
        user_energy = self.get_user_energy_for_week(proxy, user.address.bech32())      
        logger.debug(f'User energy: {user_energy}')
        
        fees_collector_stats = {
            "first_week": self.get_first_week_start_epoch(proxy),
            "current_week": self.get_current_week(proxy),
            "total_rewards_for_week": self.get_total_rewards_for_week(proxy, week),
            "total_energy_for_week": self.get_total_energy_for_week(proxy, week)
        }
        return user_energy, fees_collector_stats
    

    def get_tx_op(self, tx_hash: str, operation: dict, api: ApiNetworkProvider) -> dict:
        used_api = api
        # Get the transaction details
        tx = used_api.get_transaction(tx_hash)
        print(tx)
        # Get and check transaction operations
        ops = tx.raw_response['operations']

        # Take each op in ops and match it with operation. Try to match only the fields expected in operation dictionary. 
        # TX Operations are unordered. If any of the operations match, return it.
        for op in ops:
            # print(f'Matching with {operation}')
            if all(op.get(key) == operation.get(key) for key in operation.keys()):
                return op