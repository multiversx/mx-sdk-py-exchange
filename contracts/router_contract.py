import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface, RouterContractVersion
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, get_deployed_address_from_event
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy


class RouterContract(DEXContractInterface):
    def __init__(self, version: RouterContractVersion, address: str = ""):
        self.address = address
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return RouterContract(address=config_dict['address'],
                              version=RouterContractVersion(config_dict['version']))

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
        type[str]: pair template address
        """
        print_warning("Deploy router contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash, address

        arguments = [
            "0x" + Address(args[0]).hex()
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

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
        type[str]: pair template address
        """
        print_warning("Upgrade router contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        tx_hash = ""

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash

        arguments = [
            "0x" + Address(args[0]).hex()
        ]

        contract = SmartContract(address=Address(self.address), bytecode=bytecode, metadata=metadata)
        tx = contract.upgrade(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                              network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            log_explorer_transaction(tx_hash, proxy.url)
            deployer.nonce += 1 if tx_hash != "" else 0

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def pair_contract_deploy(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Expecting as args:
            type[str]: first pair token
            type[str]: second pair token
            type[str]: address of initial liquidity adder
            type[str]: total fee percentage
            type[str]: special fee percentage
            type[str..]: admin addresses (v2 only)
        """
        print_warning("Deploy pair via router")

        network_config = proxy.get_network_config()
        address, tx_hash = "", ""

        if len(args) < 5:
            print_test_step_fail(f"FAIL: Failed to deploy pair via router. Args list not as expected.")
            return address, tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x" + Address(args[2]).hex(),
            args[3],
            args[4]
        ]

        if self.version == RouterContractVersion.V2:
            sc_args.extend(args[5:])

        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "createPair", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)

        # retrieve deployed contract address
        if tx_hash != "":
            response = proxy.get_transaction(tx_hash, with_results=True)
            address = get_deployed_address_from_event(response)
            deployer.nonce += 1

        return tx_hash, address

    def pair_contract_upgrade(self, deployer: Account, proxy: ElrondProxy, args: list) -> str:
        """ Expected as args:
        type[str]: first token id
        type[str]: second token id
        type[int]: total fee percent
        type[int]: special fee percent
        type[str]: initial liquidity adder (only v1)
        """
        print_warning("Upgrade pair contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) < 4:
            print_test_step_fail(f"FAIL: Failed to issue token. Args list not as expected.")
            return tx_hash

        gas_limit = 200000000
        sc_args = [
            "str:" + args[0],
            "str:" + args[1],
            args[2],
            args[3]
        ]
        if self.version == RouterContractVersion.V1:
            sc_args.insert(2, args[4])

        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "upgradePair", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    """ Expected as args:
    type[str]: pair address
    type[str]: lp token name
    type[str]: lp token ticker
    """
    def issue_lp_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        print_warning("Issue LP token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to issue token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x" + args[2].encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueLpToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_lp_token_local_roles(self, deployer: Account, proxy: ElrondProxy, pair_contract: str):
        print_warning("Set LP token local roles")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + Address(pair_contract).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRoles", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_fee_on(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: pair address to send fees
            type[str]: address to receive fees
            type[str]: expected token
        """
        print_warning("Set fee on for pool")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to add trusted swap pair. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            "0x" + Address(args[1]).hex(),
            "0x" + args[2].encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setFeeOn", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def pair_contract_pause(self, deployer: Account, proxy: ElrondProxy, pair_contract: str):
        print_warning("Pause pair contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = [
            "0x" + Address(pair_contract).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "pause", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def pair_contract_resume(self, deployer: Account, proxy: ElrondProxy, pair_contract: str):
        print_warning("Resume pair contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = [
            "0x" + Address(pair_contract).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "resume", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed router contract: {self.address}")
