from contracts.base_contracts import BaseBoostedContract
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class FeesCollectorContract(BaseBoostedContract):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return FeesCollectorContract(address=config_dict['address'])

    @classmethod
    def load_contract_by_address(cls, address: str):
        return FeesCollectorContract(address=address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
            type[str]: locked token
            type[str]: energy factory address
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            args[0],
            Address(args[1])
        ]
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address
    
    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None,
                         no_init: bool = False):
        """ Expected as args:
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            # implement below in case of upgrade args needed
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)

        return tx_hash

    def add_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Add known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownContracts", sc_args)

    def add_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Add known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownTokens", args)

    def remove_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Remove known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownContracts", sc_args)

    def remove_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Remove known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownTokens", sc_args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, factory_address: str):
        """ Expected as args:
                    type[str]: energy factory address
        """
        function_purpose = f"Set Energy factory address in fees collector contract"
        logger.info(function_purpose)

        if not factory_address:
            log_unexpected_args(function_purpose, factory_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(factory_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress", sc_args)

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """ Expected as args:
            type[str]: locking address
        """
        function_purpose = f"Set locking address in fees collector"
        logger.info(function_purpose)

        if not locking_address:
            log_unexpected_args(function_purpose, locking_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(locking_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingScAddress", sc_args)

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        function_purpose = f"Set lock epochs in fees collector"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            lock_epochs
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockEpochs", sc_args)

    def set_locked_tokens_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, locked_tokens_per_block: int):
        function_purpose = f"Set locked tokens per block"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            locked_tokens_per_block
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockedTokensPerBlock", sc_args)

    def claim_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimRewards", sc_args)
    
    def claim_boosted_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimBoostedRewards", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed fees collector contract: {self.address}")
