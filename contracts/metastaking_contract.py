import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface, MetaStakingContractIdentity
from events.metastake_events import (EnterMetastakeEvent,
                                                       ExitMetastakeEvent,
                                                       ClaimRewardsMetastakeEvent)
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning


class MetaStakingContract(DEXContractInterface):
    def __init__(self, staking_token: str, lp_token: str, farm_token: str, stake_token: str,
                 lp_address: str, farm_address: str, stake_address: str,
                 metastake_token: str = "", address: str = ""):
        self.address = address
        self.metastake_token = metastake_token
        self.staking_token = staking_token
        self.lp_token = lp_token
        self.farm_token = farm_token
        self.stake_token = stake_token
        self.lp_address = lp_address
        self.farm_address = farm_address
        self.stake_address = stake_address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "metastake_token": self.metastake_token,
            "staking_token": self.staking_token,
            "lp_token": self.lp_token,
            "farm_token": self.farm_token,
            "stake_token": self.stake_token,
            "lp_address": self.lp_address,
            "farm_address": self.farm_address,
            "stake_address": self.stake_address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return MetaStakingContract(address=config_dict['address'],
                                   metastake_token=config_dict['metastake_token'],
                                   staking_token=config_dict['staking_token'],
                                   lp_token=config_dict['lp_token'],
                                   farm_token=config_dict['farm_token'],
                                   stake_token=config_dict['stake_token'],
                                   lp_address=config_dict['lp_address'],
                                   farm_address=config_dict['farm_address'],
                                   stake_address=config_dict['stake_address'])

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        print_warning("Deploy metastaking contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            "0x" + Address(self.farm_address).hex(),
            "0x" + Address(self.stake_address).hex(),
            "0x" + Address(self.lp_address).hex(),
            "0x" + self.staking_token.encode("ascii").hex(),
            "0x" + self.farm_token.encode("ascii").hex(),
            "0x" + self.stake_token.encode("ascii").hex(),
            "0x" + self.lp_token.encode("ascii").hex(),
        ]
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

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path,
                         args: list = [], no_init: bool = False):
        print_warning("Upgrade metastaking contract")

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
                "0x" + Address(self.farm_address).hex(),
                "0x" + Address(self.stake_address).hex(),
                "0x" + Address(self.lp_address).hex(),
                "0x" + self.staking_token.encode("ascii").hex(),
                "0x" + self.farm_token.encode("ascii").hex(),
                "0x" + self.stake_token.encode("ascii").hex(),
                "0x" + self.lp_token.encode("ascii").hex(),
            ]
        print(f"Arguments: {arguments}")
        contract = SmartContract(bytecode=bytecode, metadata=metadata, address=Address(self.address))
        tx = contract.upgrade(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                              network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            print_transaction_hash(tx_hash, proxy.url, True)

            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send upgrade transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def register_dual_yield_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Register metastaking token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register metastake token. Args not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerDualYieldToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_local_roles_dual_yield_token(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Set local roles for metastake token")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesDualYieldToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed metastaking contract: {self.address}")
        print_test_substep(f"Staking token: {self.staking_token}")
        print_test_substep(f"Stake address: {self.stake_address}")
        print_test_substep(f"Farm address: {self.farm_address}")
        print_test_substep(f"LP address: {self.lp_address}")

    def enter_metastake(self, network_provider: NetworkProviders, user: Account,
                        event: EnterMetastakeEvent, initial: bool = False) -> str:
        print_warning('enterMetastaking')
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)
        metastake_fn = 'stakeFarmTokens'
        gas_limit = 50000000

        sc_args = [
            '0x' + Address(self.address).hex(),  # contract address
            '0x01' if initial else '0x02',  # number of tokens sent
            '0x' + event.metastaking_tk.encode('ascii').hex(),  # farming token
            '0x' + '0' + f'{event.metastaking_tk_nonce:x}' if len(f'{event.metastaking_tk_nonce:x}') % 2 else
            '0x' + f'{event.metastaking_tk_nonce:x}',
            '0x' + '0' + f'{event.metastaking_tk_amount:x}' if len(f'{event.metastaking_tk_amount:x}') % 2 else
            '0x' + f'{event.metastaking_tk_amount:x}'
        ]

        if not initial:
            sc_args.extend([
                '0x' + event.metastake_tk.encode('ascii').hex(),  # farming token
                '0x' + '0' + f'{event.metastake_tk_nonce:x}' if len(f'{event.metastake_tk_nonce:x}') % 2 else
                '0x' + f'{event.metastake_tk_nonce:x}',
                '0x' + '0' + f'{event.metastake_tk_amount:x}' if len(f'{event.metastake_tk_amount:x}') % 2 else
                '0x' + f'{event.metastake_tk_amount:x}'
            ])

        sc_args.extend(['0x' + metastake_fn.encode('ascii').hex()])  # endpoint name
        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = user.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)

        try:
            tx_hash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(tx_hash, network_provider.proxy.url)
            user.nonce += 1
            return tx_hash
        except Exception as ex:
            print(ex)
            return ''

    def exit_metastake(self, network_provider: NetworkProviders, user: Account, event: ExitMetastakeEvent):
        print_warning('exitMetastaking')
        print('Account: ', user.address)

        contract = SmartContract(address=user.address)
        gas_limit = 50000000
        exit_metastake_fn = 'unstakeFarmTokens'

        sc_args = [
            '0x' + self.metastake_token.encode('ascii').hex(),
            '0x' + '0' + f'{event.nonce:x}' if len(f'{event.nonce:x}') % 2 else '0x' + f'{event.nonce:x}',
            '0x' + '0' + f'{event.amount:x}' if len(f'{event.amount:x}') % 2 else '0x' + f'{event.amount:x}',
            '0x' + Address(self.address).hex(),
            '0x' + exit_metastake_fn.encode('ascii').hex(),
            '0x01',  # first token slippage
            '0x01'  # second token slippage
        ]

        tx_data = contract.prepare_execute_transaction_data('ESDTNFTTransfer', sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = user.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)

        try:
            tx_hash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(tx_hash, network_provider.proxy.url)
            user.nonce += 1

            return tx_hash
        except Exception as ex:
            print(ex)
            return ''

    def claim_rewards_metastaking(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsMetastakeEvent):
        print_warning('claimDualYield')
        print('Account: ', user.address)

        contract = SmartContract(address=user.address)
        gas_limit = 50000000
        claim_fn = 'claimDualYield'

        sc_args = [
            "0x" + self.metastake_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + claim_fn.encode('ascii').hex()
        ]

        tx_data = contract.prepare_execute_transaction_data('ESDTNFTTransfer', sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = user.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)

        try:
            tx_hash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(tx_hash, network_provider.proxy.url)
            user.nonce += 1

            return tx_hash
        except Exception as ex:
            print(ex)
            return ''
