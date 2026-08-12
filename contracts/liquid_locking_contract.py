import config
from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.contract_data_fetchers import LiquidLockingContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue
from typing import List, Dict, Any


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and how many arguments it requires. `_call_endpoint` on `DEXContractInterface`
# does the rest, so each wrapper below carries only its signature and the argument documentation its
# callers depend on.
#
# `lock` is the only endpoint here that moves tokens, and — alone among the five — the only one that
# does not count what it was handed: its opposite number `unlock` *names* the token rather than
# sending it, so it goes out as a plain call. The two `*_token` endpoints are also the only
# snake_case endpoint names on the contract.
_WHITELIST_TOKEN = _Endpoint("Whitelist token", 20000000, "whitelist_token", exactly=1)
_BLACKLIST_TOKEN = _Endpoint("Blacklist token", 20000000, "blacklist_token", exactly=1)
_LOCK = _Endpoint("lock tokens", 30000000, "lock", transfers=True)
_UNLOCK = _Endpoint("unlock tokens", 20000000, "unlock", exactly=1)
_UNBOND = _Endpoint("unbond tokens", 20000000, "unbond", exactly=1)


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
        return self._call_endpoint(_WHITELIST_TOKEN, deployer, proxy, args)

    def blacklist_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token identifier
        """
        return self._call_endpoint(_BLACKLIST_TOKEN, deployer, proxy, args)

    def lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: locked tokens
        """
        return self._call_endpoint(_LOCK, user, proxy, args)

    def unlock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens to unlock
        """
        return self._call_endpoint(_UNLOCK, user, proxy, args)

    def unbond(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[list[str]]: token identifiers
        """
        return self._call_endpoint(_UNBOND, user, proxy, args)


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
