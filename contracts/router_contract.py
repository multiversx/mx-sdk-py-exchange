import config
from contracts.contract_identities import (DEXContractInterface, RouterContractVersion,
                                           _as_addresses, _ConfigField, _Endpoint,
                                           _leading_addresses)
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, get_deployed_address_from_tx
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from utils.contract_data_fetchers import RouterContractDataFetcher
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


def _enable_by_user_parameters(args: list) -> list:
    """The four parameters the enable-by-user config takes, out of the keywords it was given.

    Alone among the 46 Endpoint Wrappers on the router, the pair and the simple lock, this one is
    called with keywords rather than a list, so what it is handed is the mapping itself and the
    build is what puts the four in order. Reading them here rather than in the wrapper keeps a
    missing keyword raising *after* the purpose is announced, as it always has.
    """
    parameters, = args
    return [parameters['common_token_id'], parameters['locked_token_id'],
            parameters['min_locked_token_value'], parameters['min_lock_period_epochs']]


def _pair_arguments(args: list) -> list:
    """The five parameters `createPair` takes, of which only the liquidity adder is an address."""
    return [args[0], args[1], Address(args[2]), args[3], args[4]]


def _pair_arguments_with_admins(args: list) -> list:
    """The five, followed by the admin addresses only a V2 router has anywhere to put."""
    return [*_pair_arguments(args), *args[5:]]


# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# Four of these endpoints act on a pool and two on the router itself, and the two pairs disagree
# about whose address to name: `pause` and `resume` send the router's own, where their
# `pair_contract_*` opposite numbers send the pool they were handed. Preserved as declared.
_ADD_COMMON_TOKENS_FOR_USER_PAIRS = _Endpoint("Add common tokens for user pairs", 100000000,
                                              "addCommonTokensForUserPairs")
_REMOVE_COMMON_TOKENS_FOR_USER_PAIRS = _Endpoint("Remove common tokens for user pairs", 100000000,
                                                 "removeCommonTokensForUserPairs")
_CONFIG_ENABLE_BY_USER_PARAMETERS = _Endpoint("Add enable config for common token", 100000000,
                                              "configEnableByUserParameters",
                                              build=_enable_by_user_parameters)

# The one endpoint here declared twice: which of the two a call takes is the router's version, and
# a V1 router drops anything past the fifth argument rather than forwarding it as an admin.
_CREATE_PAIR = _Endpoint("Deploy pair via router", 100000000, "createPair", at_least=5,
                         build=_pair_arguments)
_CREATE_PAIR_V2 = _Endpoint("Deploy pair via router", 100000000, "createPair", at_least=5,
                            build=_pair_arguments_with_admins)
