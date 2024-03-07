import sys
import traceback

from contracts.contract_identities import DEXContractInterface
from utils.utils_tx import multi_esdt_endpoint_call, prepare_contract_call_tx, send_contract_call_tx, deploy, upgrade_call, endpoint_call
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, log_explorer_transaction
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider
from utils.logger import get_logger

logger = get_logger(__name__)


class LockedAssetContract(DEXContractInterface):
    def __init__(self, unlocked_asset: str, locked_asset: str = "", address: str = ""):
        self.address = address
        self.unlocked_asset = unlocked_asset
        self.locked_asset = locked_asset

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "unlocked_asset": self.unlocked_asset,
            "locked_asset": self.locked_asset
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return LockedAssetContract(address=config_dict['address'],
                                   unlocked_asset=config_dict['unlocked_asset'],
                                   locked_asset=config_dict['locked_asset'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            self.unlocked_asset,
            bytes.fromhex("000000000000016D11"),
            bytes.fromhex("000000000000018B11"),
            bytes.fromhex("00000000000001A911"),
            bytes.fromhex("00000000000001C711"),
            bytes.fromhex("00000000000001E510"),
            bytes.fromhex("000000000000020310"),
            ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path,
                         args: list = [], no_init: bool = False):
        function_purpose = "Upgrade locked asset contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            arguments = [
                self.unlocked_asset,
                93457,
                101137,
                108817,
                116497,
                124176,
                131856,
            ]

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, arguments)
    
    def unlock_assets(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
        """
        function_purpose = "unlock tokens early"
        logger.info(function_purpose)
        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "unlockAssets", args)

    def set_new_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        function_purpose = "Set new factory address"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setNewFactoryAddress", sc_args)

    def register_locked_asset_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token name
            type[str]: token ticker
        """
        function_purpose = "Register locked asset token"
        logger.info(function_purpose)

        tx_hash = ""

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "registerLockedAssetToken", sc_args, value="50000000000000000")

    def set_locked_asset_local_roles(self, deployer: Account, proxy: ProxyNetworkProvider, contract: str):
        function_purpose = "Set locked asset token local roles"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(contract),
            3, 4, 5,
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "setLocalRolesLockedAssetToken", sc_args)

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = "Whitelist contract in locked asset contract"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(contract_to_whitelist)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "whitelist", sc_args)

    def set_transfer_role_for_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = "Set transfer role for contract"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(contract_to_whitelist)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "setTransferRoleForAddress", sc_args)

    def set_burn_role_for_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = "Set burn role for contract"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(contract_to_whitelist)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "setBurnRoleForAddress", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed locked asset contract: {self.address}")
        log_substep(f"Unlocked token: {self.unlocked_asset}")
        log_substep(f"Locked token: {self.locked_asset}")
