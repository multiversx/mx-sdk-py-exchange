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


class ProxyDeployerContract(DEXContractInterface):
    def __init__(self, template_name: str, address: str = ""):
        """
        template_name: should be one of the defined names in config
        """
        self.address = address
        self.template = template_name

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "template": self.template
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return ProxyDeployerContract(address=config_dict['address'],
                                     template_name=config_dict['template'])

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
        type[str]: template sc address
        """
        print_warning("Deploy proxy deployer contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
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

    def farm_contract_deploy(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Expecting as args:
            type[str]: reward token id
            type[str]: farming token id
            type[str]: pair contract address
        """
        print_warning("Deploy farm via router")

        network_config = proxy.get_network_config()
        address, tx_hash = "", ""

        if len(args) < 3:
            print_test_step_fail(f"FAIL: Failed to deploy farm via proxy deployer. Args list not as expected.")
            return address, tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x" + Address(args[2]).hex()
        ]

        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "deployFarm", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)

        # retrieve deployed contract address
        if tx_hash != "":
            response = proxy.get_transaction(tx_hash, with_results=True)
            address = get_deployed_address_from_event(response)
            deployer.nonce += 1

        return tx_hash, address

    def call_farm_endpoint(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
        type[str]: farm address
        type[str]: farm endpoint
        type[list]: farm endpoint args
        """
        print_warning("Call farm endpoint via proxy deployer")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to call farm endpoint. Args list not as expected.")
            return tx_hash

        print_warning(f"Calling: {args[1]}")

        gas_limit = 20000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            "str:" + args[1],
        ]
        if type(args[2] != list):
            endpoint_args = [args[2]]
        else:
            endpoint_args = args[2]
        sc_args.extend(endpoint_args)

        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "callFarmEndpoint", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed proxy deployer contract: {self.address}")
