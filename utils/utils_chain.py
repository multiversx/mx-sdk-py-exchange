import base64
import time
import logging
from multiprocessing import Pool
from os import path
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, cast

from multiversx_sdk_network_providers.tokens import FungibleTokenOfAccountOnNetwork, NonFungibleTokenOfAccountOnNetwork

from contracts.contract_identities import FarmContractVersion
from multiversx_sdk_core import Address, Transaction
from multiversx_sdk_core.interfaces import ISignature
from multiversx_sdk_wallet import UserSigner, pem_format
from multiversx_sdk_network_providers import ProxyNetworkProvider

from utils import utils_generic

logger = logging.getLogger("accounts")


class WrapperAddress(Address):
    def __init__(self, address: str):
        self_instance = Address.from_bech32(address)
        super().__init__(self_instance.pubkey, "erd")

    def __str__(self):
        return self.bech32()

    def __repr__(self):
        return self.bech32()


class Account:
    def __init__(self,
                 address: str = None,
                 pem_file: Optional[str] = None,
                 pem_index: int = 0,
                 key_file: str = "",
                 password: str = "",
                 ledger: bool = False):
        self.address = Address.from_bech32(address) if address else None
        self.pem_file = pem_file
        self.pem_index = int(pem_index)
        self.nonce: int = 0
        self.ledger = ledger

        if self.pem_file:
            self.signer = UserSigner.from_pem_file(Path(self.pem_file), self.pem_index)
            self.address = Address.from_hex(self.signer.get_pubkey().hex(), "erd")
        elif key_file and password:
            self.signer = UserSigner.from_wallet(Path(key_file), password)
            self.address = Address.from_hex(self.signer.get_pubkey().hex(), "erd")

    def sync_nonce(self, proxy: ProxyNetworkProvider):
        logger.info("Account.sync_nonce()")
        self.nonce = proxy.get_account(self.address).nonce
        logger.info(f"Account.sync_nonce() done: {self.nonce}")

    def sign_transaction(self, transaction: Transaction) -> ISignature:
        return self.signer.sign(transaction)


class BunchOfAccounts:
    def __init__(self, items: List[Account]) -> None:
        self.accounts = items

    @classmethod
    def load_accounts_from_files(cls, files: List[Path]):
        loaded: List[Account] = []

        for file in files:
            # Assume multi-account PEM files.
            pem_entries = len(pem_format.parse_all(file))
            for index in range(pem_entries):
                account = Account(pem_file=str(file), pem_index=index)
                loaded.append(account)

        # Perform some deduplication (workaround)
        addresses: Set[str] = set()
        deduplicated: List[Account] = []
        for account in loaded:
            address = account.address.bech32()
            if address not in addresses:
                addresses.add(address)
                deduplicated.append(account)

        print(f"loaded {len(deduplicated)} accounts from {len(files)} PEM files.")
        return BunchOfAccounts(deduplicated)

    def get_account(self, address: Address) -> Account:
        return next(account for account in self.accounts if account.address.bech32() == address.bech32())

    def get_all(self) -> List[Account]:
        return self.accounts

    def __len__(self):
        return len(self.accounts)

    def get_not_in_shard(self, shard: int):
        return [account for account in self.accounts if account.address.get_shard() != shard]

    def get_in_shard(self, shard: int) -> List[Account]:
        return [account for account in self.accounts if account.address.get_shard() == shard]

    def sync_nonces(self, proxy: ProxyNetworkProvider):
        print("Sync nonces for", len(self.accounts), "accounts")

        def sync_nonce(account: Account):
            account.sync_nonce(proxy)

        Pool(100).map(sync_nonce, self.accounts)

        print("Done")

    def store_nonces(self, file: str):
        # We load the previously stored data in order to display a nice delta (for debugging purposes)
        data: Any = utils_generic.read_json_file(file) or dict() if path.exists(file) else dict()

        for account in self.accounts:
            address = account.address.bech32()
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
            address = account.address.bech32()
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


