import config
from contracts.contract_identities import DEXContractInterface, ProxyContractVersion, _ConfigField, _Endpoint
from contracts.farm_contract import FarmContract
from contracts.pair_contract import PairContract
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider, CodeMetadata
from utils.contract_data_fetchers import ProxyContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, ESDTToken
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, \
    log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, base64_to_hex, dec_to_padded_hex, decode_merged_attributes, hex_to_string

from utils.decoding_structures import LKMEX_ATTRIBUTES, XMEX_ATTRIBUTES, XMEXFARM_ATTRIBUTES, XMEXLP_ATTRIBUTES

logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature, the
# tokens it builds out of the event it was handed, and the argument documentation its callers
# depend on.
#
# The five that take an event are the only Endpoint Wrappers in `contracts/` that never announce
# their purpose at info: they log themselves, the user and the whole event at debug instead, from
# their own bodies. The purpose still reaches `multi_esdt_endpoint_call`, which names it if it
# refuses the call itself.
_ADD_LIQUIDITY_PROXY = _Endpoint("add liquidity via proxy", 40000000, "addLiquidityProxy",
                                 transfers=True, announces_purpose=False)
_REMOVE_LIQUIDITY_PROXY = _Endpoint("remove liquidity via proxy", 40000000, "removeLiquidityProxy",
                                    transfers=True, announces_purpose=False)
_ENTER_FARM_PROXY = _Endpoint("enter farm via proxy", 50000000, "enterFarmProxy", transfers=True,
                              announces_purpose=False)
_EXIT_FARM_PROXY = _Endpoint("exit farm via proxy", 50000000, "exitFarmProxy", transfers=True,
                             announces_purpose=False)
_CLAIM_REWARDS_PROXY = _Endpoint("claim rewards via proxy", 50000000, "claimRewardsProxy",
                                 transfers=True, announces_purpose=False)

# The five that are handed their token list ready-made, and so can count what they were given.
_INCREASE_PROXY_LP_TOKEN_ENERGY = _Endpoint("increase proxy pair token energy", 50000000,
                                            "increaseProxyPairTokenEnergy", exactly=2,
                                            transfers=True)
_INCREASE_PROXY_FARM_TOKEN_ENERGY = _Endpoint("increase proxy farm token energy", 50000000,
                                              "increaseProxyFarmTokenEnergy", exactly=2,
                                              transfers=True)
_DESTROY_PROXY_FARM_TOKEN = _Endpoint("destroy proxy farm token", 50000000, "destroyFarmProxy",
                                      at_least=5, transfers=True)
_MERGE_PROXY_FARM_TOKENS = _Endpoint("merge proxy farm tokens", 50000000, "mergeWrappedFarmTokens",
                                     at_least=2, transfers=True)
_MERGE_PROXY_LP_TOKENS = _Endpoint("merge proxy lp tokens", 50000000, "mergeWrappedLpTokens",
                                   at_least=1, transfers=True)

