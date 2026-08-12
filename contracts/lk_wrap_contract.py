from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
import config

logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# The two transfer endpoints are handed the tokens themselves rather than a list of arguments
# beginning with them, so the build wraps them one level deeper before the dispatcher reads
# `args[0]` as what to move. Their four neighbours take their arguments as they come.
_WRAP_LOCKED_TOKEN = _Endpoint("wrap locked tokens", 10000000, "wrapLockedToken", at_least=1,
                               build=lambda args: [args], transfers=True)
_UNWRAP_LOCKED_TOKEN = _Endpoint("unwrap locked tokens", 10000000, "unwrapLockedToken", at_least=1,
                                 build=lambda args: [args], transfers=True)
_SET_TRANSFER_ROLE_WRAPPED_TOKEN = _Endpoint("set transfer role locked token", 100000000,
                                             "setTransferRoleWrappedToken", at_least=1)
_UNSET_TRANSFER_ROLE_WRAPPED_TOKEN = _Endpoint("unset transfer role locked token", 100000000,
                                               "unsetTransferRoleWrappedToken", at_least=1)
_ISSUE_WRAPPED_TOKEN = _Endpoint("Issue wrapped token", 100000000, "issueWrappedToken", exactly=2,
                                 build=lambda args: [*args, 18],
                                 value=config.DEFAULT_ISSUE_TOKEN_PRICE)


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
        return self._call_endpoint(_WRAP_LOCKED_TOKEN, user, proxy, args)

    def unwrap_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[ESDTToken]: tokens
        """
        return self._call_endpoint(_UNWRAP_LOCKED_TOKEN, user, proxy, args)

    def set_transfer_role_wrapped_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address...]: addresses
        """
        return self._call_endpoint(_SET_TRANSFER_ROLE_WRAPPED_TOKEN, user, proxy, args)

    def unset_transfer_role_wrapped_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: address
        """
        return self._call_endpoint(_UNSET_TRANSFER_ROLE_WRAPPED_TOKEN, user, proxy, args)

    def issue_wrapped_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_ISSUE_WRAPPED_TOKEN, deployer, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed locked token wrapping contract: {self.address}")
