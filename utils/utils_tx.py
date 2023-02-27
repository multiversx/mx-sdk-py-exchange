import sys
import time
import traceback
from typing import List, Dict

from multiversx_sdk_core import Transaction, TokenPayment, Address
from multiversx_sdk_network_providers import ProxyNetworkProvider, ApiNetworkProvider
from multiversx_sdk_network_providers.network_config import NetworkConfig
from multiversx_sdk_network_providers.tokens import FungibleTokenOfAccountOnNetwork, NonFungibleTokenOfAccountOnNetwork
from multiversx_sdk_network_providers.transactions import TransactionOnNetwork
from multiversx_sdk_core.transaction_builders import ContractCallBuilder, DefaultTransactionBuildersConfiguration, \
    MultiESDTNFTTransferBuilder
from utils.utils_chain import Account, print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_warning

TX_CACHE: Dict[str, dict] = {}


class ESDTToken:
    token_id: str
    token_nonce: int
    token_amount: int

    def __init__(self, token_id: str, token_nonce: int, token_amount: int):
        self.token_id = token_id
        self.token_nonce = token_nonce
        self.token_amount = token_amount

    def get_token_data(self) -> tuple:
        return self.token_id, self.token_nonce, self.token_amount

    def get_full_token_name(self) -> str:
        if self.token_nonce != 0:
            nonce_str = "0" + f"{self.token_nonce:x}" if len(f"{self.token_nonce:x}") % 2 else f"{self.token_nonce:x}"
            return f"{self.token_id}-{nonce_str}"
        else:
            return f"{self.token_id}"

    @classmethod
    def from_token_payment(cls, token_payment: TokenPayment):
        return cls(token_payment.token_identifier, token_payment.token_nonce, token_payment.amount_as_integer)

    @classmethod
    def from_fungible_on_network(cls, token: FungibleTokenOfAccountOnNetwork):
        return cls(token.identifier, 0, token.balance)

    @classmethod
    def from_non_fungible_on_network(cls, token: NonFungibleTokenOfAccountOnNetwork):
        return cls(token.identifier, token.nonce, token.balance)

    def to_token_payment(self) -> TokenPayment:
        return TokenPayment(self.token_id, self.token_nonce, self.token_amount, 18)


