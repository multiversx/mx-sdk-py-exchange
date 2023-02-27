import random
import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface, ProxyContractVersion
from contracts.farm_contract import FarmContract
from contracts.pair_contract import PairContract
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction


class DexProxyAddLiquidityEvent:
    def __init__(self, pairContract: PairContract,
                 tokenA: str, nonceA: int, amountA: int, amountAmin: int,
                 tokenB: str, nonceB: int, amountB: int, amountBmin: int):
        self.pairContract = pairContract
        self.tokenA = tokenA
        self.nonceA = nonceA
        self.amountA = amountA
        self.amountAmin = amountAmin
        self.tokenB = tokenB
        self.nonceB = nonceB
        self.amountB = amountB
        self.amountBmin = amountBmin


class DexProxyRemoveLiquidityEvent:
    def __init__(self, pairContract: PairContract, amount: int, nonce: int, amountA: int, amountB: int):
        self.pairContract = pairContract
        self.amount = amount
        self.nonce = nonce
        self.amountA = amountA
        self.amountB = amountB


class DexProxyEnterFarmEvent:
    def __init__(self, farmContract: FarmContract,
                 farming_token: str, farming_nonce: int, farming_amount,
                 farm_token: str, farm_nonce: int, farm_amount):
        self.farmContract = farmContract
        self.farming_tk = farming_token
        self.farming_tk_nonce = farming_nonce
        self.farming_tk_amount = farming_amount
        self.farm_tk = farm_token
        self.farm_tk_nonce = farm_nonce
        self.farm_tk_amount = farm_amount


class DexProxyExitFarmEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


class DexProxyClaimRewardsEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


class DexProxyCompoundRewardsEvent:
    def __init__(self, farmContract: FarmContract, token: str, nonce: int, amount):
        self.farmContract = farmContract
        self.token = token
        self.nonce = nonce
        self.amount = amount


