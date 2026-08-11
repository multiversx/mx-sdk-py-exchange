from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface, _ConfigField
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
import config

logger = get_logger(__name__)


class LkWrapContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        # ⚠️ `attr` names an attribute nothing assigns, so `get_config_dict` raises
        # `AttributeError` for every LkWrapContract and the `lk_wraps` group cannot be saved at
        # all. Preserved exactly as it behaves today — see docs/CLEANUP.md.
        _ConfigField("wrapped_token", attr="wrap_lk_token"),
    )
    _CONTRACT_TOKENS = ("wrapped_token",)

    def __init__(self, address: str = "", wrapped_token: str = ""):
        self.address = address
        self.wrapped_token = wrapped_token

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[str]: energy factory address
        """
        function_purpose = "Deploy lk token wrapping contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = args
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address
    
    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None,
                         no_init: bool = False):
        """ Expected as args: []
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)
        return tx_hash
    
    def wrap_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[ESDTToken]: tokens
        """
        function_purpose = "wrap locked tokens"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "wrapLockedToken", [args])
    
    def unwrap_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[ESDTToken]: tokens
        """
        function_purpose = "unwrap locked tokens"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "unwrapLockedToken", [args])

    
    def set_transfer_role_wrapped_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address...]: addresses
        """
        function_purpose = "set transfer role locked token"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 100000000, user, Address(self.address), "setTransferRoleWrappedToken", args)
    
    def unset_transfer_role_wrapped_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: address
        """
        function_purpose = "unset transfer role locked token"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 100000000, user, Address(self.address), "unsetTransferRoleWrappedToken", args)
    
    def issue_wrapped_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Issue wrapped token"
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
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueWrappedToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed locked token wrapping contract: {self.address}")