class NetworkProviders:
    def __init__(self, api: str, proxy: str):
        self.api = ApiNetworkProvider(api)
        self.proxy = ProxyNetworkProvider(proxy)
        self.network = self.proxy.get_network_config()

    def wait_for_tx_executed(self, tx_hash: str):
        time.sleep(2)  # temporary fix for the api returning the wrong status
        while True:
            status = self.api.get_transaction_status(tx_hash)
            if status.is_executed():
                break
            time.sleep(self.network.round_duration)

    def check_deploy_tx_status(self, tx_hash: str, address: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                print_test_step_fail(f"FAIL: no tx hash for {msg_label} contract deployment!")
            return False

        status = self.api.get_transaction_status(tx_hash)
        if status.is_failed() or address == "":
            if msg_label:
                print_test_step_fail(f"FAIL: transaction for {msg_label} contract deployment failed "
                                     f"or couldn't retrieve address!")
            return False
        return True

    def check_complex_tx_status(self, tx_hash: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                print_test_step_fail(f"FAIL: no tx hash for {msg_label} transaction!")
            return False

        self.wait_for_tx_executed(tx_hash)
        return self.check_simple_tx_status(tx_hash, msg_label)

    def check_simple_tx_status(self, tx_hash: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                print_test_step_fail(f"FAIL: no tx hash for {msg_label} transaction!")
            return False

        results = self.api.get_transaction_status(tx_hash)
        if results.is_failed():
            if msg_label:
                print_test_step_fail(f"Transaction to {msg_label} failed!")
            return False
        return True

    def get_tx_operations(self, tx_hash: str) -> list:
        if tx_hash not in TX_CACHE:
            # TODO replace with get_transaction after operations are added to the transaction object
            transaction = self.api.do_get_generic(f'transactions/{tx_hash}')
            TX_CACHE[tx_hash] = transaction     # add it into the hash cache to avoid fetching it again
        else:
            transaction = TX_CACHE[tx_hash]     # take it from hash cache

        if 'operations' in transaction:
            return transaction['operations']

        return []

    def check_for_burn_operation(self, tx_hash: str, token: ESDTToken) -> bool:
        operations = self.get_tx_operations(tx_hash)
        if not operations:
            return False

        for operation in operations:
            if (operation['action'] == "localBurn" or operation['action'] == "burn") \
                    and operation['identifier'] == token.get_full_token_name() \
                    and operation['value'] == str(token.token_amount):
                return True
        return False

    def check_for_add_quantity_operation(self, tx_hash: str, token: ESDTToken) -> bool:
        operations = self.get_tx_operations(tx_hash)
        if not operations:
            return False

        for operation in operations:
            if operation['action'] == "addQuantity" \
                    and operation['identifier'] == token.get_full_token_name() \
                    and operation['value'] == str(token.token_amount):
                return True
        return False

    def check_for_mint_operation(self, tx_hash: str, token: ESDTToken) -> bool:
        operations = self.get_tx_operations(tx_hash)
        if not operations:
            return False

        for operation in operations:
            if operation['action'] == "localMint" \
                    and operation['identifier'] == token.get_full_token_name() \
                    and operation['value'] == str(token.token_amount):
                return True
        return False

    def check_for_transfer_operation(self, tx_hash: str, token: ESDTToken, sender: str = "", destination: str = ""):
        operations = self.get_tx_operations(tx_hash)
        if not operations:
            return False

        for operation in operations:
            if operation['action'] == "transfer" \
                    and operation['identifier'] == token.get_full_token_name() \
                    and operation['value'] == str(token.token_amount) \
                    and (operation['sender'] == sender or sender == "") \
                    and (operation['receiver'] == destination or destination == ""):
                return True
        return False

    def check_for_error_operation(self, tx_hash: str, message: str):
        operations = self.get_tx_operations(tx_hash)
        if not operations:
            return False

        for operation in operations:
            if operation['action'] == "signalError" \
                    and operation['message'] == message:
                return True
        return False


def prepare_contract_call_tx(contract_address: Address, deployer: Account,
                             network_config: NetworkConfig, gas_limit: int,
                             function: str, args: list, value: str = "0") -> Transaction:

    config = DefaultTransactionBuildersConfiguration(chain_id=network_config.chain_id)
    builder = ContractCallBuilder(
        config=config,
        contract=contract_address,
        function_name=function,
        caller=deployer.address,
        call_arguments=args,
        value=value,
        gas_limit=gas_limit,
        nonce=deployer.nonce,
    )
    tx = builder.build()
    tx.signature = deployer.sign_transaction(tx)

    return tx


def prepare_multiesdtnfttransfer_to_endpoint_call_tx(contract_address: Address, user: Account,
                                                     network_config: NetworkConfig, gas_limit: int,
                                                     endpoint: str, endpoint_args: list, tokens: List[ESDTToken],
                                                     value: str = "0") -> Transaction:
    config = DefaultTransactionBuildersConfiguration(chain_id=network_config.chain_id)
    payment_tokens = [token.to_token_payment() for token in tokens]
    builder = ContractCallBuilder(
        config=config,
        contract=contract_address,
        function_name=endpoint,
        caller=user.address,
        call_arguments=endpoint_args,
        value=value,
        gas_limit=gas_limit,
        nonce=user.nonce,
        esdt_transfers=payment_tokens
    )
    tx = builder.build()
    tx.signature = user.sign_transaction(tx)

    return tx


def prepare_multiesdtnfttransfer_tx(destination: Address, user: Account,
                                    network_config: NetworkConfig, gas_limit: int,
                                    tokens: List[ESDTToken], value: str = "0") -> Transaction:
    config = DefaultTransactionBuildersConfiguration(chain_id=network_config.chain_id)
    payment_tokens = [token.to_token_payment() for token in tokens]
    builder = MultiESDTNFTTransferBuilder(
        config=config,
        sender=user.address,
        destination=destination,
        payments=payment_tokens,
        gas_limit=gas_limit,
        value=value,
        nonce=user.nonce,
    )

    tx = builder.build()
    tx.signature = user.sign_transaction(tx)
    return tx


def send_contract_call_tx(tx: Transaction, proxy: ProxyNetworkProvider) -> str:
    try:
        tx_hash = proxy.send_transaction(tx)
        # TODO: check if needed to wait for tx to be processed
        print_transaction_hash(tx_hash, proxy.url, True)
    except Exception as ex:
        print_test_step_fail(f"Failed to send tx due to: {ex}")
        traceback.print_exception(*sys.exc_info())
        return ""

    return tx_hash


def multi_esdt_endpoint_call(function_purpose: str, proxy: ProxyNetworkProvider, gas: int,
                             user: Account, contract: Address, endpoint: str, args: list):
    """ Expected as args:
        type[List[ESDTToken]]: tokens list
        opt: type[str..]: endpoint arguments
    """
    print_warning(function_purpose)
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    tx_hash = ""

    if len(args) < 1:
        print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
        return tx_hash

    ep_args = args[1:] if len(args) != 1 else []
    tx = prepare_multiesdtnfttransfer_to_endpoint_call_tx(contract, user, network_config,
                                                          gas, endpoint, ep_args, args[0])
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def multi_esdt_tx(function_purpose: str, proxy: ProxyNetworkProvider, gas: int,
                  user: Account, dest: Address, args: list):
    """ Expected as args:
        type[ESDTToken...]: tokens list
    """
    print_warning(function_purpose)
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    tx_hash = ""

    if len(args) < 1:
        print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
        return tx_hash

    tx = prepare_multiesdtnfttransfer_tx(dest, user, network_config, gas, args)
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def endpoint_call(function_purpose: str, proxy: ProxyNetworkProvider, gas: int,
                  user: Account, contract: Address, endpoint: str, args: list, value: str = "0"):
    """ Expected as args:
        opt: type[str..]: endpoint arguments
    """
    print_warning(function_purpose)
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call

    tx = prepare_contract_call_tx(contract, user, network_config, gas, endpoint, args, value)
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def get_deployed_address_from_event(tx_result: TransactionOnNetwork) -> str:
    searched_event_id = "SCDeploy"
    deploy_event = tx_result.logs.find_first_or_none_event(searched_event_id)
    if deploy_event is None:
        return ""

    address = deploy_event.address.bech32()
    return address