_UPGRADE_PAIR = _Endpoint("Upgrade pair contract", 200000000, "upgradePair", at_least=2)
_ISSUE_LP_TOKEN = _Endpoint("Issue LP token", 100000000, "issueLpToken", exactly=3,
                            build=_leading_addresses(1),
                            value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_SET_LOCAL_ROLES = _Endpoint("Set LP token local roles", 100000000, "setLocalRoles",
                             build=_as_addresses)

_SET_FEE_ON = _Endpoint("Set fee on for pool", 100000000, "setFeeOn", exactly=3,
                        build=_leading_addresses(2))
_SET_FEE_OFF = _Endpoint("Set fee off for pool", 100000000, "setFeeOff", exactly=3,
                         build=_leading_addresses(2))

_PAIR_CONTRACT_PAUSE = _Endpoint("Pause pair contract", 60000000, "pause", build=_as_addresses)
_PAIR_CONTRACT_RESUME = _Endpoint("Resume pair contract", 60000000, "resume", build=_as_addresses)
_PAUSE = _Endpoint("Pause router contract", 60000000, "pause", build=_as_addresses)
_RESUME = _Endpoint("Resume router contract", 60000000, "resume", build=_as_addresses)

_SET_PAIR_CREATION_ENABLED = _Endpoint("Set pair creation enabled/disabled", 20000000,
                                       "setPairCreationEnabled", exactly=1,
                                       build=lambda args: [1 if args[0] else 0])
# The one endpoint in `contracts/` whose gas is nothing but its argument count: 9M per pair, and
# no base at all, where the fees collector's two scaling endpoints add theirs to a 10M floor.
_CLAIM_DEVELOPER_REWARDS_PAIRS = _Endpoint("Claim developer rewards for pairs", 0,
                                           "claimDeveloperRewardsPairs", build=_as_addresses,
                                           gas_per_argument=9000000)
_WITHDRAW_EGLD = _Endpoint("Withdraw EGELD from router contract", 10000000, "withdrawEgld")
_SET_SAFE_PRICE_ROUND_SAVE_INTERVAL = _Endpoint("Set safe price round save interval", 10000000,
                                                "setSafePriceRoundSaveInterval")
_SET_DEFAULT_SAFE_PRICE_ROUNDS_OFFSET = _Endpoint("Set default safe price rounds offset", 10000000,
                                                  "setDefaultSafePriceRoundsOffset")


class RouterContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("version", enum=RouterContractVersion),
    )

    def __init__(self, version: RouterContractVersion, address: str = ""):
        self.address = address
        self.version = version

    @classmethod
    def load_contract_by_address(cls, address: str, version=RouterContractVersion.V2):
        return RouterContract(version, address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        type[str]: pair template address
        """
        function_purpose = f"Deploy router contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = [
            Address(args[0])
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path):
        function_purpose = f"Upgrade router contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, [])

        return tx_hash

    def add_common_tokens_for_user_pairs(self, owner: Account, proxy: ProxyNetworkProvider, *tokens):
        """Expecting as args:
            type[str..]: common token IDs
        """
        return self._call_endpoint(_ADD_COMMON_TOKENS_FOR_USER_PAIRS, owner, proxy, list(tokens))

    def remove_common_tokens_for_user_pairs(self, owner: Account, proxy: ProxyNetworkProvider, *tokens):
        """Expecting as args:
            type[str..]: common token IDs
        """
        return self._call_endpoint(_REMOVE_COMMON_TOKENS_FOR_USER_PAIRS, owner, proxy, list(tokens))

    def config_enable_by_user_parameters(self, deployer: Account, proxy: ProxyNetworkProvider, **kargs):
        """Expecting as args:
            type[str]: common_token_id
            type[str]: locked_token_id
            type[int]: min_locked_token_value
            type[int]: min_lock_period_epochs
        """
        return self._call_endpoint(_CONFIG_ENABLE_BY_USER_PARAMETERS, deployer, proxy, [kargs])

    def pair_contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: first pair token
            type[str]: second pair token
            type[str]: address of initial liquidity adder
            type[str]: total fee percentage
            type[str]: special fee percentage
            type[str..]: admin addresses (v2 only)
        """
        endpoint = _CREATE_PAIR_V2 if self.version == RouterContractVersion.V2 else _CREATE_PAIR
        tx_hash = self._call_endpoint(endpoint, deployer, proxy, args)

        # the pool is deployed from a template, so its address only exists once the call has gone out
        address = get_deployed_address_from_tx(tx_hash, proxy) if tx_hash != "" else ""
        return tx_hash, address

    def pair_contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """ Expected as args:
        type[str]: first token id
        type[str]: second token id
        """
        return self._call_endpoint(_UPGRADE_PAIR, deployer, proxy, args)

    def issue_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address
            type[str]: lp token name
            type[str]: lp token ticker
        """
        return self._call_endpoint(_ISSUE_LP_TOKEN, deployer, proxy, args)

    def set_lp_token_local_roles(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        return self._call_endpoint(_SET_LOCAL_ROLES, deployer, proxy, [pair_contract])

    def set_fee_on(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address to send fees
            type[str]: address to receive fees
            type[str]: expected token
        """
        return self._call_endpoint(_SET_FEE_ON, deployer, proxy, args)

    def set_fee_off(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address to send fees
            type[str]: address to receive fees
            type[str]: expected token
        """
        return self._call_endpoint(_SET_FEE_OFF, deployer, proxy, args)

    def pair_contract_pause(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        return self._call_endpoint(_PAIR_CONTRACT_PAUSE, deployer, proxy, [pair_contract])

    def pair_contract_resume(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        return self._call_endpoint(_PAIR_CONTRACT_RESUME, deployer, proxy, [pair_contract])

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_PAUSE, deployer, proxy, [self.address])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [self.address])

    def set_pair_creation_enabled(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[bool]: enabled or disabled
        """
        return self._call_endpoint(_SET_PAIR_CREATION_ENABLED, deployer, proxy, args)

    def claim_developer_rewards_pairs(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contracts: list[str]):
        return self._call_endpoint(_CLAIM_DEVELOPER_REWARDS_PAIRS, deployer, proxy, pair_contracts)

    def withdraw_egld(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_WITHDRAW_EGLD, deployer, proxy, [])

    def set_safe_price_round_save_interval(self, deployer: Account, proxy: ProxyNetworkProvider, interval: int):
        """ Expected as args:
            type[int]: interval
        """
        return self._call_endpoint(_SET_SAFE_PRICE_ROUND_SAVE_INTERVAL, deployer, proxy, [interval])

    def set_default_safe_price_rounds_offset(self, deployer: Account, proxy: ProxyNetworkProvider, offset: int):
        """
        Sets the default safe price rounds offset for the legacy safe price views.
        Expected as args:
            type[int]: offset
        """
        return self._call_endpoint(_SET_DEFAULT_SAFE_PRICE_ROUNDS_OFFSET, deployer, proxy, [offset])


    # Alone among the View Getters, this one names no `empty`: an address is the one kind with no
    # empty value, so a view that answers with nothing still raises here rather than returning "".
    def get_pair_template_address(self, proxy: ProxyNetworkProvider):
        return self._query_view(proxy, RouterContractDataFetcher, "getPairTemplateAddress",
                                returns=Address)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed router contract: {self.address}")