_REGISTER_PROXY_FARM_TOKEN = _Endpoint("Register proxy farm token", 100000000, "registerProxyFarm",
                                       exactly=2, build=lambda args: [*args, 18],
                                       value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_REGISTER_PROXY_LP_TOKEN = _Endpoint("Register proxy lp token", 100000000, "registerProxyPair",
                                     exactly=2, build=lambda args: [*args, 18],
                                     value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_SET_LOCAL_ROLES_PROXY_TOKEN = _Endpoint("Set local roles for proxy token", 100000000,
                                         "setLocalRoles", exactly=2,
                                         build=lambda args: [*args, 3, 4, 5])

# All seven collaborator setters refuse an empty address and then send the bech32 text as it
# arrived — where the fees collector's three equivalents convert it first.
_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("Set energy factory address in proxy contract", 50000000,
                                        "setEnergyFactoryAddress", rejects_empty=True)
_ADD_PAIR_TO_INTERMEDIATE = _Endpoint("Add pair to intermediate in proxy contract", 50000000,
                                      "addPairToIntermediate", rejects_empty=True)
_ADD_FARM_TO_INTERMEDIATE = _Endpoint("Add farm to intermediate in proxy contract", 50000000,
                                      "addFarmToIntermediate", rejects_empty=True)
_SET_TRANSFER_ROLE_LOCKED_LP_TOKEN = _Endpoint(
    "Set transfer role on address for lp token; legacy endpoint", 100000000,
    "setTransferRoleLockedLpToken", rejects_empty=True)
_SET_TRANSFER_ROLE_LOCKED_FARM_TOKEN = _Endpoint(
    "Set transfer role on address for farm token; legacy endpoint", 100000000,
    "setTransferRoleLockedFarmToken", rejects_empty=True)
_SET_TRANSFER_ROLE_WRAPPED_LP_TOKEN = _Endpoint("Set transfer role on address for lp token",
                                                100000000, "setTransferRoleWrappedLpToken",
                                                rejects_empty=True)
_SET_TRANSFER_ROLE_WRAPPED_FARM_TOKEN = _Endpoint("Set transfer role on address for farm token",
                                                  100000000, "setTransferRoleWrappedFarmToken",
                                                  rejects_empty=True)

# Alone among the eight address-taking wrappers here, this one guards nothing. It is this
# contract's own copy of the endpoint `BaseSCWhitelistContract` gives the pair and the router.
_ADD_CONTRACT_TO_WHITELIST = _Endpoint("Add contract to proxy dex whitelist", 30000000,
                                       "addSCAddressToWhitelist")


class DexProxyAddLiquidityEvent:
    def __init__(self, pairContract: PairContract,
                 tokenA: str, nonceA: int, amountA: int, amountAmin: int,
                 tokenB: str, nonceB: int, amountB: int, amountBmin: int):
        self.pairContract = pairContract
        self.tokenA = tokenA
        self.nonceA = nonceA
        self.amountA = amountA
        self.amountAmin = amountAmin
        self.tokenB = tokenB
        self.nonceB = nonceB
        self.amountB = amountB
        self.amountBmin = amountBmin


class DexProxyRemoveLiquidityEvent:
    def __init__(self, pairContract: PairContract, amount: int, nonce: int, amountA: int, amountB: int):
        self.pairContract = pairContract
        self.amount = amount
        self.nonce = nonce
        self.amountA = amountA
        self.amountB = amountB


class DexProxyEnterFarmEvent:
    def __init__(self, farmContract: FarmContract,
                 farming_token: str, farming_nonce: int, farming_amount,
                 farm_token: str, farm_nonce: int, farm_amount):
        self.farmContract = farmContract
        self.farming_tk = farming_token
        self.farming_tk_nonce = farming_nonce
        self.farming_tk_amount = farming_amount
        self.farm_tk = farm_token
        self.farm_tk_nonce = farm_nonce
        self.farm_tk_amount = farm_amount


class DexProxyExitFarmEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount, original_caller: str = ""):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount
        self.original_caller = original_caller


class DexProxyClaimRewardsEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


class DexProxyCompoundRewardsEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


class DexProxyContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("token"),
        _ConfigField("locked_tokens"),
        _ConfigField("proxy_farm_token"),
        _ConfigField("proxy_lp_token"),
        _ConfigField("address"),
        _ConfigField("version", enum=ProxyContractVersion),
    )
    _CONTRACT_TOKENS = ("proxy_lp_token", "proxy_farm_token")

    def __init__(self, locked_tokens: list, token: str, version: ProxyContractVersion,
                 address: str = "", proxy_lp_token: str = "", proxy_farm_token: str = ""):
        self.address = address
        self.proxy_lp_token = proxy_lp_token
        self.proxy_farm_token = proxy_farm_token
        self.locked_tokens = locked_tokens
        self.token = token
        self.version = version

    @classmethod
    def load_contract_by_address(cls, address: str):
        data_fetcher = ProxyContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        locked_tokens = [hex_to_string(res) for res in data_fetcher.get_data("getLockedTokenIds")]
        token = hex_to_string(data_fetcher.get_data("getAssetTokenId"))
        proxy_lp_token = data_fetcher.get_data("getWrappedLpTokenId")
        proxy_farm_token = data_fetcher.get_data("getWrappedFarmTokenId")
        version = ProxyContractVersion.V2

        return DexProxyContract(locked_tokens, token, version, address, proxy_lp_token, proxy_farm_token)

    def add_liquidity_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyAddLiquidityEvent):
        logger.debug(f"Executing {_ADD_LIQUIDITY_PROXY.purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(event.tokenA, event.nonceA, event.amountA),
                  ESDTToken(event.tokenB, event.nonceB, event.amountB)
                  ]

        return self._call_endpoint(_ADD_LIQUIDITY_PROXY, user, proxy,
                                   [tokens, Address(event.pairContract.address),
                                    event.amountAmin, event.amountBmin])

    def remove_liquidity_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyRemoveLiquidityEvent):
        logger.debug(f"Executing {_REMOVE_LIQUIDITY_PROXY.purpose} for user {user.address} with event {event.__dict__}")

        # Alone among the five, the token identifier is the contract's rather than the event's.
        tokens = [ESDTToken(self.proxy_lp_token, event.nonce, event.amount)]

        return self._call_endpoint(_REMOVE_LIQUIDITY_PROXY, user, proxy,
                                   [tokens, Address(event.pairContract.address),
                                    event.amountA, event.amountB])

    def enter_farm_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyEnterFarmEvent):
        logger.debug(f"Executing {_ENTER_FARM_PROXY.purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk != "":
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        return self._call_endpoint(_ENTER_FARM_PROXY, user, proxy,
                                   [tokens, Address(event.farmContract.address)])

    def exit_farm_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyExitFarmEvent):
        logger.debug(f"Executing {_EXIT_FARM_PROXY.purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(event.token, event.nonce, event.amount)]

        return self._call_endpoint(_EXIT_FARM_PROXY, user, proxy,
                                   [tokens, Address(event.farmContract.address)])

    def claim_rewards_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyClaimRewardsEvent):
        logger.debug(f"Executing {_CLAIM_REWARDS_PROXY.purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(event.token, event.nonce, event.amount)]

        return self._call_endpoint(_CLAIM_REWARDS_PROXY, user, proxy,
                                   [tokens, Address(event.farmContract.address)])

    def increase_proxy_lp_token_energy(self, user: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to increase energy for
            type[int]: lock epochs
        """
        args = [] if args is None else args
        return self._call_endpoint(_INCREASE_PROXY_LP_TOKEN_ENERGY, user, proxy, args)

    def increase_proxy_farm_token_energy(self, user: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to increase energy for
            type[int]: lock epochs
        """
        args = [] if args is None else args
        return self._call_endpoint(_INCREASE_PROXY_FARM_TOKEN_ENERGY, user, proxy, args)

    def destroy_proxy_farm_token(self, user: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to destroy
            type[str]: farm address
            type[str]: pair address
            type[int]: first token slippage
            type[int]: second token slippage
            optional type[str]: original caller
        """
        args = [] if args is None else args
        return self._call_endpoint(_DESTROY_PROXY_FARM_TOKEN, user, proxy, args)

    def merge_proxy_farm_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to merge
            type[str]: farm address
        """
        args = [] if args is None else args
        return self._call_endpoint(_MERGE_PROXY_FARM_TOKENS, user, proxy, args)

    def merge_proxy_lp_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to merge
        """
        args = [] if args is None else args
        return self._call_endpoint(_MERGE_PROXY_LP_TOKENS, user, proxy, args)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list | None = None):
        """Expecting as args:
        type[list]: locked asset factories contract addresses; care for the correct order based on locked tokens list
        """
        args = [] if args is None else args
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        if len(self.locked_tokens) != len(args[0]):
            log_step_fail(f"FAIL: Failed to deploy contract. "
                                 f"Mismatch between locked tokens and factory addresses.")
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 300000000

        arguments = [self.token]
        locked_tokens_args = list(sum(zip(self.locked_tokens, args[0]), ()))
        arguments.extend(locked_tokens_args)

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path,
                         args: list | None = None, no_init: bool = False):
        """Expecting as args:
        type[str]: old_locked_token_id
        type[str]: old_factory_address
        """
        args = [] if args is None else args
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 2 and not no_init:
            log_unexpected_args(function_purpose, args)
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 300000000

        if no_init:
            arguments = []
        else:
            arguments = [
                args[0],
                Address(args[1])
            ]

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, arguments)

        return tx_hash

    def register_proxy_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_REGISTER_PROXY_FARM_TOKEN, deployer, proxy, args)

    def register_proxy_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_REGISTER_PROXY_LP_TOKEN, deployer, proxy, args)

    def set_local_roles_proxy_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: token id
            type[str]: contract address to assign roles to
        """
        return self._call_endpoint(_SET_LOCAL_ROLES_PROXY_TOKEN, deployer, proxy, args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_address: str):
        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy, [energy_address])

    def add_pair_to_intermediate(self, deployer: Account, proxy: ProxyNetworkProvider, pair_address: str):
        return self._call_endpoint(_ADD_PAIR_TO_INTERMEDIATE, deployer, proxy, [pair_address])

    def set_transfer_role_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        return self._call_endpoint(_SET_TRANSFER_ROLE_LOCKED_LP_TOKEN, deployer, proxy, [address])

    def set_transfer_role_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        return self._call_endpoint(_SET_TRANSFER_ROLE_LOCKED_FARM_TOKEN, deployer, proxy, [address])

    def set_transfer_role_wrapped_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        return self._call_endpoint(_SET_TRANSFER_ROLE_WRAPPED_LP_TOKEN, deployer, proxy, [address])

    def set_transfer_role_wrapped_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        return self._call_endpoint(_SET_TRANSFER_ROLE_WRAPPED_FARM_TOKEN, deployer, proxy, [address])

    def add_farm_to_intermediate(self, deployer: Account, proxy: ProxyNetworkProvider, farm_address: str):
        return self._call_endpoint(_ADD_FARM_TO_INTERMEDIATE, deployer, proxy, [farm_address])

    def add_contract_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str):
        return self._call_endpoint(_ADD_CONTRACT_TO_WHITELIST, deployer, proxy,
                                   [whitelisted_sc_address])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed proxy contract: {self.address}")
        log_substep(f"Token: {self.token}")
        log_substep(f"Locked tokens: {self.locked_tokens}")
        log_substep(f"Proxy LP token: {self.proxy_lp_token}")
        log_substep(f"Proxy Farm token: {self.proxy_farm_token}")

    def get_all_decoded_farm_token_attributes_from_api(self, api: ApiNetworkProvider, farm_token_nonce: int):
        # Get token details for a given farm token
        farm_token_on_network = api.get_non_fungible_token(self.proxy_farm_token, farm_token_nonce)

        # Decode the farm token attributes
        decoded_xmex_farm_attributes = decode_merged_attributes(base64_to_hex(farm_token_on_network.attributes), XMEXFARM_ATTRIBUTES)
        logger.debug(decoded_xmex_farm_attributes)

        # Decode the LP token attributes & underlying locked token
        xmex_lp_token_id = decoded_xmex_farm_attributes.get('proxy_token_id')
        if xmex_lp_token_id != self.proxy_lp_token:
            logger.error(f"Wrong token contained by XMEXFARM token: {xmex_lp_token_id} expected {self.proxy_lp_token}")

        decoded_xmex_lp_attributes, decoded_lk_token_attributes = self.get_all_decoded_lp_token_attributes_from_api(api, decoded_xmex_farm_attributes.get('proxy_token_nonce'))

        return decoded_xmex_farm_attributes, decoded_xmex_lp_attributes, decoded_lk_token_attributes
    
    def get_all_decoded_lp_token_attributes_from_api(self, api: ApiNetworkProvider, lp_token_nonce: int):
        # Decode the LP token attributes
        lp_token_on_network = api.get_non_fungible_token(self.proxy_lp_token, lp_token_nonce)

        decoded_xmex_lp_attributes = decode_merged_attributes(base64_to_hex(lp_token_on_network.attributes), XMEXLP_ATTRIBUTES)
        logger.debug(decoded_xmex_lp_attributes)

        # Decode the XMEX token attributes
        xmex_token_id = decoded_xmex_lp_attributes.get('locked_tokens_id')

        if xmex_token_id not in self.locked_tokens:
            logger.error(f"Locked token not found in locked tokens: {xmex_token_id}")

        xmex_token_on_network = api.get_non_fungible_token(xmex_token_id, decoded_xmex_lp_attributes.get('locked_tokens_nonce'))

        if "XMEX" in xmex_token_id:
            decoded_lk_token_attributes = decode_merged_attributes(base64_to_hex(xmex_token_on_network.attributes), XMEX_ATTRIBUTES)
        if "LKMEX" in xmex_token_id:
            decoded_lk_token_attributes = decode_merged_attributes(base64_to_hex(xmex_token_on_network.attributes), LKMEX_ATTRIBUTES)
        logger.debug(decoded_lk_token_attributes)

        return decoded_xmex_lp_attributes, decoded_lk_token_attributes
