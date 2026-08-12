from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.logger import get_logger
from utils.utils_tx import deploy, ESDTToken
from utils.utils_generic import log_step_pass
from utils.utils_chain import Account
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)

# The contract's three endpoints, one declaration each. Wrapping and unwrapping are the two halves
# of the same thing and neither takes an argument list at all: what wrapping sends is EGLD, and what
# unwrapping sends is the wrapped token this contract issued.
#
# `_WRAP_EGLD` names no `value` — the amount is the wrapper's argument, so it rides on
# `_call_endpoint` rather than on the declaration.
#
# ⚠️ `_UNWRAP_EGLD` is handed one `ESDTToken` where every other transfer endpoint in `contracts/` is
# handed a *list* of them. Preserved as it behaves — see docs/CLEANUP.md.
_WRAP_EGLD = _Endpoint("Wrap egld", 10000000, "wrapEgld")
_UNWRAP_EGLD = _Endpoint("unwrap egld", 10000000, "unwrapEgld", transfers=True)
_RESUME = _Endpoint("Resume wrapper contract", 10000000, "unpause")


class EgldWrapContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("wrapped_token"),
    )
    _CONTRACT_TOKENS = ("wrapped_token",)

    def __init__(self, wrapped_token, address: str = ""):
        self.address = address
        self.wrapped_token = wrapped_token

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            self.wrapped_token
        ]
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def wrap_egld(self, user: Account, proxy: ProxyNetworkProvider, amount: int):
        return self._call_endpoint(_WRAP_EGLD, user, proxy, [], value=str(amount))

    def unwrap_egld(self, user: Account, proxy: ProxyNetworkProvider, amount: int):
        """ Expected as args:
            type[ESDTToken]: wrapped token
        """
        return self._call_endpoint(_UNWRAP_EGLD, user, proxy,
                                   [ESDTToken(self.wrapped_token, 0, amount)])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed egld wrapper contract: {self.address}")
