from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, ESDTToken, multi_esdt_endpoint_call
from utils.utils_generic import log_step_pass
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class EgldWrapContract(DEXContractInterface):
    def __init__(self, wrapped_token, address: str = ""):
        self.address = address
        self.wrapped_token = wrapped_token

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "wrapped_token": self.wrapped_token
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return EgldWrapContract(address=config_dict['address'],
                                wrapped_token=config_dict['wrapped_token'])

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
        function_purpose = f"Wrap egld"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "wrapEgld", sc_args, value=str(amount))

    def unwrap_egld(self, user: Account, proxy: ProxyNetworkProvider, amount: int):
        """ Expected as args:
            type[ESDTToken]: wrapped token
        """
        function_purpose = f"unwrap egld"
        logger.info(function_purpose)

        gas_limit = 10000000
        args = [
            ESDTToken(self.wrapped_token, 0, amount)
        ]
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user,
                                        Address(self.address), "unwrapEgld", args)
    
    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Resume wrapper contract"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "unpause", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed egld wrapper contract: {self.address}")