def get_token_details_for_address(in_token: str, address: str, proxy: ProxyNetworkProvider, underlying_tk: str = ""):
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


class DecodedTokenAttributes:
    rewards_per_share: int
    original_entering_epoch: int
    entering_epoch: int
    apr_multiplier: int
    locked_rewards: bool
    initial_farming_amount: int
    compounded_rewards: int
    current_farm_amount: int

    def __init__(self, attributes_hex: str, attr_version: FarmContractVersion = None):
        def slide_indexes(i, j, no_bytes: int):
            index_f = j
            index_l = j + (no_bytes * 2)
            return index_f, index_l

        self.rewards_per_share = 0
        self.apr_multiplier = 0
        self.locked_rewards = False
        self.current_farm_amount = 0
        self.compounded_rewards = 0
        self.initial_farming_amount = 0

        # decode rewards per share BigUInt
        index_first = 0
        index_last = 8
        payload_size = int(attributes_hex[index_first:index_last], 16)
        if payload_size:
            index_first, index_last = slide_indexes(index_first, index_last, payload_size)
            self.rewards_per_share = int(attributes_hex[index_first:index_last], 16)

        # decode original entering epoch U64
        index_first, index_last = slide_indexes(index_first, index_last, 8)
        self.entering_epoch = int(attributes_hex[index_first:index_last], 16)

        # decode entering epoch U64
        index_first, index_last = slide_indexes(index_first, index_last, 8)
        self.original_entering_epoch = int(attributes_hex[index_first:index_last], 16)

        if attr_version == FarmContractVersion.V12:
            # decode APR multiplier U8
            index_first, index_last = slide_indexes(index_first, index_last, 1)
            self.apr_multiplier = int(attributes_hex[index_first:index_last], 16)

            # decode Locked Rewards U8
            index_first, index_last = slide_indexes(index_first, index_last, 1)
            self.locked_rewards = bool(int(attributes_hex[index_first:index_last], 16))

        # decode Initial Farming amount BigUInt
        index_first, index_last = slide_indexes(index_first, index_last, 4)
        payload_size = int(attributes_hex[index_first:index_last], 16)
        if payload_size:
            index_first, index_last = slide_indexes(index_first, index_last, payload_size)
            self.initial_farming_amount = int(attributes_hex[index_first:index_last], 16)

        # decode Compounded Rewards BigUInt
        index_first, index_last = slide_indexes(index_first, index_last, 4)
        payload_size = int(attributes_hex[index_first:index_last], 16)
        if payload_size:
            index_first, index_last = slide_indexes(index_first, index_last, payload_size)
            self.compounded_rewards = int(attributes_hex[index_first:index_last], 16)

        # decode Current Farm amount BigUInt
        index_first, index_last = slide_indexes(index_first, index_last, 4)
        payload_size = int(attributes_hex[index_first:index_last], 16)
        if payload_size:
            index_first, index_last = slide_indexes(index_first, index_last, payload_size)
            self.current_farm_amount = int(attributes_hex[index_first:index_last], 16)


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

    def string(attributes: str, start_index: int):
        payload_size, _, index = fixed_length_primitive(attributes, start_index, 4)
        result_string = ""
        if payload_size:
            _, result, index = fixed_length_primitive(attributes, index, payload_size)
            result_string = bytearray.fromhex(result).decode()
        return result_string, index

    results_dict = {}
    sliding_index = 0
    implemented_primitives = {'u8': u8,
                              'u16': u16,
                              'u32': u32,
                              'u64': u64,
                              'biguint': biguint,
                              'string': string}

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


def print_transaction_hash(hash: str, proxy: str, debug_level=True):
    explorer = ""
    if proxy == "https://testnet-gateway.multiversx.com":
        explorer = "https://testnet-explorer.multiversx.com"
    if proxy == "https://devnet-gateway.multiversx.com":
        explorer = "https://devnet-explorer.multiversx.com"
    if proxy == "https://gateway.multiversx.com":
        explorer = "https://explorer.multiversx.com"

    if debug_level:
        print(explorer+"/transactions/"+hash)

