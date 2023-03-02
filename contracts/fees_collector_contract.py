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


class FeesCollectorContract(DEXContractInterface):
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

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = None):
        """ Expected as args:
            type[str]: locked token
            type[str]: energy factory address
        """
        print_warning("Deploy fees collector contract")

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to deploy. Args list not as expected.")
            return ""

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            f"str:{args[0]}",
            args[1]
        ]
        print(f"Arguments: {arguments}")
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

    def add_known_contracts(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        print_warning("Add known contract in fees collector contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to add know contracts. Args list not as expected.")
            return tx_hash

        gas_limit = 10000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addKnownContracts", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_known_tokens(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        print_warning("Add known tokens in fees collector contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to add know tokens. Args list not as expected.")
            return tx_hash

        gas_limit = 10000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addKnownTokens", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def remove_known_contracts(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        print_warning("Remove known contract in fees collector contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to remove know contracts. Args list not as expected.")
            return tx_hash

        gas_limit = 10000000
        sc_args = args
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "removeKnownContracts", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def remove_known_tokens(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        print_warning("Remove known tokens in fees collector contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to remove know tokens. Args list not as expected.")
            return tx_hash

        gas_limit = 10000000
        sc_args = args
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "removeKnownTokens", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_energy_factory_address(self, deployer: Account, proxy: ElrondProxy, factory_address: str):
        """ Expected as args:
                    type[str]: energy factory address
        """
        print_warning("Set Energy factory address in fees collector contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if not factory_address:
            print_test_step_fail(f"FAIL: Failed to set Energy factory address. Arg not as expected.")
            return tx_hash

        gas_limit = 30000000
        sc_args = [
            "0x" + Address(factory_address).hex()
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setEnergyFactoryAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_locking_address(self, deployer: Account, proxy: ElrondProxy, locking_address: str):
        """ Expected as args:
            type[str]: locking address
        """
        print_warning("Set locking address in fees collector")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if not locking_address:
            print_test_step_fail(f"FAIL: Failed to set set locking address. Arg not as expected.")
            return tx_hash

        gas_limit = 30000000
        sc_args = [
            "0x" + Address(locking_address).hex()
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockingScAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_lock_epochs(self, deployer: Account, proxy: ElrondProxy, lock_epochs: int):
        print_warning("Set lock epochs in fees collector")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 30000000
        sc_args = [
            lock_epochs
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockEpochs", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_locked_tokens_per_block(self, deployer: Account, proxy: ElrondProxy, locked_tokens_per_block: int):
        print_warning("Set locked tokens per block")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 30000000
        sc_args = [
            locked_tokens_per_block
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockedTokensPerBlock", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def claim_rewards(self, user: Account, proxy: ElrondProxy):
        print_warning("Claim rewards from fees collector")

        network_config = proxy.get_network_config()

        gas_limit = 20000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), user, network_config, gas_limit,
                                      "claimRewards", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        user.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = None):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed fees collector contract: {self.address}")
