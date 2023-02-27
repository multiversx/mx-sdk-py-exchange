import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import (
    DEXContractInterface, PairContractVersion)
from utils.utils_tx import (NetworkProviders,
                            prepare_contract_call_tx,
                            send_contract_call_tx)
from utils.utils_chain import (dec_to_padded_hex, print_transaction_hash,
                               string_to_hex)
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import CodeMetadata, SmartContract
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction


class SwapFixedInputEvent:
    def __init__(self, tokenA: str, amountA: int, tokenB: str, amountBmin: int):
        self.tokenA = tokenA
        self.amountA = amountA
        self.tokenB = tokenB
        self.amountBmin = amountBmin


class SwapFixedOutputEvent:
    def __init__(self, tokenA: str, amountAmax: int, tokenB: str, amountB: int):
        self.tokenA = tokenA
        self.amountAmax = amountAmax
        self.tokenB = tokenB
        self.amountB = amountB


class AddLiquidityEvent:
    def __init__(self, tokenA: str, amountA: int, amountAmin: int, tokenB: str, amountB: int, amountBmin: int):
        self.tokenA = tokenA
        self.amountA = amountA
        self.amountAmin = amountAmin
        self.tokenB = tokenB
        self.amountB = amountB
        self.amountBmin = amountBmin


class RemoveLiquidityEvent:
    def __init__(self, amount: int, tokenA: str, amountA: int, tokenB: str, amountB: int):
        self.amount = amount
        self.tokenA = tokenA
        self.amountA = amountA
        self.tokenB = tokenB
        self.amountB = amountB


class SetCorrectReservesEvent:
    pass


