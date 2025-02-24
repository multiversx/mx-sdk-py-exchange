import sys
import traceback

from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import endpoint_call, deploy
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import log_step_fail, log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class UnstakerContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return UnstakerContract(address=config_dict['address'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        return UnstakerContract(address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[int]: unbond epochs
            type[str]: energy factory address
            type[int]: fees burn percentage
            type[str]: fees collector address
        """
        function_purpose = f"Deploy token unstake contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 4:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = args
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: energy factory address
        """
        function_purpose = "set energy factory address"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setEnergyFactoryAddress", args)

    def claim_unlocked_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
            empty
        """
        function_purpose = "claim unlocked tokens"
        logger.info(function_purpose)
        return endpoint_call(proxy, 20000000, deployer, Address(self.address), "claimUnlockedTokens", [])

    def cancel_unbond(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
            empty
        """
        function_purpose = "cancel unbond"
        logger.info(function_purpose)
        return endpoint_call(proxy, 20000000, deployer, Address(self.address), "cancelUnbond", args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed token unstake contract: {self.address}")
