import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import CodeMetadata, SmartContract
from erdpy.proxy import ElrondProxy


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

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        print_warning("Deploy locked asset contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            "0x" + self.unlocked_asset.encode("ascii").hex(),
            "0x000000000000016D11",
            "0x000000000000018B11",
            "0x00000000000001A911",
            "0x00000000000001C711",
            "0x00000000000001E510",
            "0x000000000000020310",
            ]

        contract = SmartContract(bytecode=bytecode, metadata=metadata)
        tx = contract.deploy(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                             network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            log_explorer_transaction(tx_hash, proxy.url)

            address = contract.address.bech32()
            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash, address

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path,
                         args: list = [], no_init: bool = False):
        print_warning("Upgrade locked asset contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            arguments = [
                "0x" + self.unlocked_asset.encode("ascii").hex(),
                "0x000000000000016D11",
                "0x000000000000018B11",
                "0x00000000000001A911",
                "0x00000000000001C711",
                "0x00000000000001E510",
                "0x000000000000020310",
            ]

        contract = SmartContract(bytecode=bytecode, metadata=metadata, address=Address(self.address))
        tx = contract.upgrade(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                              network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            log_explorer_transaction(tx_hash, proxy.url)

            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send upgrade transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def set_new_factory_address(self, deployer: Account, proxy: ElrondProxy, contract_address: str):
        print_warning("Set new factory address")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + Address(contract_address).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setNewFactoryAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def register_locked_asset_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: token name
            type[str]: token ticker
        """
        print_warning("Register locked asset token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register locked token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerLockedAssetToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_locked_asset_local_roles(self, deployer: Account, proxy: ElrondProxy, contract: str):
        print_warning("Set locked asset token local roles")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + Address(contract).hex(),
            "0x03",
            "0x04",
            "0x05",
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesLockedAssetToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def whitelist_contract(self, deployer: Account, proxy: ElrondProxy, contract_to_whitelist: str):
        print_warning("Whitelist contract in locked asset contract")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + Address(contract_to_whitelist).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "whitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_transfer_role_for_contract(self, deployer: Account, proxy: ElrondProxy, contract_to_whitelist: str):
        print_warning("Set transfer role for contract")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + Address(contract_to_whitelist).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setTransferRoleForAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_burn_role_for_contract(self, deployer: Account, proxy: ElrondProxy, contract_to_whitelist: str):
        print_warning("Set burn role for contract")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + Address(contract_to_whitelist).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setBurnRoleForAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed locked asset contract: {self.address}")
        print_test_substep(f"Unlocked token: {self.unlocked_asset}")
        print_test_substep(f"Locked token: {self.locked_asset}")
