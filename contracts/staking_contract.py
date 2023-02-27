import sys
import time
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface, StakingContractIdentity, \
    StakingContractVersion
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import get_continue_confirmation, print_test_step_fail, print_test_step_pass, \
    print_test_substep, print_warning
from events.farm_events import (EnterFarmEvent, ExitFarmEvent,
                                                  ClaimRewardsFarmEvent, CompoundRewardsFarmEvent,
                                                  MigratePositionFarmEvent)


class StakingContract(DEXContractInterface):
    def __init__(self, farming_token: str, max_apr: int, rewards_per_block: int, unbond_epochs: int,
                 version: StakingContractVersion, farm_token: str = "", address: str = ""):
        self.farming_token = farming_token
        self.farm_token = farm_token
        self.farmed_token = farming_token
        self.address = address
        self.max_apr = max_apr
        self.rewards_per_block = rewards_per_block
        self.unbond_epochs = unbond_epochs
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "farming_token": self.farming_token,
            "farm_token": self.farm_token,
            "address": self.address,
            "max_apr": self.max_apr,
            "rewards_per_block": self.rewards_per_block,
            "unbond_epochs": self.unbond_epochs,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return StakingContract(farming_token=config_dict['farming_token'],
                               farm_token=config_dict['farm_token'],
                               address=config_dict['address'],
                               max_apr=config_dict['max_apr'],
                               rewards_per_block=config_dict['rewards_per_block'],
                               unbond_epochs=config_dict['unbond_epochs'],
                               version=StakingContractVersion(config_dict['version']))

    def stake_farm(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent,
                   initial: bool = False) -> str:
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        stake_farm_fn = "stakeFarm"

        print_warning(f"{stake_farm_fn}")

        gas_limit = 50000000

        sc_args = [
            "0x" + Address(self.address).hex(),  # contract address
            "0x01" if initial else "0x02",  # number of tokens sent
            "0x" + event.farming_tk.encode("ascii").hex(),  # farming token details
            "0x" + "0" + f"{event.farming_tk_nonce:x}" if len(
                f"{event.farming_tk_nonce:x}") % 2 else "0x" + f"{event.farming_tk_nonce:x}",
            "0x" + "0" + f"{event.farming_tk_amount:x}" if len(
                f"{event.farming_tk_amount:x}") % 2 else "0x" + f"{event.farming_tk_amount:x}",
        ]
        if not initial:
            sc_args.extend([
                "0x" + event.farm_tk.encode("ascii").hex(),  # farm token details
                "0x" + "0" + f"{event.farm_tk_nonce:x}" if len(
                    f"{event.farm_tk_nonce:x}") % 2 else "0x" + f"{event.farm_tk_nonce:x}",
                "0x" + "0" + f"{event.farm_tk_amount:x}" if len(
                    f"{event.farm_tk_amount:x}") % 2 else "0x" + f"{event.farm_tk_amount:x}",
            ])
        sc_args.extend([
            "0x" + stake_farm_fn.encode("ascii").hex(),  # enterFarm endpoint name
        ])
        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = user.address.bech32()  # MultiESDTNFTTransfer is issued via self transfers
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)
        try:
            txHash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(txHash, network_provider.proxy.url)
            user.nonce += 1

            return txHash
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())
            return ""

    def unstake_farm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        unstake_fn = 'unstakeFarm'
        print_warning(f"{unstake_fn}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + event.farm_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + unstake_fn.encode("ascii").hex(),
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = contract.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)
        try:
            txHash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(txHash, network_provider.proxy.url)
            user.nonce += 1

            return txHash
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())
            return ""

    def claimRewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        print_warning(f"claimRewards")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + self.farm_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "claimRewards".encode("ascii").hex(),
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = contract.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)
        try:
            txHash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(txHash, network_provider.proxy.url)
            user.nonce += 1
            return txHash
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())
            return ""

    def compoundRewards(self, network_provider: NetworkProviders, user: Account, event: CompoundRewardsFarmEvent) -> str:
        print_warning(f"compoundRewards")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + self.farm_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "compoundRewards".encode("ascii").hex(),
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = contract.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = gas_limit
        tx.data = tx_data
        tx.chainID = network_provider.network.chain_id
        tx.version = network_provider.network.min_tx_version
        tx.sign(user)
        try:
            txHash = network_provider.proxy.send_transaction(tx.to_dictionary())
            print_transaction_hash(txHash, network_provider.proxy.url)
            user.nonce += 1
            return txHash
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())
            return ""

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        """Expecting as args:percent
        type[str]: owner address - only from v2
        type[str]: admin address - only from v2
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        print_warning("Deploy staking contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=False, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            "0x" + self.farming_token.encode("ascii").hex(),
            "0xE8D4A51000",
            "0x" + "0" + f"{self.max_apr:x}" if len(f"{self.max_apr:x}") % 2 else "0x" + f"{self.max_apr:x}",
            "0x" + "0" + f"{self.unbond_epochs:x}" if len(f"{self.unbond_epochs:x}") % 2 else "0x" + f"{self.unbond_epochs:x}",
        ]
        if self.version == StakingContractVersion.V2:
            arguments.extend(args)

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

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = [],
                         yes: bool = True):
        """Expecting as args:percent
        type[str]: owner address - only from v2
        type[str]: admin address - only from v2
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        print_warning("Upgrade staking contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=False)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        tx_hash = ""

        arguments = [
            "str:" + self.farming_token,
            "0xE8D4A51000",
            self.max_apr,
            self.unbond_epochs,
        ]
        if self.version == StakingContractVersion.V2:
            arguments.extend(args)

        if not get_continue_confirmation(yes): return tx_hash

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

    def register_farm_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Register stake token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register stake token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerFarmToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_local_roles_farm_token(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Set local roles for stake token")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesFarmToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_rewards_per_block(self, deployer: Account, proxy: ElrondProxy, rewards_amount: int):
        print_warning("Set rewards per block in stake contract")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + "0" + f"{rewards_amount:x}" if len(f"{rewards_amount:x}") % 2 else "0x" + f"{rewards_amount:x}",
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setPerBlockRewardAmount", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def topup_rewards(self, deployer: Account, proxy: ElrondProxy, rewards_amount: int):
        print_warning("Topup rewards in stake contract")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + self.farmed_token.encode("ascii").hex(),
            "0x" + "0" + f"{rewards_amount:x}" if len(f"{rewards_amount:x}") % 2 else "0x" + f"{rewards_amount:x}",
            "0x" + "topUpRewards".encode("ascii").hex(),
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "ESDTTransfer", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def resume(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Resume stake contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "resume", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def pause(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Pause stake contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "pause", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def start_produce_rewards(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Start producing rewards in stake contract")

        network_config = proxy.get_network_config()
        gas_limit = 10000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "startProduceRewards", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def whitelist_contract(self, deployer: Account, proxy: ElrondProxy, contract_to_whitelist: str):
        print_warning("Whitelist contract in staking")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + Address(contract_to_whitelist).hex()
        ]

        endpoint_name = "addAddressToWhitelist" if self.version == StakingContractVersion.V1 \
            else "addSCAddressToWhitelist"
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      endpoint_name, sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        print_test_step_pass(f"Deployed staking contract: {self.address}")
        print_test_substep(f"Staking token: {self.farming_token}")
        print_test_substep(f"Stake token: {self.farm_token}")
