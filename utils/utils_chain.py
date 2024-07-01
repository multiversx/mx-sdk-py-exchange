import base64
import time
from hashlib import blake2b
from multiprocessing.dummy import Pool
from os import path
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, cast

from multiversx_sdk import (Address, AddressComputer, Message, MessageComputer,
                            ProxyNetworkProvider, Transaction,
                            TransactionComputer, UserSigner)
from multiversx_sdk.wallet.pem_entry import PemEntry
from multiversx_sdk.core.interfaces import ISignature
from multiversx_sdk.network_providers.tokens import (
    FungibleTokenOfAccountOnNetwork, NonFungibleTokenOfAccountOnNetwork)

from utils import utils_generic
from utils.logger import get_logger

logger = get_logger(__name__)


class WrapperAddress(Address):
    def __init__(self, address: str):
        self_instance = Address.new_from_bech32(address)
        super().__init__(self_instance.pubkey, "erd")

    @classmethod
    def from_hex(cls, value: str, hrp: str = "erd") -> 'Address':
        self_instance = Address.new_from_hex(value, hrp)
        return cls(self_instance.bech32())
    
    def get_shard(self) -> int:
        return AddressComputer().get_shard_of_address(self)

    def __str__(self):
        return self.to_bech32()

    def __repr__(self):
        return self.to_bech32()


class Account:
    def __init__(self,
                 address: Optional[str] = None,
                 pem_file: Optional[str] = None,
                 pem_index: int = 0,
                 key_file: str = "",
                 password: str = "",
                 ledger: bool = False):
        self.address = WrapperAddress(address) if address else None
        self.pem_file = pem_file
        self.pem_index = int(pem_index)
        self.nonce: int = 0
        self.ledger = ledger

        if self.pem_file:
            self.signer = UserSigner.from_pem_file(Path(self.pem_file), self.pem_index)
            self.address = WrapperAddress.from_hex(self.signer.get_pubkey().hex(), "erd")
        elif key_file and password:
            self.signer = UserSigner.from_wallet(Path(key_file), password)
            self.address = WrapperAddress.from_hex(self.signer.get_pubkey().hex(), "erd")

    def sync_nonce(self, proxy: ProxyNetworkProvider):
        if self.address:
            self.nonce = proxy.get_account(self.address).nonce
            logger.debug(f"Account.sync_nonce() done: {self.nonce}")
        else:
            raise Exception("Account.address is not set.")

    def sign_transaction(self, transaction: Transaction) -> ISignature:
        assert self.signer is not None
        tx_computer = TransactionComputer()
        return self.signer.sign(tx_computer.compute_bytes_for_signing(transaction))
    
    def sign_message(self, data: bytes) -> ISignature:
        assert self.signer is not None
        message = Message(data)
        msg_computer = MessageComputer()
        serialized_message = msg_computer.compute_bytes_for_signing(message)
        signature = self.signer.sign(serialized_message)

        logger.debug(f"Account.sign_message(): raw_data_to_sign = {data.hex()}, message_data_to_sign = {serialized_message.hex()}, signature = {signature.hex()}")
        return signature


