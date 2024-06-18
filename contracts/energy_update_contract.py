"""
EnergyUpdateContract module
"""

from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy
from utils.utils_generic import log_step_pass
from utils.utils_chain import Account


logger = get_logger(__name__)


class EnergyUpdateContract(DEXContractInterface):
    """
        EnergyUpdateContract class
    """

    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return EnergyUpdateContract(address=config_dict['address'])

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(
            self,
            deployer: Account,
            proxy: ProxyNetworkProvider,
            bytecode_path,
            args: list = None
    ):
        """
            Expected as args:
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        tx_hash, address = deploy(
            type(self).__name__,
            proxy,
            gas_limit,
            deployer,
            bytecode_path,
            metadata,
            []
        )

        return tx_hash, address

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed energy update contract: {self.address}")
