import config
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class SimpleLockContract(DEXContractInterface):
    def __init__(self, locked_token: str = "", lp_proxy_token: str = "", farm_proxy_token: str = "", address: str = ""):
        self.address = address
        self.locked_token = locked_token
        self.lp_proxy_token = lp_proxy_token
        self.farm_proxy_token = farm_proxy_token

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "locked_token": self.locked_token,
            "lp_proxy_token": self.lp_proxy_token,
            "farm_proxy_token": self.farm_proxy_token
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return SimpleLockContract(address=config_dict['address'],
                                  locked_token=config_dict['locked_token'],
                                  lp_proxy_token=config_dict['lp_proxy_token'],
                                  farm_proxy_token=config_dict.get('farm_proxy_token'))

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        function_purpose = f"Deploy simple lock contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable=True)
        gas_limit = 200000000

        arguments = []

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def issue_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Issue locked LP token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueLpProxyToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def issue_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Issue locked farm token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueFarmProxyToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def issue_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Issue locked token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueLockedToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def set_local_roles_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Set local roles locked token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRolesLockedToken", sc_args)

    def set_local_roles_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Set local roles locked lp token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRolesLpProxyToken", sc_args)

    def add_lp_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address
            type[str]: first token identifier
            type[str]: second token identifier
        """
        function_purpose = f"Add LP to Whitelist in simple lock contract"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            Address(args[0]),
            args[1],
            args[2]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addLpToWhitelist", sc_args)

    def add_farm_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: farm address
            type[str]: farming token identifier
            type[str]: farm type: 0 - simple, 1 - locked, 2 - boosted
        """
        function_purpose = f"Add Farm to Whitelist in simple lock contract"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            Address(args[0]),
            args[1],
            args[2]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addFarmToWhitelist", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed simple lock contract: {self.address}")
        log_substep(f"Locked token: {self.locked_token}")
        log_substep(f"Locked LP token: {self.lp_proxy_token}")
