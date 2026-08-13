import config
from contracts.contract_identities import (DEXContractInterface, _ConfigField, _Endpoint,
                                           _leading_addresses)
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_substep
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# The three issuances are the only calls here that send EGLD, and all three append the 18 decimals
# none of their callers passes — a fourth argument is refused, so 18 is the only precision a token
# on this contract can have.
_ISSUE_LP_PROXY_TOKEN = _Endpoint("Issue locked LP token", 100000000, "issueLpProxyToken",
                                  exactly=2, build=lambda args: [*args, 18],
                                  value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_ISSUE_FARM_PROXY_TOKEN = _Endpoint("Issue locked farm token", 100000000, "issueFarmProxyToken",
                                    exactly=2, build=lambda args: [*args, 18],
                                    value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_ISSUE_LOCKED_TOKEN = _Endpoint("Issue locked token", 100000000, "issueLockedToken", exactly=2,
                                build=lambda args: [*args, 18],
                                value=config.DEFAULT_ISSUE_TOKEN_PRICE)

_SET_LOCAL_ROLES_LOCKED_TOKEN = _Endpoint("Set local roles locked token", 100000000,
                                          "setLocalRolesLockedToken")
_SET_LOCAL_ROLES_LP_PROXY_TOKEN = _Endpoint("Set local roles locked lp token", 100000000,
                                            "setLocalRolesLpProxyToken")

_ADD_LP_TO_WHITELIST = _Endpoint("Add LP to Whitelist in simple lock contract", 100000000,
                                 "addLpToWhitelist", exactly=3, build=_leading_addresses(1))
_ADD_FARM_TO_WHITELIST = _Endpoint("Add Farm to Whitelist in simple lock contract", 100000000,
                                   "addFarmToWhitelist", exactly=3, build=_leading_addresses(1))

# The six user-facing ones, each handed its token list ready-made rather than an event.
_LOCK_TOKENS = _Endpoint("lock tokens", 10000000, "lockTokens", at_least=2, transfers=True)
_ADD_LIQUIDITY_LOCKED_TOKEN = _Endpoint("add liquidity for locked token", 20000000,
                                        "addLiquidityLockedToken", exactly=3, transfers=True)
# Announces the purpose above it, word for word, while calling the opposite endpoint. The purpose
# is what `logs/trace.log` is grepped for, so it is preserved as declared.
_REMOVE_LIQUIDITY_LOCKED_TOKEN = _Endpoint("add liquidity for locked token", 20000000,
                                           "removeLiquidityLockedToken", exactly=3, transfers=True)
_ENTER_FARM_LOCKED_TOKEN = _Endpoint("enter farm with locked token", 30000000,
                                     "enterFarmLockedToken", exactly=1, transfers=True)
_EXIT_FARM_LOCKED_TOKEN = _Endpoint("exit farm with locked token", 30000000, "exitFarmLockedToken",
                                    exactly=1, transfers=True)
_CLAIM_FARM_LOCKED_TOKEN = _Endpoint("claim farm with locked token", 30000000,
                                     "farmClaimRewardsLockedToken", exactly=1, transfers=True)


class SimpleLockContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("locked_token"),
        _ConfigField("lp_proxy_token"),
        # Committed deploy state predates this field — `deployed_simple_locks.json` carries no
        # such key — so it loads as `None` rather than raising.
        _ConfigField("farm_proxy_token", optional=True),
    )
    _CONTRACT_TOKENS = ("locked_token", "lp_proxy_token", "farm_proxy_token")

    def __init__(self, locked_token: str = "", lp_proxy_token: str = "", farm_proxy_token: str = "", address: str = ""):
        self.address = address
        self.locked_token = locked_token
        self.lp_proxy_token = lp_proxy_token
        self.farm_proxy_token = farm_proxy_token

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list | None = None):
        function_purpose = f"Deploy simple lock contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = []

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path):
        function_purpose = "Upgrade simple lock contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, [])

    def issue_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_ISSUE_LP_PROXY_TOKEN, deployer, proxy, args)

    def issue_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_ISSUE_FARM_PROXY_TOKEN, deployer, proxy, args)

    def issue_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_ISSUE_LOCKED_TOKEN, deployer, proxy, args)

    def set_local_roles_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_LOCAL_ROLES_LOCKED_TOKEN, deployer, proxy, [])

    def set_local_roles_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_LOCAL_ROLES_LP_PROXY_TOKEN, deployer, proxy, [])

    def add_lp_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address
            type[str]: first token identifier
            type[str]: second token identifier
        """
        return self._call_endpoint(_ADD_LP_TO_WHITELIST, deployer, proxy, args)

    def add_farm_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: farm address
            type[str]: farming token identifier
            type[str]: farm type: 0 - simple, 1 - locked, 2 - boosted
        """
        return self._call_endpoint(_ADD_FARM_TO_WHITELIST, deployer, proxy, args)

    def lock_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: lock epochs
        """
        return self._call_endpoint(_LOCK_TOKENS, user, proxy, args)

    def add_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        return self._call_endpoint(_ADD_LIQUIDITY_LOCKED_TOKEN, user, proxy, args)

    def remove_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        return self._call_endpoint(_REMOVE_LIQUIDITY_LOCKED_TOKEN, user, proxy, args)

    def enter_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_ENTER_FARM_LOCKED_TOKEN, user, proxy, args)

    def exit_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_EXIT_FARM_LOCKED_TOKEN, user, proxy, args)

    def claim_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_CLAIM_FARM_LOCKED_TOKEN, user, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed simple lock contract: {self.address}")
        log_substep(f"Locked token: {self.locked_token}")
        log_substep(f"Locked LP token: {self.lp_proxy_token}")
