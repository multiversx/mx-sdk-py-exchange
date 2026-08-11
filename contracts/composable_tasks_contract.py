from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface, _ConfigField
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass

logger = get_logger(__name__)


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

        function_purpose = "Set wrap egld address"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setWrapEgldAddr", args)

    def set_router_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[str]: router address
        """

        function_purpose = "Set router address"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setRouterAddr", args)

    def set_smart_swap_fee(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[number]: fee percentage
        """

        function_purpose = "Set smart swap fees"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setSmartSwapFeePercentage", args)

    def withdraw_smart_swap_fees(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[string]: tokens identifiers
        """

        function_purpose = "Withdraw smart swap fees"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "withdrawSmartSwapFees", args)