class BunchOfAccounts:
    def __init__(self, items: List[Account]) -> None:
        self.accounts = items

    @classmethod
    def load_accounts_from_files(cls, files: List[Path]):
        loaded: List[Account] = []

        for file in files:
            # Assume multi-account PEM files.
            pem_entries = len(PemEntry.from_text_all(file.read_text()))
            for index in range(pem_entries):
                account = Account(pem_file=str(file), pem_index=index)
                loaded.append(account)

        # Perform some deduplication (workaround)
        addresses: Set[str] = set()
        deduplicated: List[Account] = []
        for account in loaded:
            address = account.address.to_bech32()
            if address not in addresses:
                addresses.add(address)
                deduplicated.append(account)

        print(f"loaded {len(deduplicated)} accounts from {len(files)} PEM files.")
        return BunchOfAccounts(deduplicated)

    def get_account(self, address: Address) -> Account:
        return next(account for account in self.accounts if account.address.to_bech32() == address.to_bech32())

    def get_all(self) -> List[Account]:
        return self.accounts

    def __len__(self):
        return len(self.accounts)

    def get_not_in_shard(self, shard: int):
        address_computer = AddressComputer()
        return [account for account in self.accounts if address_computer.get_shard_of_address(account.address) != shard]

    def get_in_shard(self, shard: int) -> List[Account]:
        address_computer = AddressComputer()
        return [account for account in self.accounts if address_computer.get_shard_of_address(account.address) == shard]

    def sync_nonces(self, proxy: ProxyNetworkProvider):
        logger.debug(f"Sync nonces for {len(self.accounts)} accounts")

        def sync_nonce(account: Account):
            account.sync_nonce(proxy)

        Pool(100).map(sync_nonce, self.accounts)

        logger.debug("Done")

    def store_nonces(self, file: str):
        # We load the previously stored data in order to display a nice delta (for debugging purposes)
        data: Any = utils_generic.read_json_file(file) or dict() if path.exists(file) else dict()

        for account in self.accounts:
            address = account.address.to_bech32()
            previous_nonce = data.get(address, 0)
            current_nonce = account.nonce
            data[address] = current_nonce

            if previous_nonce != current_nonce:
                print("Nonce delta", current_nonce - previous_nonce, "for", address)

        utils_generic.write_json_file(file, data)

    def load_nonces(self, file: Path):
        if not path.exists(file):
            print("no nonces to load")
            return

        data = utils_generic.read_json_file(file) or dict()

        for account in self.accounts:
            address = account.address.to_bech32()
            account.nonce = data.get(address, 0)

        print("Loaded nonces for", len(self.accounts), "accounts")


def prevent_spam_crash_elrond_proxy_go():
    time.sleep(1)


def hex_to_base64(s):
    return base64.b64encode(s.encode('hex'))


def base64_to_hex(b):
    return base64.b64decode(b).hex()


def string_to_base64(s):
    return base64.b64encode(s.encode('utf-8'))


def base64_to_string(b):
    return base64.b64decode(b).decode('utf-8')


def denominated_amount(amount):
    return amount / 1000000000000000000


def nominated_amount(amount):
    return amount * 1000000000000000000


def dec_to_padded_hex(i):
    return "0" + f"{i:x}" if len(f"{i:x}") % 2 else f"{i:x}"


def string_to_hex(s):
    return s.encode("ascii").hex()


def hex_to_string(s):
    return bytearray.fromhex(s).decode("utf-8")


def get_bytecode_codehash(bytecode_path: Path) -> str:
    bytecode = bytecode_path.read_bytes()
    code_hash = blake2b(bytecode, digest_size=32).hexdigest()
    return code_hash


def _get_all_esdts_for_account(address: str, proxy: ProxyNetworkProvider):
    # TODO: this is only to support old code that needs to be refactored to mxpy
    url = f'address/{address}/esdt'
    response = proxy.do_get_generic(url)
    prevent_spam_crash_elrond_proxy_go()

    esdts = response.get('esdts')
    return esdts


def _get_fungibles_from_esdts(items: Dict):
    esdts = [items[key] for key in items.keys() if items[key].get('nonce', '') == '']
    tokens = map(FungibleTokenOfAccountOnNetwork.from_http_response, esdts)
    return tokens


def _get_non_fungibles_from_esdts(items: Dict):
    nfts = [items[key] for key in items.keys() if items[key].get('nonce', -1) > 0]
    tokens = map(NonFungibleTokenOfAccountOnNetwork.from_http_response, nfts)
    return tokens


def get_all_token_nonces_details_for_account(in_token: str, address: str, proxy: ProxyNetworkProvider):
    """
    Result list will contain all in_tokens with following indexes:
        ['nonce']
        ['balance']
        ['tokenIdentifier']
        ['attributes'] - if existent
        ['creator']
    """
    # TODO: to refactor into supporting the new mxpy sdk
    esdts = cast(List, _get_all_esdts_for_account(address, proxy))
    filtered_tokens_list = []

    for token in esdts:
        if in_token not in token:
            continue
        if 'nonce' not in esdts[token]:
            esdts[token]['nonce'] = 0
        filtered_tokens_list.append(esdts[token])

    return filtered_tokens_list


