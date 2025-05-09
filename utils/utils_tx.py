import sys
import time
import traceback
from multiversx_sdk.core.constants import INTEGER_MAX_NUM_BYTES
from pathlib import Path
from typing import Any, Dict, List, Protocol, Sequence, Tuple, Union

from multiversx_sdk import (Address, ApiNetworkProvider, ProxyNetworkProvider, Transaction)
from multiversx_sdk import Token, TokenTransfer
from multiversx_sdk import CodeMetadata, TransactionOnNetwork
from multiversx_sdk import (TransactionsFactoryConfig, SmartContractTransactionsFactory,
                                                        TransferTransactionsFactory)
from multiversx_sdk import NetworkConfig
from multiversx_sdk import TokenAmountOnNetwork
from multiversx_sdk import find_events_by_identifier
from multiversx_sdk import TransactionEvent
from multiversx_sdk import TransactionStatus
from multiversx_sdk.abi import Abi
from multiversx_sdk.network_providers.errors import TransactionFetchingError
from utils.logger import get_logger
from utils.errors import GenericError
from utils.utils_chain import Account, WrapperAddress, log_explorer_transaction, get_bytecode_codehash
from utils.utils_generic import (get_continue_confirmation, log_step_fail,
                                 log_unexpected_args, split_to_chunks, get_file_from_url_or_path)

TX_CACHE: Dict[str, dict] = {}
logger = get_logger(__name__)

API_TX_DELAY = 3
API_LONG_TX_DELAY = 6
API_TX_STATUS_REFETCH_DELAY = 2
MAX_TX_FETCH_RETRIES = 50 // API_TX_DELAY


class IArgument(Protocol):
    def serialize(self) -> bytes:
        ...


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
    
    def get_token_nonce_hex(self) -> str:
        if not self.token_nonce:
            return ""
        
        nonce_str = "0" + f"{self.token_nonce:x}" if len(f"{self.token_nonce:x}") % 2 else f"{self.token_nonce:x}"
        return nonce_str

    def get_full_token_name(self) -> str:
        if self.token_nonce != 0:
            nonce_str = "0" + f"{self.token_nonce:x}" if len(f"{self.token_nonce:x}") % 2 else f"{self.token_nonce:x}"
            return f"{self.token_id}-{nonce_str}"
        else:
            return f"{self.token_id}"

    @classmethod
    def from_token_transfer(cls, token_transfer: TokenTransfer):
        return cls(token_transfer.token.identifier, token_transfer.token.nonce, token_transfer.amount)

    @classmethod
    def from_amount_on_network(cls, token: TokenAmountOnNetwork):
        return cls(token.token.identifier, token.token.nonce, token.amount)
    
    @classmethod
    def from_full_token_name(cls, token_name: str):
        # token id is everything before the last dash while nonce is everything after
        token_id, token_nonce = token_name.rsplit("-", 1)
        return cls(token_id, int(token_nonce, 16), 0)

    def to_token_transfer(self) -> TokenTransfer:
        return TokenTransfer(Token(self.token_id, self.token_nonce), self.token_amount)


