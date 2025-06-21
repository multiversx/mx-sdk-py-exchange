import config
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider, TransactionComputer
from typing import List, Dict, Any
from multiversx_sdk.abi import Abi

logger = get_logger(__name__)
transaction_computer = TransactionComputer()


class MEXGovernanceContract(DEXContractInterface):
    def __init__(self, reference_emission_rate: int = 0 ,incentive_token: str = "", address: str = ""):
        self.address = address
        self.incentive_token = incentive_token
        self.reference_emission_rate = reference_emission_rate

    def get_config_dict(self) -> dict:
        output_dict = {
            "reference_emission_rate": self.reference_emission_rate,
            "incentive_token": self.incentive_token,
            "address": self.address

        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return MEXGovernanceContract(emission_rate=config_dict['reference_emission_rate'],
                                  incentive_token=config_dict['incentive_token'],
                                  address=config_dict['address']
                                  )
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """ Expected as args:
            type[int]: reference_emission_rate
            # type[str]: incentive_token
            type[str]: energy_factory_address
        """
        function_purpose = f"Deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        metadata = CodeMetadata(upgradeable=True, payable=False, payable_by_contract=False, readable=True)
        gas_limit = 100000000
        sc_args = [
            args[0], 
            args[1], 
            Address(args[2])
                   ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, sc_args)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = [],
                         no_init: bool = False):
        """ Expected as args:
            type[int]: reference_emission_rate
            type[int]: incentive_token
            type[int]: energy_factory_address
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable=False, payable_by_contract=False, readable=True)
        gas_limit = 100000000
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            if len(args) != 3:
                log_unexpected_args(function_purpose, args)
                return tx_hash

            sc_args = [
                args[0], 
                args[1], 
                Address(args[2])
                   ]


        logger.debug(f"Arguments: {arguments}")

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, sc_args)
        return tx_hash

    def vote(self, deployer: Account, proxy: ProxyNetworkProvider, abi: Abi, args: list):

        function_purpose = f"Vote proposal"
        logger.info(function_purpose)

        gas_limit = 20000000
        sc_args = args
    
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "vote", sc_args, abi =  abi)
        
    def blacklist_farm(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[Address]: list of farms
        """
        function_purpose = f"Blacklist farm"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "blacklistFarm", sc_args)
    
    def remove_blacklist_farm(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[Address]: list of farms
        """

        function_purpose = f"Remove farms from blacklist"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeBlacklistFarm", sc_args)
    
    def set_reference_emission_rate(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: reference_emission_rate
        """
        function_purpose = f"Set reference emission rate"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setReferenceEmissionRate", sc_args)
    
    def set_incentive_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: incentive_token
        """
        function_purpose = f"Set incentive token"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setIncentiveToken", sc_args)
    
    def set_farm_emissions(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        function_purpose = f"Set farm emissions"
        logger.info(function_purpose)
        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setFarmEmissions", sc_args)
    
    def incentivize_farm(self, deployer: Account, proxy: ProxyNetworkProvider, abi: Abi, args: list):
        """ Expected as args:
            type[Address]: farm address
            type[int]: amount
            type[int]: week
        """
        function_purpose = f"Set incentive farm"
        logger.info(function_purpose)
        gas_limit = 10000000
        sc_args = args
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, deployer, Address(self.address), "incentivizeFarm", sc_args, abi = abi)
    
    def claim_incentive(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: week
        """
        function_purpose = f"Claim incentive"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "claimIncentive", sc_args)
    
    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: energy_factory_address
        """
        function_purpose = f"Set energy factory address"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress", sc_args)
    

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed mex governance contract: {self.address}")