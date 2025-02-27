import config
from contracts.contract_identities import DEXContractInterface, ProxyContractVersion
from contracts.farm_contract import FarmContract
from contracts.pair_contract import PairContract
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider, CodeMetadata
from utils.contract_data_fetchers import ProxyContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, \
    endpoint_call, multi_esdt_endpoint_call, ESDTToken
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, \
    log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, base64_to_hex, dec_to_padded_hex, decode_merged_attributes, hex_to_string

from utils.decoding_structures import LKMEX_ATTRIBUTES, XMEX_ATTRIBUTES, XMEXFARM_ATTRIBUTES, XMEXLP_ATTRIBUTES

logger = get_logger(__name__)


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
    def __init__(self, locked_tokens: list, token: str, version: ProxyContractVersion,
                 address: str = "", proxy_lp_token: str = "", proxy_farm_token: str = ""):
        self.address = address
        self.proxy_lp_token = proxy_lp_token
        self.proxy_farm_token = proxy_farm_token
        self.locked_tokens = locked_tokens
        self.token = token
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "token": self.token,
            "locked_tokens": self.locked_tokens,
            "proxy_farm_token": self.proxy_farm_token,
            "proxy_lp_token": self.proxy_lp_token,
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return DexProxyContract(token=config_dict['token'],
                                locked_tokens=config_dict['locked_tokens'],
                                proxy_farm_token=config_dict['proxy_farm_token'],
                                proxy_lp_token=config_dict['proxy_lp_token'],
                                address=config_dict['address'],
                                version=ProxyContractVersion(config_dict['version']))
    
    def get_contract_tokens(self) -> list[str]:
        return [
            self.proxy_lp_token,
            self.proxy_farm_token
        ]

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
        function_purpose = "add liquidity via proxy"
        logger.debug(f"Executing {function_purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(event.tokenA, event.nonceA, event.amountA),
                  ESDTToken(event.tokenB, event.nonceB, event.amountB)
                  ]

        sc_args = [
            tokens,
            Address(event.pairContract.address),
            event.amountAmin,
            event.amountBmin
        ]
        gas_limit = 40000000

        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address),
                                        "addLiquidityProxy", sc_args)

    def remove_liquidity_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyRemoveLiquidityEvent):
        function_purpose = "remove liquidity via proxy"
        logger.debug(f"Executing {function_purpose} for user {user.address} with event {event.__dict__}")

        tokens = [ESDTToken(self.proxy_lp_token, event.nonce, event.amount)]

        sc_args = [
            tokens,
            Address(event.pairContract.address),
            event.amountA,
            event.amountB
        ]
        gas_limit = 40000000

        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address),
                                        "removeLiquidityProxy", sc_args)

    def enter_farm_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyEnterFarmEvent):
        function_purpose = "enter farm via proxy"
        logger.debug(f"Executing {function_purpose} for user {user.address} with event {event.__dict__}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk != "":
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        sc_args = [
            tokens,
            Address(event.farmContract.address)
        ]
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address),
                                        "enterFarmProxy", sc_args)

    def exit_farm_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyExitFarmEvent):
        function_purpose = "exit farm via proxy"
        logger.debug(f"Executing {function_purpose} for user {user.address} with event {event.__dict__}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.token, event.nonce, event.amount)]

        sc_args = [
            tokens,
            Address(event.farmContract.address)
        ]
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address),
                                        "exitFarmProxy", sc_args)

    def claim_rewards_proxy(self, user: Account, proxy: ProxyNetworkProvider, event: DexProxyClaimRewardsEvent):
        function_purpose = "claim rewards via proxy"
        logger.debug(f"Executing {function_purpose} for user {user.address} with event {event.__dict__}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.token, event.nonce, event.amount)]
        sc_args = [
            tokens,
            Address(event.farmContract.address)
        ]
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address),
                                        "claimRewardsProxy", sc_args)
    
    def increase_proxy_lp_token_energy(self, user: Account, proxy: ProxyNetworkProvider, args: list = []):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to increase energy for
            type[int]: lock epochs
        """
        function_purpose = "increase proxy pair token energy"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address), "increaseProxyPairTokenEnergy", args)
    
    def increase_proxy_farm_token_energy(self, user: Account, proxy: ProxyNetworkProvider, args: list = []):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to increase energy for
            type[int]: lock epochs
        """
        function_purpose = "increase proxy farm token energy"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address), "increaseProxyFarmTokenEnergy", args)
    
    def destroy_proxy_farm_token(self, user: Account, proxy: ProxyNetworkProvider, args: list = []):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to destroy
            type[str]: farm address
            type[str]: pair address
            type[int]: first token slippage
            type[int]: second token slippage
            optional type[str]: original caller
        """
        function_purpose = "destroy proxy farm token"
        logger.info(function_purpose)

        if len(args) < 5:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address), "destroyFarmProxy", args)
    
    def merge_proxy_farm_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list = []):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to merge
            type[str]: farm address
        """
        function_purpose = "merge proxy farm tokens"
        logger.info(function_purpose)

        if len(args) < 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address), "mergeWrappedFarmTokens", args)
    
    def merge_proxy_lp_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list = []):
        """Expecting as args:
            type[List[ESDTTokens]]: tokens to merge
        """
        function_purpose = "merge proxy lp tokens"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user, Address(self.address), "mergeWrappedLpTokens", args)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """Expecting as args:
        type[list]: locked asset factories contract addresses; care for the correct order based on locked tokens list
        """
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
                         args: list = [], no_init: bool = False):
        """Expecting as args:
        type[str]: old_locked_token_id
        type[str]: old_factory_address
        """
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
        function_purpose = "Register proxy farm token"
        logger.info(function_purpose)
        tx_hash = ""

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "registerProxyFarm", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def register_proxy_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = "Register proxy lp token"
        logger.info(function_purpose)
        tx_hash = ""

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "registerProxyPair", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    """Expecting as args:
    type[str]: token id
    type[str]: contract address to assign roles to
    """
    def set_local_roles_proxy_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        function_purpose = "Set local roles for proxy token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            3, 4, 5
        ]

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRoles", sc_args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_address: str):
        function_purpose = "Set energy factory address in proxy contract"
        logger.info(function_purpose)

        if energy_address == "":
            log_unexpected_args(function_purpose, energy_address)
            return ""

        gas_limit = 50000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress",
                             [energy_address])

    def add_pair_to_intermediate(self, deployer: Account, proxy: ProxyNetworkProvider, pair_address: str):
        function_purpose = "Add pair to intermediate in proxy contract"
        logger.info(function_purpose)

        if pair_address == "":
            log_unexpected_args(function_purpose, pair_address)
            return ""

        gas_limit = 50000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addPairToIntermediate", [pair_address])

    def set_transfer_role_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        function_purpose = "Set transfer role on address for lp token; legacy endpoint"
        logger.info(function_purpose)

        if address == "":
            log_unexpected_args(function_purpose, address)
            return ""

        gas_limit = 100000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setTransferRoleLockedLpToken", [address])
    
    def set_transfer_role_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        function_purpose = "Set transfer role on address for farm token; legacy endpoint"
        logger.info(function_purpose)

        if address == "":
            log_unexpected_args(function_purpose, address)
            return ""

        gas_limit = 100000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setTransferRoleLockedFarmToken", [address])
    
    def set_transfer_role_wrapped_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        function_purpose = "Set transfer role on address for lp token"
        logger.info(function_purpose)

        if address == "":
            log_unexpected_args(function_purpose, address)
            return ""

        gas_limit = 100000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setTransferRoleWrappedLpToken", [address])
    
    def set_transfer_role_wrapped_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, address: str):
        function_purpose = "Set transfer role on address for farm token"
        logger.info(function_purpose)

        if address == "":
            log_unexpected_args(function_purpose, address)
            return ""

        gas_limit = 100000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setTransferRoleWrappedFarmToken", [address])
    
    def add_farm_to_intermediate(self, deployer: Account, proxy: ProxyNetworkProvider, farm_address: str):
        function_purpose = "Add farm to intermediate in proxy contract"
        logger.info(function_purpose)

        if farm_address == "":
            log_unexpected_args(function_purpose, farm_address)
            return ""

        gas_limit = 50000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addFarmToIntermediate", [farm_address])
    
    def add_contract_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str):
        function_purpose = "Add contract to proxy dex whitelist"
        logger.info(function_purpose)
        
        gas_limit = 30000000
        sc_args = [whitelisted_sc_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addSCAddressToWhitelist", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
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