class NetworkProviders:
    def __init__(self, api: str, proxy: str):
        self.api = ApiNetworkProvider(api)
        self.proxy = ProxyNetworkProvider(proxy)
        self.network = self.proxy.get_network_config()

    def _get_initial_tx_status(self, tx_hash: str) -> Union[None, TransactionStatus]:
        # due to API data propagation delays, some transactions may not be indexed yet at the time of the request
        results = None
        while True:
            try:
                results = self.api.get_transaction(tx_hash).status
                break   # if no exception, we got the results
            except (TransactionFetchingError, GenericError) as e:
                logger.debug(f"Transaction not found. Exception: {e.data}")
                if e.data['statusCode'] == 404:
                    # api didn't index the transaction yet, try again after a delay
                    logger.debug(f"Transaction {tx_hash} not indexed yet, "
                                f"trying again in {API_TX_STATUS_REFETCH_DELAY} seconds...")
                    time.sleep(API_TX_STATUS_REFETCH_DELAY)
        return results

    def wait_for_tx_executed(self, tx_hash: str) -> Union[None, TransactionStatus]:
        status = self._get_initial_tx_status(tx_hash)
        if status is None:
            log_step_fail(f"Wait failed. Transaction {tx_hash} not found!")
            return None
        while not status.is_completed:
            time.sleep(API_TX_STATUS_REFETCH_DELAY)
            status = self.api.get_transaction(tx_hash).status
            logger.debug(f"Transaction {tx_hash} status: {status.status}")
        return status

    def check_deploy_tx_status(self, tx_hash: str, address: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                log_step_fail(f"FAIL: no tx hash for {msg_label} contract deployment!")
            return False

        status = self.wait_for_tx_executed(tx_hash)
        if status is None or status.is_failed or address == "":
            if msg_label:
                log_step_fail(f"FAIL: transaction for {msg_label} contract deployment failed "
                                     f"or couldn't retrieve address!")
            return False
        logger.debug(f"Transaction {tx_hash} status: {status.status}")
        return True

    def check_complex_tx_status(self, tx_hash: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                log_step_fail(f"FAIL: no tx hash for {msg_label} transaction!")
            return False

        logger.debug(f"Waiting for transaction {tx_hash} to be executed...")

        # temporary fix for the api returning the wrong status
        # start by avoiding an early false success followed by pending (usually occurring in the first 2 rounds)
        start_time = time.time()
        time.sleep(API_LONG_TX_DELAY)
        status = self.check_simple_tx_status(tx_hash, msg_label)
        if status:
            ready_time = time.time()
            if ready_time - start_time < 2 * self.network.round_duration // 1000:
                # most likely a false positive, wait again
                logger.debug(f"TX status most likely false success, making sure...")
                time.sleep(API_LONG_TX_DELAY)
                status = self.wait_for_tx_executed(tx_hash)

        # we need to check for false success again,
        # because the api may return a fake success at the end followed by fail
        if status:
            logger.debug(f"Making sure tx status is not false success...")
            time.sleep(API_LONG_TX_DELAY)
            status = self.check_simple_tx_status(tx_hash, msg_label)

        return status

    def check_simple_tx_status(self, tx_hash: str, msg_label: str = "") -> bool:
        if not tx_hash:
            if msg_label:
                log_step_fail(f"FAIL: no tx hash for {msg_label} transaction!")
            return False

        results = self.wait_for_tx_executed(tx_hash)
        if results is None:
            log_step_fail(f"FAIL: couldn't retrieve transaction {tx_hash} status!")
            return False

        if results.is_failed:
            if msg_label:
                log_step_fail(f"Transaction to {msg_label} failed!")
            return False
        logger.debug(f"Transaction {tx_hash} status: {results.status}")
        return True

    def get_tx_operations(self, tx_hash: str, no_cache: bool = False) -> list:
        if no_cache or tx_hash not in TX_CACHE:
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

    def wait_for_epoch(self, target_epoch: int, idle_time: int = 30):
        status = self.proxy.get_network_status()
        while status.current_epoch < target_epoch:
            status = self.proxy.get_network_status
            time.sleep(idle_time)

    def wait_for_nonce_in_shard(self, shard_id: int, target_nonce: int, idle_time: int = 6):
        status = self.proxy.get_network_status(shard_id)
        while status.block_nonce < target_nonce:
            status = self.proxy.get_network_status(shard_id)
            time.sleep(idle_time)

    def wait_epochs(self, num_epochs: int, idle_time: int = 30):
        status = self.proxy.get_network_status()
        next_epoch = status.current_epoch + num_epochs
        while status.current_epoch < next_epoch:
            status = self.proxy.get_network_status()
            time.sleep(idle_time)

    def get_round(self) -> int:
        status = self.proxy.get_network_status(0)
        return status.current_round


def _get_flags_from_code_metadata(code_metadata: CodeMetadata) -> tuple[bool, bool, bool, bool]:
    return code_metadata.upgradeable, code_metadata.readable, code_metadata.payable, code_metadata.payable_by_contract


def encode_unsigned_number(arg: int) -> bytes:
    return arg.to_bytes(INTEGER_MAX_NUM_BYTES, byteorder="big", signed=False).lstrip(bytes([0]))


def encode_signed_number(arg: int) -> bytes:
    if arg == 0:
        return b''
    length = ((arg + (arg < 0)).bit_length() + 7 + 1) // 8
    return arg.to_bytes(length, byteorder="big", signed=True)


def _arg_to_buffer(arg: Any) -> bytes:
    if isinstance(arg, str):
        if arg.startswith("erd1"):
            return Address.from_bech32(arg).get_public_key()
        return arg.encode("utf-8")
    if isinstance(arg, int):
        if arg < 0:
            return encode_signed_number(arg)
        return encode_unsigned_number(arg)
    if isinstance(arg, Address):
        return arg.get_public_key()
    return arg


def _args_to_buffers(args: Sequence[Any]) -> List[Any]:
    return [_arg_to_buffer(arg) for arg in args]


def _prep_legacy_args(args: List[Any]) -> List[Any]:
    # This is now an important piece of code, as it's used to serialize the old untyped arguments without changing EVERYTHING
    return _args_to_buffers(args)


def prepare_deploy_tx(deployer: Account, network_config: NetworkConfig,
                      gas_limit: int, contract_file: Path, code_metadata: CodeMetadata,
                      args: list = None, value: int = 0, abi: Abi = None) -> Transaction:
    config = TransactionsFactoryConfig(chain_id=network_config.chain_id)

    logger.debug(f"Deploy arguments: {args}")
    logger.debug(f"Bytecode codehash: {get_bytecode_codehash(contract_file)}")

    factory = SmartContractTransactionsFactory(config, abi) if abi else SmartContractTransactionsFactory(config)
    call_args = _prep_legacy_args(args) if not abi else args
    upgradeable, readable, payable, payable_by_contract = _get_flags_from_code_metadata(code_metadata)
    tx = factory.create_transaction_for_deploy(
        deployer.address,
        contract_file.read_bytes(),
        gas_limit,
        call_args,
        native_transfer_amount=value,
        is_upgradeable=upgradeable,
        is_readable=readable,
        is_payable=payable,
        is_payable_by_sc=payable_by_contract,
    )
    tx.nonce = deployer.nonce
    tx.signature = deployer.sign_transaction(tx)

    return tx


def prepare_upgrade_tx(contract_address: Address, deployer: Account, network_config: NetworkConfig,
                       gas_limit: int, contract_file: Path, code_metadata: CodeMetadata,
                       args: list = None, value: int = 0, abi: Abi = None) -> Transaction:
    config = TransactionsFactoryConfig(chain_id=network_config.chain_id)

    logger.debug(f"Upgrade arguments: {args}")
    logger.debug(f"Bytecode codehash: {get_bytecode_codehash(contract_file)}")

    factory = SmartContractTransactionsFactory(config, abi) if abi else SmartContractTransactionsFactory(config)
    call_args = _prep_legacy_args(args) if not abi else args
    upgradeable, readable, payable, payable_by_contract = _get_flags_from_code_metadata(code_metadata)
    tx = factory.create_transaction_for_upgrade(
        deployer.address,
        contract_address,
        contract_file.read_bytes(),
        gas_limit,
        call_args,
        native_transfer_amount=value,
        is_upgradeable=upgradeable,
        is_readable=readable,
        is_payable=payable,
        is_payable_by_sc=payable_by_contract,
    )
    tx.nonce = deployer.nonce
    tx.signature = deployer.sign_transaction(tx)

    return tx


def prepare_contract_call_tx(contract_address: Address, deployer: Account,
                             network_config: NetworkConfig, gas_limit: int,
                             function: str, args: list, value: int = 0, abi: Abi = None) -> Transaction:

    config = TransactionsFactoryConfig(chain_id=network_config.chain_id)
    
    logger.debug(f"Contract call arguments: {args}")
    factory = SmartContractTransactionsFactory(config, abi) if abi else SmartContractTransactionsFactory(config)
    call_args = _prep_legacy_args(args) if not abi else args

    tx = factory.create_transaction_for_execute(
        deployer.address,
        contract_address,
        function,
        gas_limit,
        call_args,
        int(value)
    )
    tx.nonce = deployer.nonce
    tx.signature = deployer.sign_transaction(tx)

    return tx


def prepare_multiesdtnfttransfer_to_endpoint_call_tx(contract_address: Address, user: Account,
                                                     network_config: NetworkConfig, gas_limit: int,
                                                     endpoint: str, endpoint_args: list, tokens: List[ESDTToken],
                                                     value: int = 0, abi: Abi = None) -> Transaction:
    config = TransactionsFactoryConfig(chain_id=network_config.chain_id)
    payment_tokens = [token.to_token_transfer() for token in tokens]
    
    logger.debug(f"Contract call arguments: {endpoint_args}")

    factory = SmartContractTransactionsFactory(config, abi) if abi else SmartContractTransactionsFactory(config)
    call_args = _prep_legacy_args(endpoint_args) if not abi else endpoint_args
    tx = factory.create_transaction_for_execute(
        user.address,
        contract_address,
        endpoint,
        gas_limit,
        call_args,
        int(value),
        payment_tokens
    )
    tx.nonce = user.nonce
    tx.signature = user.sign_transaction(tx)

    return tx


def prepare_multiesdtnfttransfer_tx(destination: Address, user: Account,
                                    network_config: NetworkConfig, gas_limit: int,
                                    tokens: List[ESDTToken], value: int = 0) -> Transaction:
    """
    TODO: cleanup: gas_limit and value are ignored for this transaction type
    """
    config = TransactionsFactoryConfig(chain_id=network_config.chain_id)
    payment_tokens = [token.to_token_transfer() for token in tokens]

    factory = TransferTransactionsFactory(config)
    tx = factory.create_transaction_for_esdt_token_transfer(
        user.address,
        destination,
        payment_tokens
    )
    tx.nonce = user.nonce
    tx.signature = user.sign_transaction(tx)
    return tx


def send_deploy_tx(tx: Transaction, proxy: ProxyNetworkProvider) -> str:
    try:
        tx_hash = proxy.send_transaction(tx).hex()
        log_explorer_transaction(tx_hash, proxy.url)
    except Exception as ex:
        log_step_fail(f"Failed to deploy due to: {ex}")
        traceback.print_exception(*sys.exc_info())
        tx_hash = ""

    return tx_hash


def send_contract_call_tx(tx: Transaction, proxy: ProxyNetworkProvider) -> str:
    try:
        tx_hash = proxy.send_transaction(tx).hex()
        # TODO: check if needed to wait for tx to be processed
        log_explorer_transaction(tx_hash, proxy.url)
    except Exception as ex:
        log_step_fail(f"Failed to send tx due to: {ex}")
        traceback.print_exception(*sys.exc_info())
        return ""

    return tx_hash


def multi_esdt_endpoint_call(function_purpose: str, proxy: ProxyNetworkProvider, gas: int,
                             user: Account, contract: Address, endpoint: str, args: list, value: int = 0, abi: Abi = None):
    """ Expected as args:
        type[List[ESDTToken]]: tokens list
        opt: type[str..]: endpoint arguments
    """
    logger.debug(function_purpose)
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    tx_hash = ""

    if len(args) < 1:
        log_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
        return tx_hash

    ep_args = args[1:] if len(args) != 1 else []
    tx = prepare_multiesdtnfttransfer_to_endpoint_call_tx(contract, user, network_config,
                                                          gas, endpoint, ep_args, args[0], value, abi)
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def multi_esdt_transfer(proxy: ProxyNetworkProvider, gas: int, user: Account, dest: Address, args: list):
    """ Expected as args:
        type[ESDTToken...]: tokens list
    """
    logger.debug(f"Sending multi esdt transfer to {dest}")
    logger.debug(f"Args: {args}")
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    tx_hash = ""

    if len(args) < 1:
        log_unexpected_args(f"send multi esdt transfer", args)
        return tx_hash

    tx = prepare_multiesdtnfttransfer_tx(dest, user, network_config, gas, args)
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def endpoint_call(proxy: ProxyNetworkProvider, gas: int, user: Account, contract: Address, endpoint: str, args: list,
                  value: int = 0, abi: Abi = None):
    """ Expected as args:
        opt: type[str..]: endpoint arguments
    """
    logger.debug(f"Calling {endpoint} at {contract.bech32()}")
    logger.debug(f"Args: {args}")
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call

    tx = prepare_contract_call_tx(contract, user, network_config, gas, endpoint, args, value, abi)
    tx_hash = send_contract_call_tx(tx, proxy)
    user.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def deploy(contract_label: str, proxy: ProxyNetworkProvider, gas: int,
           owner: Account, bytecode_path: str, metadata: CodeMetadata, args: list, value: int = 0, abi: Abi = None) -> Tuple[str, str]:
    logger.debug(f"Deploy {contract_label}")
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    tx_hash, contract_address = "", ""
    processed_bytecode_path = get_file_from_url_or_path(bytecode_path)

    tx = prepare_deploy_tx(owner, network_config, gas, processed_bytecode_path, metadata, args, value, abi)
    tx_hash = send_deploy_tx(tx, proxy)

    if tx_hash:
        contract_address = get_deployed_address_from_tx(tx_hash, proxy)
        owner.nonce += 1

    return tx_hash, contract_address


def upgrade_call(contract_label: str, proxy: ProxyNetworkProvider, gas: int,
                 owner: Account, contract: Address, bytecode_path: str, metadata: CodeMetadata,
                 args: list, value: int = 0, abi: Abi = None) -> str:
    logger.debug(f"Upgrade {contract_label} contract")
    network_config = proxy.get_network_config()     # TODO: find solution to avoid this call
    processed_bytecode_path = get_file_from_url_or_path(bytecode_path)

    tx = prepare_upgrade_tx(contract, owner, network_config, gas, processed_bytecode_path, metadata, args, value, abi)
    tx_hash = send_contract_call_tx(tx, proxy)
    owner.nonce += 1 if tx_hash != "" else 0

    return tx_hash


def check_error_from_event(tx_result: TransactionOnNetwork) -> bool:
    searched_event_id = ["signalError", "internalVMErrors"]
    for event_id in searched_event_id:
        error_event = find_events_by_identifier(tx_result, event_id)
        if error_event is not None:
            return True
    return False


def get_event_from_tx(event_id: str, tx_hash: str, proxy: ProxyNetworkProvider) -> Union[TransactionEvent, None]:
    try:
        time.sleep(API_TX_DELAY)
        while not proxy.get_transaction_status(tx_hash).is_completed:
            time.sleep(6)

        if not proxy.get_transaction_status(tx_hash).is_successful:
            logger.debug(f"Transaction {tx_hash} failed.")
            return None

        tx = proxy.get_transaction(tx_hash)
        event = find_events_by_identifier(tx,event_id)[0]

        # if event is still not available, but the transaction was successful, try fetching again until either event is
        # available or transaction is failed
        # timeout after MAX_TX_FETCH_RETRIES
        attempt = 0
        while event is None and attempt < MAX_TX_FETCH_RETRIES:
            attempt += 1
            if check_error_from_event(tx):
                logger.debug(f"Transaction {tx_hash} failed.")
                return None
            time.sleep(API_TX_DELAY)
            tx = proxy.get_transaction(tx_hash)
            event = find_events_by_identifier(tx,event_id)[0]

    except Exception as ex:
        logger.exception(f"Failed to get event due to: {ex}")
        event = None

    return event


def get_deployed_address_from_tx(tx_hash: str, proxy: ProxyNetworkProvider) -> str:
    if "localhost" in proxy.url:
        proxy.do_post_generic(f"{proxy.url}/simulator/generate-blocks/1", {})
    event = get_event_from_tx("SCDeploy", tx_hash, proxy)
    if event is None:
        return ""
    return event.address.to_bech32()


def broadcast_transactions(transactions: List[Transaction], proxy: ProxyNetworkProvider,
                           chunk_size: int, sleep: int = 0, confirm_yes: bool = False):
    chunks = list(split_to_chunks(transactions, chunk_size))

    logger.debug(f"{len(transactions)} transactions have been prepared, in {len(chunks)} chunks of size {chunk_size}")
    get_continue_confirmation(confirm_yes)

    chunk_index = 0
    hashes = []
    for chunk in chunks:
        logger.debug(f"... chunk {chunk_index} out of {len(chunks)}")

        num_sent, sent_hashes = proxy.send_transactions(chunk)
        if len(chunk) != num_sent:
            logger.debug(f"sent {num_sent} instead of {len(chunk)}")

        chunk_index += 1
        hashes.extend([hash.hex() for hash in sent_hashes])

        if sleep is not None:
            time.sleep(sleep)

    logger.debug(f"Hashes: {hashes}")
    return hashes
