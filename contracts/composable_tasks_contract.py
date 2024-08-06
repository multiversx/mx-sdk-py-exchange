from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass

logger = get_logger(__name__)


class ComposableTasksContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return ComposableTasksContract(address=config_dict['address'])

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """Expecting as args:
        """
        function_purpose = "Deploy escrow contract"
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
        log_step_pass(f"Deployed escrow contract: {self.address}")

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

    def set_pair_address_for_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            Type[str]: first token id
            Type[str]: second token id
            Type[str]: pair address
        """

        function_purpose = "Set pair address for tokens"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setPairAddrForTokens", args)

