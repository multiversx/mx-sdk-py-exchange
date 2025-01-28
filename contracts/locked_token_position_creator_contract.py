"""
LockedTokenPositionCreatorContract module
"""

from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_substep
from utils.utils_chain import Account, WrapperAddress as Address


logger = get_logger(__name__)


class LockedTokenPositionCreatorContract(DEXContractInterface):
    """
        LockedTokenPositionCreatorContract class
    """

    def __init__(
        self,
        address: str = "",
        energy_factory_adddress: str = "",
        egld_wrapper_address: str = "",
        mex_wegld_lp_pair_address: str = "",
        mex_wegld_lp_farm_address: str = "",
        proxy_dex_address: str = "",
        router_address: str = ""
    ):
        self.address = address
        self.energy_factory_adddress = energy_factory_adddress
        self.egld_wrapper_address = egld_wrapper_address
        self.mex_wegld_lp_pair_address = mex_wegld_lp_pair_address
        self.mex_wegld_lp_farm_address = mex_wegld_lp_farm_address
        self.proxy_dex_address = proxy_dex_address
        self.router_address = router_address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return LockedTokenPositionCreatorContract(address=config_dict['address'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(
            self,
            deployer: Account,
            proxy: ProxyNetworkProvider,
            bytecode_path,
            args: list
    ):
        """
            Expecting as args:
                type[str]: energy factory address
                type[str]: egld wrapper address
                type[str]: mex-wegld lp pair address
                type[str]: mex-wegld lp farm address
                type[str]: proxy dex address
                type[str]: router address
        """
        function_purpose = f"Deploy {type(self).__name__} contract"
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
            args
        )

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path):
        """
            Expecting as args:
        """

        function_purpose = f"Upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True)
        gas_limit = 200000000

        tx_hash = upgrade_call(
            type(self).__name__,
            proxy,
            gas_limit,
            deployer,
            Address(self.address),
            bytecode_path,
            metadata,
            []
        )

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed locked token position creator contract: {self.address}")
        log_substep(f"Energy Factory address: {self.energy_factory_adddress}")
        log_substep(f"EGLD Wrapper address: {self.egld_wrapper_address}")
        log_substep(f"Mex-Wegld LP Pair address: {self.mex_wegld_lp_pair_address}")
        log_substep(f"Mex-Wegld LP Farm address: {self.mex_wegld_lp_farm_address}")
        log_substep(f"Proxy Dex address: {self.proxy_dex_address}")
        log_substep(f"Router address: {self.router_address}")
