from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface
from utils.utils_chain import Account
from utils.logger import get_logger
from utils.utils_tx import deploy
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

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed escrow contract: {self.address}")
