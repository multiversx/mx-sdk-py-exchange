import sys
import traceback

from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, get_deployed_address_from_event, deploy, \
    endpoint_call, get_deployed_address_from_tx
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_warning, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider


logger = get_logger(__name__)


class ProxyDeployerContract(DEXContractInterface):
    def __init__(self, template_name: str, address: str = ""):
        """
        template_name: should be one of the defined names in config
        """
        self.address = address
        self.template = template_name

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "template": self.template
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return ProxyDeployerContract(address=config_dict['address'],
                                     template_name=config_dict['template'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        type[str]: template sc address
        """
        function_purpose = f"Deploy proxy deployer contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = [
            Address(args[0])
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def farm_contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: reward token id
            type[str]: farming token id
            type[str]: pair contract address
        """
        function_purpose = f"Deploy farm via router"
        logger.info(function_purpose)

        address, tx_hash = "", ""

        if len(args) < 3:
            log_unexpected_args(function_purpose, args)
            return address, tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            Address(args[2])
        ]

        tx_hash = endpoint_call(proxy, gas_limit, deployer, Address(self.address), "deployFarm", sc_args)

        # retrieve deployed contract address
        if tx_hash != "":
            address = get_deployed_address_from_tx(tx_hash, proxy)

        return tx_hash, address

    def call_farm_endpoint(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
        type[str]: farm address
        type[str]: farm endpoint
        type[list]: farm endpoint args
        """
        function_purpose = f"Call farm endpoint via proxy deployer"
        logger.info(function_purpose)

        tx_hash = ""

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        logger.debug(f"Calling remote farm endpoint: {args[1]}")

        gas_limit = 20000000
        sc_args = [
            Address(args[0]),
            args[1],
        ]
        if type(args[2]) != list:
            endpoint_args = [args[2]]
        else:
            endpoint_args = args[2]
        sc_args.extend(endpoint_args)

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "callFarmEndpoint", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed proxy deployer contract: {self.address}")
