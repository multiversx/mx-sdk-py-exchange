import config
from contracts.contract_identities import DEXContractInterface, _ConfigField
from utils.contract_data_fetchers import LiquidLockingContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue
from typing import List, Dict, Any


logger = get_logger(__name__)


class LiquidLockingContract(DEXContractInterface):
    # `whitelisted_tokens` are the tokens this contract accepts, not ones it issues, so it is
    # persisted but absent from `_CONTRACT_TOKENS`.
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("whitelisted_tokens"),
    )

    def __init__(self, whitelisted_tokens: List = None, address: str = ""):
        self.address = address
        self.whitelisted_tokens = whitelisted_tokens

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
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'lockedTokenAmounts',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=decoding_structures.LIQUID_LOCKING_LOCKED_TOKEN_AMOUNTS)

    def get_unlocked_token_amounts(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'unlockedTokenAmounts',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=decoding_structures.LIQUID_LOCKING_UNLOCKED_TOKEN_AMOUNTS)

    # The three token lists below answer `{}` rather than `[]` when the view is empty, which is what
    # they have always done and what their `Dict[str, Any]` annotation claims they always return.
    def get_locked_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'lockedTokens',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=[str], empty={})

    def get_unlocked_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'unlockedTokens',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=[str], empty={})

    def get_whitelisted_tokens(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'whitelistedTokens',
                                returns=[str], empty={})

    def get_unbond_period(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, LiquidLockingContractDataFetcher, 'unbondPeriod')

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed liquid locking contract: {self.address}")
