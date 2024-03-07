from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args

logger = get_logger(__name__)


class EscrowContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return EscrowContract(address=config_dict['address'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[str]: energy factory address
            type[str]: locked token ID
            type[int]: minimum locked epochs
            type[int]: epochs cooldown duration
        """
        function_purpose = "Deploy escrow contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 4:
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
    
    def lock_funds(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[address]: destination address
        """
        function_purpose = "lock tokens"
        logger.info(function_purpose)
        if len(args) < 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 60000000,
                                        user, Address(self.address), "lockFunds", args)
    
    def withdraw(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: sender address
        """
        function_purpose = "withdraw tokens"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "withdraw", args)
    
    def cancel_transfer(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: sender address
            type[address]: receiver address
        """
        function_purpose = "cancel transfer"
        logger.info(function_purpose)
        if len(args) < 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, user, Address(self.address), "cancelTransfer", args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed escrow contract: {self.address}")
