import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx
from utils.utils_chain import print_warning, print_transaction_hash, print_test_step_fail, \
    print_test_step_pass, print_test_substep
from erdpy.accounts import Account, Address
from erdpy.contracts import CodeMetadata, SmartContract
from erdpy.proxy import ElrondProxy


class SimpleLockContract(DEXContractInterface):
    def __init__(self, locked_token: str = "", lp_proxy_token: str = "", address: str = ""):
        self.address = address
        self.locked_token = locked_token
        self.lp_proxy_token = lp_proxy_token

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "locked_token": self.locked_token,
            "lp_proxy_token": self.lp_proxy_token
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return SimpleLockContract(address=config_dict['address'],
                                  locked_token=config_dict['locked_token'],
                                  lp_proxy_token=config_dict['lp_proxy_token'])

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        print_warning("Deploy simple lock contract")

        metadata = CodeMetadata(upgradeable=True, payable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = []

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

    def issue_locked_lp_token(self, deployer: Account, proxy: ElrondProxy, locked_lp_token: str):
        print_warning("Issue locked LP token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueLpProxyToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def issue_locked_token(self, deployer: Account, proxy: ElrondProxy, locked_token: str):
        print_warning("Issue locked token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + locked_token.encode("ascii").hex(),
            "0x" + locked_token.encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueLockedToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_local_roles_locked_token(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Set local roles locked token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesLockedToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_local_roles_locked_lp_token(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Set local roles locked lp token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesLpProxyToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    """ Expected as args:
        type[str]: pair address
        type[str]: first token identifier
        type[str]: second token identifier
        """

    def add_lp_to_whitelist(self, deployer: Account, proxy: ElrondProxy, args: list):
        print_warning("Add LP to Whitelist in simple lock contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to whitelist lp in simple lock contract. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x" + args[2].encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addLpToWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed simple lock contract: {self.address}")
        print_test_substep(f"Locked token: {self.locked_token}")
        print_test_substep(f"Locked LP token: {self.lp_proxy_token}")
