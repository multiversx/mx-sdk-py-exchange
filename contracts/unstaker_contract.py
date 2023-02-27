import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, \
    multi_esdt_endpoint_call, endpoint_call
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import CodeMetadata, SmartContract
from erdpy.proxy import ElrondProxy


class UnstakerContract(DEXContractInterface):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return UnstakerContract(address=config_dict['address'])

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
            type[int]: unbond epochs
            type[str]: energy factory address
            type[int]: fees burn percentage
            type[str]: fees collector address
        """
        print_warning("Deploy token unstake contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        if len(args) != 4:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash, address

        arguments = args
        # lock_fee_pairs = list(zip(args[4], args[5]))
        # lock_options = [item for sublist in lock_fee_pairs for item in sublist]
        # arguments.extend(lock_options)  # lock_options
        print(f"Arguments: {arguments}")
        contract = SmartContract(bytecode=bytecode, metadata=metadata)
        tx = contract.deploy(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                             network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            print_transaction_hash(tx_hash, proxy.url, True)

            address = contract.address.bech32()
            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash, address

        return tx_hash, address

    def set_energy_factory_address(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[address]: energy factory address
        """
        function_purpose = "set energy factory address"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in token unstake contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setEnergyFactoryAddress", args)

    def claim_unlocked_tokens(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            empty
        """
        function_purpose = "claim unlocked tokens"
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 20000000, deployer, Address(self.address),
                             "claimUnlockedTokens", [])

    def cancel_unbond(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            empty
        """
        function_purpose = "cancel unbond"
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 20000000, deployer, Address(self.address),
                             "cancelUnbond", args)

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = None):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed token unstake contract: {self.address}")
