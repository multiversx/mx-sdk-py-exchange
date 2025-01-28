import config
from contracts.contract_identities import DEXContractInterface
from utils.contract_data_fetchers import LiquidLockingContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from typing import List, Dict, Any


logger = get_logger(__name__)


class LiquidLockingContract(DEXContractInterface):
    def __init__(self, whitelisted_tokens: List = None, address: str = ""):
        self.address = address
        self.whitelisted_tokens = whitelisted_tokens

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "whitelisted_tokens": self.whitelisted_tokens
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return LiquidLockingContract(address=config_dict['address'],
                                     whitelisted_tokens=config_dict['whitelisted_tokens'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """ Expected as args:
            type[int]: unbond period
        """
        function_purpose = f"Deploy liquid locking contract"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        metadata = CodeMetadata(upgradeable=True, payable=True)
        gas_limit = 200000000

        arguments = args

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def whitelist_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token identifier
        """
        function_purpose = f"Whitelist token"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 20000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "whitelist_token", sc_args)
    
    def blacklist_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token identifier
        """
        function_purpose = f"Blacklist token"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 20000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "blacklist_token", sc_args)

    def lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: locked tokens
        """
        function_purpose = f"lock tokens"
        logger.info(function_purpose)

        gas_limit = 30000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user,
                                        Address(self.address), "lock", args)
    
    def unlock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens to unlock
        """
        function_purpose = f"unlock tokens"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        


        gas_limit = 20000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "unlock", sc_args)
    
    def unbond(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[list[str]]: token identifiers
        """
        function_purpose = f"unbond tokens"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 20000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "unbond", sc_args)
    
    def get_locked_token_amounts(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('lockedTokenAmounts', [Address(user_address).get_public_key()])
        if not raw_results:
            return {}
        locked_token_amounts = decode_merged_attributes(raw_results, decoding_structures.LIQUID_LOCKING_LOCKED_TOKEN_AMOUNTS)

        return locked_token_amounts
    
    def get_unlocked_token_amounts(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('unlockedTokenAmounts', [Address(user_address).get_public_key()])
        if not raw_results:
            return {}
        unlocked_token_amounts = decode_merged_attributes(raw_results, decoding_structures.LIQUID_LOCKING_UNLOCKED_TOKEN_AMOUNTS)

        return unlocked_token_amounts
    
    def get_locked_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('lockedTokens', [Address(user_address).get_public_key()])
        if not raw_results:
            return {}
        locked_tokens = [hex_to_string(entry) for entry in raw_results]

        return locked_tokens

    def get_unlocked_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('unlockedTokens', [Address(user_address).get_public_key()])
        if not raw_results:
            return {}
        unlocked_tokens = [hex_to_string(entry) for entry in raw_results]

        return unlocked_tokens
    
    def get_whitelisted_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('whitelistedTokens')
        if not raw_results:
            return {}
        tokens = [hex_to_string(entry) for entry in raw_results]

        return tokens
    
    def get_unbond_period(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = LiquidLockingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('unbondPeriod')

        return raw_results

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed liquid locking contract: {self.address}")
