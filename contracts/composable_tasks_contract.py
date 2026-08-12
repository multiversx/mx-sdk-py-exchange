from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass

logger = get_logger(__name__)

# The contract's four endpoints, one declaration each: the same 10M gas, no argument check on any of
# them, and every argument sent as it arrived — the two collaborator addresses included, which makes
# this contract one of the ones that does not convert.
_SET_WRAP_EGLD_ADDR = _Endpoint("Set wrap egld address", 10000000, "setWrapEgldAddr")
_SET_ROUTER_ADDR = _Endpoint("Set router address", 10000000, "setRouterAddr")
_SET_SMART_SWAP_FEE_PERCENTAGE = _Endpoint("Set smart swap fees", 10000000,
                                           "setSmartSwapFeePercentage")
_WITHDRAW_SMART_SWAP_FEES = _Endpoint("Withdraw smart swap fees", 10000000,
                                      "withdrawSmartSwapFees")


class ComposableTasksContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """Expecting as args:
        """
        function_purpose = "Deploy composable tasks contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, [])
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path):
        """Expecting as args:
        """
        function_purpose = f"Upgrade composable tasks contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)

        gas_limit = 200000000

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, [])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed composable tasks contract: {self.address}")

    def set_wrap_egld_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[str]: wrap egld address
        """
        return self._call_endpoint(_SET_WRAP_EGLD_ADDR, deployer, proxy, args)

    def set_router_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[str]: router address
        """
        return self._call_endpoint(_SET_ROUTER_ADDR, deployer, proxy, args)

    def set_smart_swap_fee(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[number]: fee percentage
        """
        return self._call_endpoint(_SET_SMART_SWAP_FEE_PERCENTAGE, deployer, proxy, args)

    def withdraw_smart_swap_fees(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[string]: tokens identifiers
        """
        return self._call_endpoint(_WITHDRAW_SMART_SWAP_FEES, deployer, proxy, args)