def get_current_tokens_for_address(address: Address, proxy: ProxyNetworkProvider):
    # TODO: This is a temporary adaptor between new specs of mxpy sdk and old specs of the rest of the code.
    # Went with this granular approach to reduce api calls (one call for all esdts instead
    # of two calls for fungibles and non-fungibles).
    esdts = _get_all_esdts_for_account(address.bech32(), proxy)
    fungibles = _get_fungibles_from_esdts(esdts)
    non_fungibles = _get_non_fungibles_from_esdts(esdts)

    tokens_dict = {}
    for token in fungibles:
        identifier = token.identifier
        tokens_dict[identifier] = {
            'nonce': 0,
            'balance': token.balance,
        }
    for token in non_fungibles:
        identifier = token.collection
        tokens_dict[identifier] = {
            'nonce': token.nonce,
            'balance': token.balance
        }

    return tokens_dict


def get_token_details_for_address(in_token: str, address: str, proxy: ProxyNetworkProvider, underlying_tk: str = "") -> Tuple[int, int, str]:
    """Returns nonce, amount, attributes_hex"""
    # TODO: This is a temporary adaptor between new specs of mxpy sdk and old specs of the rest of the code.
    prevent_spam_crash_elrond_proxy_go()
    tokens = cast(List, _get_all_esdts_for_account(address, proxy))

    for token in tokens:
        if in_token not in token:
            continue

        attributes_hex = ""
        if 'attributes' in tokens[token]:
            attributes_hex = base64_to_hex(tokens[token]['attributes'])

        underlying_tk_exists = False
        if underlying_tk:
            underlying_tk_hex = underlying_tk.encode('utf-8').hex()
            if underlying_tk_hex in attributes_hex:
                underlying_tk_exists = True

        if underlying_tk == "" or underlying_tk_exists:
            nonce = tokens[token]['nonce'] if "nonce" in tokens[token] else 0
            amount = int(tokens[token]['balance'])
            return nonce, amount, attributes_hex

    print("Token not found:", in_token)
    return 0, 0, ""


def build_token_name(owner: Address, prefix: str = ""):
    prefix = prefix or ""
    prefix = (prefix + owner.bech32()[4:14]).upper()
    hex = "0x" + prefix.encode("utf8").hex()
    return prefix, hex


def build_token_ticker(owner: Address, prefix: str = ""):
    prefix = (prefix + owner.bech32()[4:8]).upper()
    hex = "0x" + prefix.encode("utf8").hex()
    return prefix, hex


def decode_merged_attributes(attributes_hex: str, decode_struct: dict) -> dict:
    def slide_indexes(j, no_bytes: int):
        index_f = j
        index_l = j + (no_bytes * 2)
        return index_f, index_l

    def fixed_length_primitive(attributes: str, start_index: int, primitive_len: int):
        index_first, index_last = slide_indexes(start_index, primitive_len)
        result_hex = attributes[index_first:index_last]
        result_int = int(result_hex, 16)
        return result_int, result_hex, index_last

    def u8(attributes: str, start_index: int):
        result, _, index = fixed_length_primitive(attributes, start_index, 1)
        return result, index

    def u16(attributes: str, start_index: int):
        result, _, index = fixed_length_primitive(attributes, start_index, 2)
        return result, index

    def u32(attributes: str, start_index: int):
        result, _, index = fixed_length_primitive(attributes, start_index, 4)
        return result, index

    def u64(attributes: str, start_index: int):
        result, _, index = fixed_length_primitive(attributes, start_index, 8)
        return result, index

    def biguint(attributes: str, start_index: int):
        payload_size, _, index = fixed_length_primitive(attributes, start_index, 4)
        result = 0
        if payload_size:
            result, _, index = fixed_length_primitive(attributes, index, payload_size)
        return result, index
    
    def bigint(attributes: str, start_index: int):
        payload_size, _, index = fixed_length_primitive(attributes, start_index, 4)
        result = 0
        if payload_size:
            _, hex, index = fixed_length_primitive(attributes, index, payload_size)
            result = int.from_bytes(bytes.fromhex(hex), byteorder="big", signed=True)
        return result, index

    def string(attributes: str, start_index: int):
        payload_size, _, index = fixed_length_primitive(attributes, start_index, 4)
        result_string = ""
        if payload_size:
            _, result, index = fixed_length_primitive(attributes, index, payload_size)
            result_string = bytearray.fromhex(result).decode()
        return result_string, index
    
    def address(attributes: str, start_index: int):
        _, result, index = fixed_length_primitive(attributes, start_index, 32)
        bech32 = Address.new_from_hex(result, "erd").to_bech32()
        return bech32, index

    results_dict = {}
    sliding_index = 0
    implemented_primitives = {'u8': u8,
                              'u16': u16,
                              'u32': u32,
                              'u64': u64,
                              'biguint': biguint,
                              'bigint': bigint,
                              'string': string,
                              'address': address}

    for key, primitive in decode_struct.items():
        if type(primitive) is dict:
            # primitive now becomes a dictionary of keys/primitives
            list_decode_fields = primitive
            list_len, sliding_index = implemented_primitives['u32'](attributes_hex, sliding_index)
            decoded_list = []
            for _ in range(list_len):
                decoded_list_fields = {}
                for field_key, field_primitive in list_decode_fields.items():
                    if field_primitive in implemented_primitives:
                        decoded_result, sliding_index = implemented_primitives[field_primitive](
                            attributes_hex, sliding_index)
                        decoded_list_fields[field_key] = decoded_result

                decoded_list.append(decoded_list_fields)

            results_dict[key] = decoded_list

        elif primitive in implemented_primitives:
            decoded_result, sliding_index = implemented_primitives[primitive](attributes_hex, sliding_index)
            results_dict[key] = decoded_result

    return results_dict


