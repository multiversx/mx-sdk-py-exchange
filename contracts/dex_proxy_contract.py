import config
from contracts.contract_identities import DEXContractInterface, ProxyContractVersion
from contracts.farm_contract import FarmContract
from contracts.pair_contract import PairContract
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, \
    endpoint_call, multi_esdt_endpoint_call, ESDTToken
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, \
    log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_core import CodeMetadata

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
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


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
            Address(event.farmContract.address),
            event.amount
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

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, args)

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path,
                         args: list = [], no_init: bool = False):
        """Expecting as args:
        type[list]: locked asset factories contract addresses; care for the correct order based on locked tokens list
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 1 and not no_init:
            log_unexpected_args(function_purpose, args)
            return "", ""

        if not no_init and len(self.locked_tokens) != len(args[0]):
            log_step_fail(f"FAIL: Failed to upgrade contract. "
                                 f"Mismatch between locked tokens and factory addresses.")
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 300000000

        if no_init:
            arguments = []
        else:
            arguments = [self.token]
            locked_tokens_args = list(sum(zip(self.locked_tokens, args[0]), ()))
            arguments.extend(locked_tokens_args)

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
            "18"
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
            "18"
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

    def add_farm_to_intermediate(self, deployer: Account, proxy: ProxyNetworkProvider, farm_address: str):
        function_purpose = "Add farm to intermediate in proxy contract"
        logger.info(function_purpose)

        if farm_address == "":
            log_unexpected_args(function_purpose, farm_address)
            return ""

        gas_limit = 50000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addFarmToIntermediate", [farm_address])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed proxy contract: {self.address}")
        log_substep(f"Token: {self.token}")
        log_substep(f"Locked tokens: {self.locked_tokens}")
        log_substep(f"Proxy LP token: {self.proxy_lp_token}")
        log_substep(f"Proxy Farm token: {self.proxy_farm_token}")