class PairContract(DEXContractInterface):
    def __init__(self, firstToken: str, secondToken: str,  version: PairContractVersion,
                 lpToken: str = "", address: str = "", proxy_contract=None):
        self.firstToken = firstToken
        self.secondToken = secondToken
        self.version = version
        self.lpToken = lpToken
        self.address = address
        self.proxy_contract = proxy_contract

    def get_config_dict(self) -> dict:
        output_dict = {
            "firstToken": self.firstToken,
            "secondToken": self.secondToken,
            "lpToken": self.lpToken,
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return PairContract(firstToken=config_dict['firstToken'],
                            secondToken=config_dict['secondToken'],
                            lpToken=config_dict['lpToken'],
                            address=config_dict['address'],
                            version=PairContractVersion(config_dict['version']))

    def hasProxy(self) -> bool:
        if self.proxy_contract is not None:
            return True
        return False

    def swapFixedInput(self, network_provider: NetworkProviders, user: Account, event: SwapFixedInputEvent):
        print_warning("swapFixedInput")
        print(f"Account: {user.address}")
        print(f"{event.amountA} {event.tokenA} for minimum {event.amountBmin} {event.tokenB}")

        contract = SmartContract(address=self.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + event.tokenA.encode("ascii").hex(),
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + "swapTokensFixedInput".encode("ascii").hex(),
            "0x" + event.tokenB.encode("ascii").hex(),
            "0x" + "0" + f"{event.amountBmin:x}" if len(
                f"{event.amountBmin:x}") % 2 else "0x" + f"{event.amountBmin:x}",
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTTransfer", sc_args)

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

    def swapFixedOutput(self, network_provider: NetworkProviders, user: Account, event: SwapFixedOutputEvent):
        print_warning("swapFixedOutput")
        print(f"Account: {user.address}")

        contract = SmartContract(address=self.address)

        gas_limit = 50000000
        sc_args = [
            "0x" + event.tokenA.encode("ascii").hex(),
            "0x" + "0" + f"{event.amountAmax:x}" if len(
                f"{event.amountAmax:x}") % 2 else "0x" + f"{event.amountAmax:x}",
            "0x" + "swapTokensFixedOutput".encode("ascii").hex(),
            "0x" + event.tokenB.encode("ascii").hex(),
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTTransfer", sc_args)

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
            ex = ex

    def addLiquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        print_warning("addLiquidity")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        sc_args = [
            "0x" + Address(self.address).hex(),
            "0x02",
            "0x" + string_to_hex(event.tokenA),
            "0x00",
            "0x" + dec_to_padded_hex(event.amountA),
            "0x" + string_to_hex(event.tokenB),
            "0x00",
            "0x" + dec_to_padded_hex(event.amountB),
            "0x" + string_to_hex("addLiquidity"),
            "0x" + dec_to_padded_hex(event.amountAmin),
            "0x" + dec_to_padded_hex(event.amountBmin)
        ]

        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)
        gas_limit = 20000000
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
            print(f'Exception encountered: {ex}')

    def addInitialLiquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        print_warning("addInitialLiquidity")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        sc_args = [
            "0x" + Address(self.address).hex(),
            "0x02",
            "0x" + string_to_hex(event.tokenA),
            "0x00",
            "0x" + dec_to_padded_hex(event.amountA),
            "0x" + string_to_hex(event.tokenB),
            "0x00",
            "0x" + dec_to_padded_hex(event.amountB),
            "0x" + string_to_hex("addInitialLiquidity")
        ]

        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)
        gas_limit = 20000000
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
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())

    def removeLiquidity(self, network_provider: NetworkProviders, user: Account, event: RemoveLiquidityEvent):
        print_warning("removeLiquidity")
        print(f"Account: {user.address}")

        contract = SmartContract(address=self.address)

        gas_limit = 20000000
        sc_args = [
            "0x" + self.lpToken.encode("ascii").hex(),
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + "removeLiquidity".encode("ascii").hex(),
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTTransfer", sc_args)

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
            ex = ex

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
            type[str]: router address
            type[str]: whitelisted owner address
            type[str]: initial liquidity adder address (v2 required)
            type[any]: fee percentage
            type[any]: special fee
            type[str..]: admin addresses (v2 required)
        """
        print_warning("Deploy pair contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=False, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        if len(args) < 5:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash, address

        arguments = [
            "0x" + self.firstToken.encode("ascii").hex(),
            "0x" + self.secondToken.encode("ascii").hex(),
            "0x" + Address(args[0]).hex(),
            "0x" + Address(args[1]).hex(),
            args[3],
            args[4],
            args[2]
        ]

        if self.version == PairContractVersion.V2:
            arguments.extend(args[5:])

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

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
            type[str]: router address
            type[str]: whitelisted owner address
            type[str]: initial liquidity adder address (v2 required)
            type[any]: fee percentage
            type[any]: special fee
            type[str..]: admin addresses (v2 required)
        """
        print_warning("Upgrade pair contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=False)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        tx_hash = ""

        if len(args) < 5:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash

        arguments = [
            "0x" + self.firstToken.encode("ascii").hex(),
            "0x" + self.secondToken.encode("ascii").hex(),
            "0x" + Address(args[0]).hex(),
            "0x" + Address(args[1]).hex(),
            args[3],
            args[4],
            args[2]
        ]

        if self.version == PairContractVersion.V2:
            arguments.extend(args[5:])

        contract = SmartContract(address=Address(self.address), bytecode=bytecode, metadata=metadata)
        tx = contract.upgrade(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                              network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            print_transaction_hash(tx_hash, proxy.url, True)
            deployer.nonce += 1 if tx_hash != "" else 0

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def contract_deploy_via_router(self, deployer: Account, proxy: ElrondProxy, router_contract, args: list):
        """ Expected as args:
            type[str]: initial liquidity adder address
            type[any]: total fee percentage
            type[any]: special fee percentage
            type[str..]: admin addresses
        """
        pair_args = [self.firstToken, self.secondToken]
        pair_args.extend(args)
        tx_hash, address = router_contract.pair_contract_deploy(deployer, proxy, pair_args)
        return tx_hash, address

    def contract_upgrade_via_router(self, deployer: Account, proxy: ElrondProxy, router_contract, args: list) -> str:
        """ Expected as args:
            type[int]: total fee percentage
            type[int]: special fee percentage
            type[str]: initial liquidity adder (only v1 router)
        """
        pair_args = [self.firstToken, self.secondToken]
        pair_args.extend(args)
        tx_hash = router_contract.pair_contract_upgrade(deployer, proxy, pair_args)
        return tx_hash

    def issue_lp_token_via_router(self, deployer: Account, proxy: ElrondProxy, router_contract, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Issue LP token via router")

        if len(args) < 2:
            print_test_step_fail(f"FAIL: Failed to issue lp token. Args list not as expected.")
            return ""

        tx_hash = router_contract.issue_lp_token(deployer, proxy, [self.address, args[0], args[1]])
        return tx_hash

    def whitelist_contract(self, deployer: Account, proxy: ElrondProxy, contract_to_whitelist: str):
        print_warning("Whitelist contract in pair")

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

    def add_trusted_swap_pair(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: trusted swap pair address
            type[str]: trusted pair first token identifier
            type[str]: trusted pair second token identifier
        """
        print_warning("Whitelist contract in pair")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to add trusted swap pair. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x" + args[2].encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addTrustedSwapPair", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_fees_collector(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: fees collector address
            type[str]: fees cut
        """
        print_warning("Setup fees collector in pair")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to setup fees collector in pair. Args list not as expected.")
            return tx_hash

        gas_limit = 50000000
        sc_args = [
            "0x" + Address(args[0]).hex(),
            args[1]
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setupFeesCollector", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_fees_percents(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: total fee percent
            type[str]: special fee percent
        """
        print_warning("Set fees in pair contract")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to set fees in pair. Args list not as expected.")
            return tx_hash

        gas_limit = 50000000
        sc_args = args
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setFeePercents", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_lp_token_local_roles_via_router(self, deployer: Account, proxy: ElrondProxy, router_contract):
        print_warning("Set lp token local roles via router")
        tx_hash = router_contract.set_lp_token_local_roles(deployer, proxy, self.address)
        return tx_hash

    """ Expected as args:
    type[str]: address to receive fees
    type[str]: expected token
    """

    def set_fee_on_via_router(self, deployer: Account, proxy: ElrondProxy, router_contract, args: list):
        print_warning("Set fee on via router")

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to set fee on via router. Args list not as expected.")
            return ""

        tx_hash = router_contract.set_fee_on(deployer, proxy, [self.address, args[0], args[1]])
        return tx_hash

    def set_locking_deadline_epoch(self, deployer: Account, proxy: ElrondProxy, epoch: int):
        print_warning("Set locking deadline epoch in pool")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + "0" + f"{epoch:x}" if len(f"{epoch:x}") % 2 else "0x" + f"{epoch:x}"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockingDeadlineEpoch", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_unlock_epoch(self, deployer: Account, proxy: ElrondProxy, epoch: int):
        print_warning("Set unlock epoch in pool")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + "0" + f"{epoch:x}" if len(f"{epoch:x}") % 2 else "0x" + f"{epoch:x}"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setUnlockEpoch", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_locking_sc_address(self, deployer: Account, proxy: ElrondProxy, locking_address: str):
        print_warning("Set locking contract address in pool")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + Address(locking_address).hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLockingScAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def resume(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Resume swaps in pool")

        network_config = proxy.get_network_config()
        gas_limit = 10000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "resume", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        print_test_step_pass(f"Deployed pair contract: {self.address}")
        print_test_substep(f"First token: {self.firstToken}")
        print_test_substep(f"Second token: {self.secondToken}")
        print_test_substep(f"LP token: {self.lpToken}")
