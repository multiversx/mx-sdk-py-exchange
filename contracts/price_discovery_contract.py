import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import PriceDiscoveryContractIdentity, DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders
from events.price_discovery_events import (DepositPDLiquidityEvent,
                                                             WithdrawPDLiquidityEvent, RedeemPDLPTokensEvent)
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import SmartContract, CodeMetadata
from erdpy.proxy import ElrondProxy
from erdpy.transactions import Transaction


class PriceDiscoveryContract(DEXContractInterface):
    def __init__(self,
                 launched_token_id: str,
                 accepted_token_id: str,
                 redeem_token: str,
                 first_redeem_token_nonce: int,
                 second_redeem_token_nonce: int,
                 address: str,
                 locking_sc_address: str,
                 start_block: int,
                 no_limit_phase_duration_blocks: int,
                 linear_penalty_phase_duration_blocks: int,
                 fixed_penalty_phase_duration_blocks: int,
                 unlock_epoch: int,
                 min_launched_token_price: int,
                 min_penalty_percentage: int,
                 max_penalty_percentage: int,
                 fixed_penalty_percentage: int
                 ):
        self.launched_token_id = launched_token_id  # launched token
        self.accepted_token = accepted_token_id  # accepted token
        self.redeem_token = redeem_token
        self.first_redeem_token_nonce = first_redeem_token_nonce  # launched token
        self.second_redeem_token_nonce = second_redeem_token_nonce  # accepted token
        self.address = address
        self.locking_sc_address = locking_sc_address
        self.start_block = start_block
        self.no_limit_phase_duration_blocks = no_limit_phase_duration_blocks
        self.linear_penalty_phase_duration_blocks = linear_penalty_phase_duration_blocks
        self.fixed_penalty_phase_duration_blocks = fixed_penalty_phase_duration_blocks
        self.unlock_epoch = unlock_epoch
        self.min_launched_token_price = min_launched_token_price
        self.min_penalty_percentage = min_penalty_percentage
        self.max_penalty_percentage = max_penalty_percentage
        self.fixed_penalty_percentage = fixed_penalty_percentage

    def get_config_dict(self) -> dict:
        output_dict = {
            "launched_token_id": self.launched_token_id,
            "accepted_token": self.accepted_token,
            "redeem_token": self.redeem_token,
            "first_redeem_token_nonce": self.first_redeem_token_nonce,
            "second_redeem_token_nonce": self.second_redeem_token_nonce,
            "address": self.address,
            "locking_sc_address": self.locking_sc_address,
            "start_block": self.start_block,
            "no_limit_phase_duration_blocks": self.no_limit_phase_duration_blocks,
            "linear_penalty_phase_duration_blocks": self.linear_penalty_phase_duration_blocks,
            "fixed_penalty_phase_duration_blocks": self.fixed_penalty_phase_duration_blocks,
            "unlock_epoch": self.unlock_epoch,
            "min_launched_token_price": self.min_launched_token_price,
            "min_penalty_percentage": self.min_penalty_percentage,
            "max_penalty_percentage": self.max_penalty_percentage,
            "fixed_penalty_percentage": self.fixed_penalty_percentage,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return PriceDiscoveryContract(launched_token_id=config_dict['launched_token_id'],  # launched token
                                      accepted_token_id=config_dict['accepted_token'],  # accepted token
                                      redeem_token=config_dict['redeem_token'],
                                      first_redeem_token_nonce=config_dict['first_redeem_token_nonce'],
                                      # launched token
                                      second_redeem_token_nonce=config_dict['second_redeem_token_nonce'],
                                      # accepted token
                                      address=config_dict['address'],
                                      locking_sc_address=config_dict['locking_sc_address'],
                                      start_block=config_dict['start_block'],
                                      no_limit_phase_duration_blocks=config_dict['no_limit_phase_duration_blocks'],
                                      linear_penalty_phase_duration_blocks=config_dict[
                                          'linear_penalty_phase_duration_blocks'],
                                      fixed_penalty_phase_duration_blocks=config_dict[
                                          'fixed_penalty_phase_duration_blocks'],
                                      unlock_epoch=config_dict['unlock_epoch'],
                                      min_launched_token_price=config_dict['min_launched_token_price'],
                                      min_penalty_percentage=config_dict['min_penalty_percentage'],
                                      max_penalty_percentage=config_dict['max_penalty_percentage'],
                                      fixed_penalty_percentage=config_dict['fixed_penalty_percentage'])

    def deposit_liquidity(self, network_provider: NetworkProviders, user: Account, event: DepositPDLiquidityEvent) -> str:
        print_warning(f"Deposit Price Discovery liquidity")
        print(f"Account: {user.address}")
        print(f"Token: {event.deposit_token} Amount: {event.amount}")

        contract = SmartContract(Address(self.address))

        gas_limit = 10000000
        sc_args = [
            "0x" + event.deposit_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + "deposit".encode("ascii").hex(),
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
            return ""

    def withdraw_liquidity(self, network_provider: NetworkProviders, user: Account, event: WithdrawPDLiquidityEvent) -> str:
        print_warning(f"Withdraw Price Discovery liquidity")
        print(f"Account: {user.address}")
        print(f"Token: {event.deposit_lp_token} Nonce: {event.nonce} Amount: {event.amount}")

        contract = SmartContract(address=user.address)

        gas_limit = 10000000
        sc_args = [
            "0x" + event.deposit_lp_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "withdraw".encode("ascii").hex(),
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

    def redeem_liquidity_position(self, network_provider: NetworkProviders, user: Account, event: RedeemPDLPTokensEvent) -> str:
        print_warning(f"Redeem Price Discovery liquidity")
        print(f"Account: {user.address}")
        print(f"Token: {event.deposit_lp_token} Nonce: {event.nonce} Amount: {event.amount}")

        contract = SmartContract(address=user.address)

        gas_limit = 10000000
        sc_args = [
            "0x" + event.deposit_lp_token.encode("ascii").hex(),
            "0x" + "0" + f"{event.nonce:x}" if len(f"{event.nonce:x}") % 2 else "0x" + f"{event.nonce:x}",
            "0x" + "0" + f"{event.amount:x}" if len(f"{event.amount:x}") % 2 else "0x" + f"{event.amount:x}",
            "0x" + Address(self.address).hex(),
            "0x" + "redeem".encode("ascii").hex(),
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

    """ Expected as args:
        type[str]:  whitelisted deposit rewards address
    """

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list = []):
        print_warning("Deploy price discovery contract")

        metadata = CodeMetadata(upgradeable=True, payable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 350000000
        value = 0
        address = ""
        tx_hash = ""

        arguments = [
            "0x" + self.launched_token_id.encode("ascii").hex(),  # launched token id
            "0x" + self.accepted_token.encode("ascii").hex(),  # accepted token id
            "0x12",  # launched token decimals
            self.min_launched_token_price,
            self.start_block,
            self.no_limit_phase_duration_blocks,
            self.linear_penalty_phase_duration_blocks,
            self.fixed_penalty_phase_duration_blocks,
            self.unlock_epoch,
            self.min_penalty_percentage,
            self.max_penalty_percentage,
            self.fixed_penalty_percentage,
            "0x" + Address(self.locking_sc_address).hex()  # locking sc address
        ]

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

    """ Expected as args:
        type[str]: lp token name
        type[str]: lp token ticker
        """

    def issue_redeem_token(self, deployer: Account, proxy: ElrondProxy, redeem_token_ticker: str):
        print_warning("Issue price discovery redeem token")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + redeem_token_ticker.encode("ascii").hex(),
            "0x" + redeem_token_ticker.encode("ascii").hex(),
            "0x12"
        ]
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueRedeemToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def create_initial_redeem_tokens(self, deployer: Account, proxy: ElrondProxy):
        print_warning("Create initial redeem tokens for price discovery contract")

        network_config = proxy.get_network_config()
        gas_limit = 50000000
        sc_args = []
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "createInitialRedeemTokens", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed price discovery contract: {self.address}")
        print_test_substep(f"Redeem token: {self.redeem_token}")
