import sys
import traceback

import config
from contracts.contract_identities import (DEXContractInterface, _as_addresses, _ConfigField,
                                           _Endpoint)
from utils.contract_data_fetchers import LockedAssetContractDataFetcher
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, deploy, upgrade_call
from utils.utils_generic import log_step_fail, log_step_pass, log_substep
from utils.utils_chain import Account, WrapperAddress as Address, hex_to_string, log_explorer_transaction
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from utils.logger import get_logger

logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# Every one of the five address-taking endpoints here converts its argument, which makes this the
# only contract in the toolkit that agrees with itself about that.
_UNLOCK_ASSETS = _Endpoint("unlock tokens", 30000000, "unlockAssets", exactly=1, transfers=True)
_SET_NEW_FACTORY_ADDRESS = _Endpoint("Set new factory address", 50000000, "setNewFactoryAddress",
                                     build=_as_addresses)
_REGISTER_LOCKED_ASSET_TOKEN = _Endpoint("Register locked asset token", 100000000,
                                         "registerLockedAssetToken", exactly=2,
                                         build=lambda args: [*args, 18],
                                         value="50000000000000000")
# The three role numbers are the local roles themselves — mint, burn and NFT-create — and no caller
# passes them, so this is the only set of roles the token can be given.
_SET_LOCAL_ROLES_LOCKED_ASSET_TOKEN = _Endpoint("Set locked asset token local roles", 100000000,
                                                "setLocalRolesLockedAssetToken",
                                                build=lambda args: [*_as_addresses(args), 3, 4, 5])
_WHITELIST = _Endpoint("Whitelist contract in locked asset contract", 100000000, "whitelist",
                       build=_as_addresses)
_SET_TRANSFER_ROLE_FOR_ADDRESS = _Endpoint("Set transfer role for contract", 100000000,
                                           "setTransferRoleForAddress", build=_as_addresses)
_SET_BURN_ROLE_FOR_ADDRESS = _Endpoint("Set burn role for contract", 100000000,
                                       "setBurnRoleForAddress", build=_as_addresses)


class LockedAssetContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("unlocked_asset"),
        _ConfigField("locked_asset"),
    )
    _CONTRACT_TOKENS = ("locked_asset",)

    def __init__(self, unlocked_asset: str, locked_asset: str = "", address: str = ""):
        self.address = address
        self.unlocked_asset = unlocked_asset
        self.locked_asset = locked_asset

    @classmethod
    def load_contract_by_address(cls, address: str):
        data_fetcher = LockedAssetContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        base_token = hex_to_string(data_fetcher.get_data("getAssetTokenId"))
        locked_token = hex_to_string(data_fetcher.get_data("getLockedAssetTokenId"))

        return LockedAssetContract(base_token, locked_token, address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list | None = None):
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
                         args: list | None = None, no_init: bool = False):
        function_purpose = "Upgrade locked asset contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

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
        return self._call_endpoint(_UNLOCK_ASSETS, user, proxy, args)

    def set_new_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        return self._call_endpoint(_SET_NEW_FACTORY_ADDRESS, deployer, proxy, [contract_address])

    def register_locked_asset_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token name
            type[str]: token ticker
        """
        return self._call_endpoint(_REGISTER_LOCKED_ASSET_TOKEN, deployer, proxy, args)

    def set_locked_asset_local_roles(self, deployer: Account, proxy: ProxyNetworkProvider, contract: str):
        return self._call_endpoint(_SET_LOCAL_ROLES_LOCKED_ASSET_TOKEN, deployer, proxy, [contract])

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_WHITELIST, deployer, proxy, [contract_to_whitelist])

    def set_transfer_role_for_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_SET_TRANSFER_ROLE_FOR_ADDRESS, deployer, proxy,
                                   [contract_to_whitelist])

    def set_burn_role_for_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_SET_BURN_ROLE_FOR_ADDRESS, deployer, proxy,
                                   [contract_to_whitelist])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed locked asset contract: {self.address}")
        log_substep(f"Unlocked token: {self.unlocked_asset}")
        log_substep(f"Locked token: {self.locked_asset}")
