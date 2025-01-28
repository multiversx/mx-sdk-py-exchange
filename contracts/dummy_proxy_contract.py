from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, ESDTToken, multi_esdt_endpoint_call
from utils.utils_generic import log_step_pass
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class DummyProxyContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return DummyProxyContract(address=config_dict['address'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        return DummyProxyContract(address=address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True, payable=True)
        gas_limit = 50000000

        arguments = []
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def call_endpoint(self, user: Account, proxy: ProxyNetworkProvider, amount: int, args: list = None):
        """ Expected as args:
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        function_purpose = f"Call endpoint"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "callEndpoint", sc_args, value=str(amount))

    def call_internal_transfer_endpoint(self, user: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[str]: token id
        type[int]: nonce
        type[int]: amount
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        function_purpose = f"Call internal transfer endpoint"
        logger.info(function_purpose)

        gas_limit = 100000000
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "callInternalTransferEndpoint", args)
    
    def call_transfer_endpoint(self, user: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
        type[list[ESDTToken]]: tokens list
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        function_purpose = f"Call transfer endpoint"
        logger.info(function_purpose)

        gas_limit = 100000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user,
                                        Address(self.address), "callTransferEndpoint", args)


    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed dummy proxy contract: {self.address}")