def encode_merged_attributes(encode_data: dict, encode_struct: dict):
    def u8(data):
        padding = 2
        return f"{data:0{padding}X}"

    def u64(data):
        padding = 16
        return f"{data:0{padding}X}"

    def biguint(data):
        padding_data = 2
        padding_length = 8
        hex_data = f"{data:0{padding_data}X}"
        data_length = len(hex_data) // 2
        hex_data_length = f"{data_length:0{padding_length}X}"
        return f"{hex_data_length}{hex_data}"

    def string(data):
        padding_data = 2
        padding_length = 8
        hex_data = data.encode("utf-8").hex()
        data_length = len(hex_data) // 2
        hex_data_length = f"{data_length:0{padding_length}X}"
        return f"{hex_data_length}{hex_data}"

    implemented_primitives = {'u8': u8,
                              'u64': u64,
                              'biguint': biguint,
                              'string': string}
    encoded_data = ""
    for key, primitive in encode_struct.items():
        if primitive in implemented_primitives:
            encoded_data += implemented_primitives[primitive](encode_data[key])

    return encoded_data


def log_explorer(proxy: str, name: str, path: str, details: str):
    networks = {
        "https://testnet-gateway.multiversx.com":
            ("MultiversX Testnet Explorer", "https://testnet-explorer.multiversx.com"),
        "https://devnet-gateway.multiversx.com":
            ("MultiversX Devnet Explorer", "https://devnet-explorer.multiversx.com"),
        "https://gateway.multiversx.com":
            ("MultiversX Mainnet Explorer", "https://explorer.multiversx.com"),
        "https://proxy-shadowfork-one.elrond.ro":
            ("MVX SF1 Explorer", "https://testnet.internal-explorer.multiversx.com/testnet-tc-shadowfork-one"),
        "https://proxy-shadowfork-three.elrond.ro":
            ("MVX SF3 Explorer", "https://testnet.internal-explorer.multiversx.com/testnet-tc-shadowfork-three"),
        "https://proxy-shadowfork-four.elrond.ro":
            ("MVX SF4 Explorer", "https://testnet.internal-explorer.multiversx.com/testnet-tc-shadowfork-four"),
    }
    try:
        explorer_name, explorer_url = networks[proxy]
        logger.info(f"View this {name} in the {explorer_name}: {explorer_url}/{path}/{details}")
    except KeyError:
        logger.info(f"No explorer known for {proxy}. {name} raw path: {proxy}/transaction/{details}")


def log_explorer_contract_address(address: str, proxy_url: str):
    log_explorer(proxy_url, "contract address", "accounts", address)


def log_explorer_transaction(tx_hash: str, proxy_url: str):
    log_explorer(proxy_url, "transaction", "transactions", tx_hash)
