import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import FarmContractVersion, DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from events.farm_events import (EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent,
                                                  CompoundRewardsFarmEvent, MigratePositionFarmEvent)


class FarmContract(DEXContractInterface):
    def __init__(self, farming_token, farm_token, farmed_token, address, version: FarmContractVersion,
                 proxy_contract=None):
        self.farmingToken = farming_token
        self.farmToken = farm_token
        self.farmedToken = farmed_token
        self.address = address
        self.version = version
        self.last_token_nonce = 0
        self.proxyContract = proxy_contract

    def get_config_dict(self) -> dict:
        output_dict = {
            "farmingToken": self.farmingToken,
            "farmToken": self.farmToken,
            "farmedToken": self.farmedToken,
            "address": self.address,
            "version": self.version.value,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return FarmContract(farming_token=config_dict['farmingToken'],
                            farm_token=config_dict['farmToken'],
                            farmed_token=config_dict['farmedToken'],
                            address=config_dict['address'],
                            version=FarmContractVersion(config_dict['version']))

    def has_proxy(self) -> bool:
        if self.proxyContract is not None:
            return True
        return False

    def enterFarm(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent, lock: int = 0, initial: bool = False) -> str:
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        enterFarmFn = "enterFarm"
        if lock == 1:
            enterFarmFn = "enterFarmAndLockRewards"
        elif lock == 0:
            enterFarmFn = "enterFarm"

        print_warning(f"{enterFarmFn}")

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
            "0x" + enterFarmFn.encode("ascii").hex(),  # enterFarm endpoint name
        ])
        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = user.address.bech32()     # MultiESDTNFTTransfer is issued via self transfers
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

    def exitFarm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        print_warning(f"exitFarm")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + self.farmToken.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "exitFarm".encode("ascii").hex(),
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
            "0x" + self.farmToken.encode("ascii").hex(),
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
            "0x" + self.farmToken.encode("ascii").hex(),
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

    def migratePosition(self, network_provider: NetworkProviders, user: Account, event: MigratePositionFarmEvent) -> str:
        print_warning(f"migratePosition")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + self.farmToken.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "migrateToNewFarm".encode("ascii").hex(),
            "0x" + user.address.hex(),
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

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:percent
        type[str]: pair contract address
        type[str]: locked asset factory address (only V14Locked)
        type[str]: admin address (only V2Boosted)
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        print_warning("Deploy farm contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 350000000
        value = 0
        address = ""
        tx_hash = ""

        if (self.version in [FarmContractVersion.V12, FarmContractVersion.V14Unlocked] and len(args) < 1) or \
           (self.version in [FarmContractVersion.V14Locked, FarmContractVersion.V2Boosted] and len(args) != 2):
            print_test_step_fail(f"FAIL: Failed to deploy contract version {self.version.name}. "
                                 f"Args list not as expected.")
            return tx_hash, address

        arguments = [
            "0x" + self.farmedToken.encode("ascii").hex(),
            "0x" + self.farmingToken.encode("ascii").hex(),
            "0xE8D4A51000",
            "0x" + Address(args[0]).hex()
        ]
        if self.version == FarmContractVersion.V14Locked:
            arguments.insert(2, "0x" + Address(args[1]).hex())
        if self.version == FarmContractVersion.V2Boosted:
            arguments.append("0x" + deployer.address.hex())
            if args[1]:
                arguments.append("0x" + Address(args[1]).hex())

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

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = [],
                         no_init: bool = False):
        """Expecting as args:percent
        type[str]: pair contract address
        type[str]: locked asset factory address (only V14Locked)
        type[str]: admin address (only V2Boosted)
        self.version has to be initialized to correctly attempt the upgrade for that specific type of farm.
        """
        print_warning("Upgrade farm contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 350000000
        value = 0
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            if (self.version in [FarmContractVersion.V12, FarmContractVersion.V14Unlocked] and len(args) < 1) or \
               (self.version in [FarmContractVersion.V14Locked, FarmContractVersion.V2Boosted] and len(args) != 2):
                print_test_step_fail(f"FAIL: Failed to deploy contract version {self.version.name}. "
                                     f"Args list not as expected.")
                return tx_hash

            arguments = [
                "0x" + self.farmedToken.encode("ascii").hex(),
                "0x" + self.farmingToken.encode("ascii").hex(),
                "0xE8D4A51000",
                "0x" + Address(args[0]).hex()
            ]
            if self.version == FarmContractVersion.V14Locked:
                arguments.insert(2, "0x" + Address(args[1]).hex())
            if self.version == FarmContractVersion.V2Boosted:
                arguments.append("0x" + deployer.address.hex())
                if args[1]:
                    arguments.append("0x" + Address(args[1]).hex())

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
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def register_farm_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Expecting as args:percent
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Register farm token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register farm token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]

        print(f"Arguments: {sc_args}")

        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerFarmToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_local_roles_farm_token(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Set local roles for farm token")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRolesFarmToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_rewards_per_block(self, deployer: Account, proxy: ElrondProxy, rewards_amount: int):
        print_warning("Set rewards per block in farm")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + "0" + f"{rewards_amount:x}" if len(f"{rewards_amount:x}") % 2 else "0x" + f"{rewards_amount:x}",
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setPerBlockRewardAmount", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_penalty_percent(self, deployer: Account, proxy: ElrondProxy, percent: int):
        print_warning("Set penalty percent in farm")

        network_config = proxy.get_network_config()
        gas_limit = 20000000
        sc_args = [
            "0x" + "0" + f"{percent:x}" if len(f"{percent:x}") % 2 else "0x" + f"{percent:x}",
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "set_penalty_percent", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_minimum_farming_epochs(self, deployer: Account, proxy: ElrondProxy, epochs: int):
        print_warning("Set minimum farming epochs in farm")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            epochs
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "set_minimum_farming_epochs", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_boosted_yields_factors(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Only V2Boosted.
        Expecting as args:
        type[int]: max_rewards_factor
        type[int]: user_rewards_energy_const
        type[int]: user_rewards_farm_const
        type[int]: min_energy_amount
        type[int]: min_farm_amount
        """
        print_warning("Set boosted yield factors")

        if len(args) != 5:
            print_test_step_fail(f"FAIL: Failed to set boosted yield factors. Args list not as expected.")
            return ""

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setBoostedYieldsFactors", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_boosted_yields_rewards_percentage(self, deployer: Account, proxy: ElrondProxy, percentage: int):
        """Only V2Boosted.
        """
        print_warning("Set boosted yield rewards percentage")

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = [percentage]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setBoostedYieldsRewardsPercentage", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_energy_factory_address(self, deployer: Account, proxy: ElrondProxy, energy_factory_address: str):
        """Only V2Boosted.
        """
        print_warning("Set energy factory address in farm")

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = [energy_factory_address]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setEnergyFactoryAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_locking_address(self, deployer: Account, proxy: ElrondProxy, locking_address: str):
        """Only V2Boosted.
        """
        print_warning("Set locking sc address in farm")

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = [locking_address]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockingScAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_lock_epochs(self, deployer: Account, proxy: ElrondProxy, lock_epochs: int):
        """Only V2Boosted.
        """
        print_warning("Set lock epochs in farm")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [lock_epochs]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockEpochs", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_contract_to_whitelist(self, deployer: Account, proxy: ElrondProxy, whitelisted_sc_address: str):
        """Only V2Boosted.
        """
        print_warning("Add contract to farm whitelist")

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = [whitelisted_sc_address]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addSCAddressToWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_transfer_role_farm_token(self, deployer: Account, proxy: ElrondProxy, whitelisted_sc_address: str):
        """Only V2Boosted.
        """
        print_warning("Set transfer role farm token")

        network_config = proxy.get_network_config()
        gas_limit = 70000000
        sc_args = [whitelisted_sc_address] if whitelisted_sc_address else []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setTransferRoleFarmToken", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def resume(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Resume farm contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "resume", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def pause(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Pause farm contract")

        network_config = proxy.get_network_config()
        gas_limit = 30000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "pause", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def start_produce_rewards(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Start producing rewards in farm contract")

        network_config = proxy.get_network_config()
        gas_limit = 10000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "startProduceRewards", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def end_produce_rewards(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Stop producing rewards in farm contract")

        network_config = proxy.get_network_config()
        gas_limit = 10000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "end_produce_rewards", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        print_test_step_pass(f"Deployed farm contract: {self.address}")
        print_test_substep(f"Farming token: {self.farmingToken}")
        print_test_substep(f"Farmed token: {self.farmedToken}")
        print_test_substep(f"Farm token: {self.farmToken}")