class DexFarmProxyContract:
    def __init__(self, farming_token: str, farm_token: str, address: str):
        self.address = address
        self.farming_token = farming_token
        self.farm_token = farm_token

    def enter_farm_proxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyEnterFarmEvent, lock: int = -1,
                         initial: bool = False):
        print("enterFarmProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        enterFarmFn = ""
        if lock == 1:
            enterFarmFn = "enterFarmAndLockRewardsProxy"
        elif lock == 0:
            enterFarmFn = "enterFarmProxy"
        else:
            if random.randrange(0, 1) == 1:
                enterFarmFn = "enterFarmAndLockRewardsProxy"
            else:
                enterFarmFn = "enterFarmProxy"

        gas_limit = 50000000

        sc_args = [
            "0x" + Address(self.address).hex(),  # proxy address
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
            "0x" + Address(event.farmContract.address).hex(),  # farm address
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
        except Exception as ex:
            print(ex)

    def exit_farm_proxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyExitFarmEvent):
        print("exitFarmProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000

        sc_args = [
            "0x" + event.token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "exitFarmProxy".encode("ascii").hex(),
            "0x" + Address(event.farmContract.address).hex(),
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
        except Exception as ex:
            print(ex)

    def claim_rewards_proxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyClaimRewardsEvent):
        print("claimRewardsProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000

        sc_args = [
            "0x" + event.token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "claimRewardsProxy".encode("ascii").hex(),
            "0x" + Address(event.farmContract.address).hex(),
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
        except Exception as ex:
            print(ex)


class DexPairProxyContract:
    def __init__(self, p_token_a: str, p_token_b: str, p_lp_token: str, address: str):
        self.address = address
        self.proxy_token_a = p_token_a
        self.proxy_token_b = p_token_b
        self.proxy_lp_token = p_lp_token

    def add_liquidity_proxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyAddLiquidityEvent):
        print("addLiquidityProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)
        add_liquidity_fn = "addLiquidityProxy"

        sc_args = [
            "0x" + Address(self.address).hex(),  # proxy address
            "0x02",  # number of tokens sent
            "0x" + event.tokenA.encode("ascii").hex(),  # farming token details
            "0x" + "0" + f"{event.nonceA:x}" if len(f"{event.nonceA:x}") % 2 else "0x" + f"{event.nonceA:x}",
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + event.tokenB.encode("ascii").hex(),  # farm token details
            "0x" + "0" + f"{event.nonceB:x}" if len(f"{event.nonceB:x}") % 2 else "0x" + f"{event.nonceB:x}",
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
            "0x" + add_liquidity_fn.encode("ascii").hex(),  # enterFarm endpoint name
            "0x" + Address(event.pairContract.address).hex(),  # farm address
            "0x" + "0" + f"{event.amountAmin:x}" if len(f"{event.amountAmin:x}") % 2 else "0x" + f"{event.amountAmin:x}",
            "0x" + "0" + f"{event.amountBmin:x}" if len(f"{event.amountBmin:x}") % 2 else "0x" + f"{event.amountBmin:x}",
        ]

        tx_data = contract.prepare_execute_transaction_data("MultiESDTNFTTransfer", sc_args)
        gas_limit = 1000000000
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
            user.nonce += 1
            print_transaction_hash(txHash, network_provider.proxy.url)
        except Exception as ex:
            print(ex)

    def remove_liquidity_proxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyRemoveLiquidityEvent):
        print("removeLiquidityProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)
        sc_args = [
            "0x" + context.wrappedLpTokenId.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "removeLiquidityProxy".encode("ascii").hex(),
            "0x" + Address(event.pairContract.address).hex(),
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        gas_limit = 1000000000
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
            user.nonce += 1
            print_transaction_hash(txHash, network_provider.proxy.url)
        except Exception as ex:
            print(ex)


class DexProxyContract(DEXContractInterface):
    def __init__(self, locked_tokens: list, token: str, version: ProxyContractVersion,
                 address: str = "", proxy_lp_token: str = "", proxy_farm_token: str = ""):
        self.address = address
        self.proxy_lp_token = proxy_lp_token
        self.proxy_farm_token = proxy_farm_token
        self.locked_tokens = locked_tokens
        self.token = token
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "token": self.token,
            "locked_tokens": self.locked_tokens,
            "proxy_farm_token": self.proxy_farm_token,
            "proxy_lp_token": self.proxy_lp_token,
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return DexProxyContract(token=config_dict['token'],
                                locked_tokens=config_dict['locked_tokens'],
                                proxy_farm_token=config_dict['proxy_farm_token'],
                                proxy_lp_token=config_dict['proxy_lp_token'],
                                address=config_dict['address'],
                                version=ProxyContractVersion(config_dict['version']))

    def addLiquidityProxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyAddLiquidityEvent):
        print("addLiquidityProxy")
        print(f"Account: {user.address}")

        self.acceptEsdtPaymentProxy(context, user, event.pairContract, event.tokenA, event.nonceA, event.amountA)
        self.acceptEsdtPaymentProxy(context, user, event.pairContract, event.tokenB, event.nonceB, event.amountB)

        contract = SmartContract(address=self.address)
        sc_args = [
            "0x" + Address(event.pairContract.address).hex(),
            "0x" + event.tokenA.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonceA:x}" if len(f"{event.nonceA:x}") % 2 else "0x" + f"{event.nonceA:x}",
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + "0" + f"{event.amountAmin:x}" if len(f"{event.amountAmin:x}") % 2 else "0x" + f"{event.amountAmin:x}",
            "0x" + event.tokenB.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonceB:x}" if len(f"{event.nonceB:x}") % 2 else "0x" + f"{event.nonceB:x}",
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
            "0x" + "0" + f"{event.amountBmin:x}" if len(f"{event.amountBmin:x}") % 2 else "0x" + f"{event.amountBmin:x}",
        ]

        tx_data = contract.prepare_execute_transaction_data("addLiquidityProxy", sc_args)
        gas_limit = 1000000000
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
            user.nonce += 1
            print_transaction_hash(txHash, network_provider.proxy.url)
        except Exception as ex:
            print(ex)

    def acceptEsdtPaymentProxy(self, network_provider: NetworkProviders, user: Account, pair: PairContract,
                               token: str, nonce: int, amount: str):
        print("acceptEsdtPaymentProxy")
        print(f"Account: {user.address}")

        if nonce == 0:
            contract = SmartContract(address=self.address)
            sc_args = [
                "0x" + token.encode("ascii").hex(),
                "0x" + "0" + f"{amount:x}" if len(f"{amount:x}") % 2 else "0x" + f"{amount:x}",
                "0x" + "acceptEsdtPaymentProxy".encode("ascii").hex(),
                "0x" + Address(pair.address).hex(),
            ]
            tx_data = contract.prepare_execute_transaction_data("ESDTTransfer", sc_args)
        else:
            contract = SmartContract(address=user.address)
            sc_args = [
                "0x" + token.encode("ascii").hex(),
                "0x" + "0" + f"{nonce:x}" if len(f"{nonce:x}") % 2 else "0x" + f"{nonce:x}",
                "0x" + "0" + f"{amount:x}" if len(f"{amount:x}") % 2 else "0x" + f"{amount:x}",
                "0x" + Address(self.address).hex(),
                "0x" + "acceptEsdtPaymentProxy".encode("ascii").hex(),
                "0x" + Address(pair.address).hex(),
            ]
            tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        tx = Transaction()
        tx.nonce = user.nonce
        tx.sender = user.address.bech32()
        tx.receiver = contract.address.bech32()
        tx.gasPrice = network_provider.network.min_gas_price
        tx.gasLimit = 50000000
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

    def removeLiquidityProxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyRemoveLiquidityEvent):
        print("removeLiquidityProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)
        sc_args = [
            "0x" + context.wrappedLpTokenId.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "removeLiquidityProxy".encode("ascii").hex(),
            "0x" + Address(event.pairContract.address).hex(),
            "0x" + "0" + f"{event.amountA:x}" if len(f"{event.amountA:x}") % 2 else "0x" + f"{event.amountA:x}",
            "0x" + "0" + f"{event.amountB:x}" if len(f"{event.amountB:x}") % 2 else "0x" + f"{event.amountB:x}",
        ]
        tx_data = contract.prepare_execute_transaction_data("ESDTNFTTransfer", sc_args)

        gas_limit = 1000000000
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
            user.nonce += 1
            print_transaction_hash(txHash, network_provider.proxy.url)
        except Exception as ex:
            print(ex)

    def enterFarmProxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyEnterFarmEvent, lock: int = -1, initial: bool = False):
        print("enterFarmProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        enterFarmFn = ""
        if lock == 1:
            enterFarmFn = "enterFarmAndLockRewardsProxy"
        elif lock == 0:
            enterFarmFn = "enterFarmProxy"
        else:
            if random.randrange(0, 1) == 1:
                enterFarmFn = "enterFarmAndLockRewardsProxy"
            else:
                enterFarmFn = "enterFarmProxy"

        gas_limit = 50000000

        sc_args = [
            "0x" + Address(self.address).hex(),  # proxy address
            "0x01" if initial else "0x02",     # number of tokens sent
            "0x" + event.farming_tk.encode("ascii").hex(),  # farming token details
            "0x" + "0" + f"{event.farming_tk_nonce:x}" if len(f"{event.farming_tk_nonce:x}") % 2 else "0x" + f"{event.farming_tk_nonce:x}",
            "0x" + "0" + f"{event.farming_tk_amount:x}" if len(f"{event.farming_tk_amount:x}") % 2 else "0x" + f"{event.farming_tk_amount:x}",
        ]
        if not initial:
            sc_args.extend([
                "0x" + event.farm_tk.encode("ascii").hex(),  # farm token details
                "0x" + "0" + f"{event.farm_tk_nonce:x}" if len(f"{event.farm_tk_nonce:x}") % 2 else "0x" + f"{event.farm_tk_nonce:x}",
                "0x" + "0" + f"{event.farm_tk_amount:x}" if len(f"{event.farm_tk_amount:x}") % 2 else "0x" + f"{event.farm_tk_amount:x}",
            ])
        sc_args.extend([
            "0x" + enterFarmFn.encode("ascii").hex(),       # enterFarm endpoint name
            "0x" + Address(event.farmContract.address).hex(),   # farm address
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
        except Exception as ex:
            print(ex)

    def exitFarmProxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyExitFarmEvent):
        print("exitFarmProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000

        sc_args = [
            "0x" + event.token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "exitFarmProxy".encode("ascii").hex(),
            "0x" + Address(event.farmContract.address).hex(),
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
        except Exception as ex:
            print(ex)

    def claimRewardsProxy(self, network_provider: NetworkProviders, user: Account, event: DexProxyClaimRewardsEvent):
        print("claimRewardsProxy")
        print(f"Account: {user.address}")

        contract = SmartContract(address=user.address)

        gas_limit = 50000000

        sc_args = [
            "0x" + event.token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "claimRewardsProxy".encode("ascii").hex(),
            "0x" + Address(event.farmContract.address).hex(),
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
        except Exception as ex:
            print(ex)

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        """Expecting as args:
        type[list]: locked asset factories contract addresses; care for the correct order based on locked tokens list
        """
        print_warning("Deploy dex proxy contract")

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return "", ""

        if len(self.locked_tokens) != len(args[0]):
            print_test_step_fail(f"FAIL: Failed to deploy contract. "
                                 f"Mismatch between locked tokens and factory addresses.")
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 300000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            "0x" + self.token.encode("ascii").hex()
        ]

        locked_tokens_list = [f"str:{token}" for token in self.locked_tokens]
        locked_tokens_args = list(sum(zip(locked_tokens_list, args[0]), ()))

        arguments.extend(locked_tokens_args)

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
        """Expecting as args:
        type[list]: locked asset factories contract addresses; care for the correct order based on locked tokens list
        """
        print_warning("Upgrade dex proxy contract")

        if len(args) != 1 and not no_init:
            print_test_step_fail(f"FAIL: Failed to upgrade contract. Args list not as expected.")
            return "", ""

        if not no_init and len(self.locked_tokens) != len(args[0]):
            print_test_step_fail(f"FAIL: Failed to deploy contract. "
                                 f"Mismatch between locked tokens and factory addresses.")
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 300000000
        value = 0
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            arguments = [
                "0x" + self.token.encode("ascii").hex()
            ]
            locked_tokens_list = [f"str:{token}" for token in self.locked_tokens]
            locked_tokens_args = list(sum(zip(locked_tokens_list, args[0]), ()))
            arguments.extend(locked_tokens_args)

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

    def register_proxy_farm_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Expecting as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Register proxy farm token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register proxy farm token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerProxyFarm", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def register_proxy_lp_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """Expecting as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Register proxy lp token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to register proxy lp token. Args list not as expected.")
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "registerProxyPair", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    """Expecting as args:
    type[str]: token id
    type[str]: contract address to assign roles to
    """
    def set_local_roles_proxy_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        print_warning("Set local roles for proxy token")

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to set proxy local roles: unexpected number of args.")
            return ""

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + Address(args[1]).hex(),
            "0x03", "0x04", "0x05"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setLocalRoles", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_energy_factory_address(self, deployer: Account, proxy: ElrondProxy, energy_address: str):
        print_warning("Set energy factory address in proxy contract")

        if energy_address == "":
            print_test_step_fail(f"FAIL: Failed to Add pair to intermediate: pair address is empty")
            return ""

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + Address(energy_address).hex(),
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "setEnergyFactoryAddress", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_pair_to_intermediate(self, deployer: Account, proxy: ElrondProxy, pair_address: str):
        print_warning("Add pair to intermediate in proxy contract")

        if pair_address == "":
            print_test_step_fail(f"FAIL: Failed to Add pair to intermediate: pair address is empty")
            return ""

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + Address(pair_address).hex(),
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addPairToIntermediate", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_farm_to_intermediate(self, deployer: Account, proxy: ElrondProxy, farm_address: str):
        print_warning("Add farm to intermediate in proxy contract")

        if farm_address == "":
            print_test_step_fail(f"FAIL: Failed to Add farm to intermediate: farm address is empty")
            return ""

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = [
            "0x" + Address(farm_address).hex(),
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addFarmToIntermediate", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed proxy contract: {self.address}")
        print_test_substep(f"Token: {self.token}")
        print_test_substep(f"Locked tokens: {self.locked_tokens}")
        print_test_substep(f"Proxy LP token: {self.proxy_lp_token}")
        print_test_substep(f"Proxy Farm token: {self.proxy_farm_token}")
