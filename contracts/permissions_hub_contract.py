from contracts.contract_identities import DEXContractInterface
from utils.contract_data_fetchers import PermissionsHubContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import endpoint_call, deploy
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import log_step_fail, log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class PermissionsHubContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return PermissionsHubContract(address=config_dict['address'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        return PermissionsHubContract(address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        """
        function_purpose = f"Deploy permissions hub contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = args
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def add_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - whitelisted_sc_addresses: list[address]
        """
        function_purpose = "Add addresses to whitelist"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        
        gas_limit = 30000000
        sc_args = args
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "whitelist", sc_args)
    
    def remove_from_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - whitelisted_sc_addresses: list[address]
        """
        function_purpose = "Remove addresses to whitelist"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        
        gas_limit = 30000000
        sc_args = args
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeWhitelist", sc_args)
    
    def add_to_blacklist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - blacklisted_sc_addresses: list[address]
        """
        function_purpose = "Add addresses to blacklist"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        
        gas_limit = 30000000
        sc_args = args
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "blacklist", sc_args)
    
    def remove_from_blacklist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - blacklisted_sc_addresses: list[address]
        """
        function_purpose = "Remove addresses from blacklist"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        
        gas_limit = 30000000
        sc_args = args
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeBlacklist", sc_args)
    
    def is_whitelisted(self, user: str, address: str, proxy: ProxyNetworkProvider) -> bool:
        data_fetcher = PermissionsHubContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('isWhitelisted', 
                                            [
                                                Address(address).get_public_key(),
                                                Address(user).get_public_key()
                                            ])
        if not raw_results:
            return False
        return bool(raw_results)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed permissions hub contract: {self.address}")
