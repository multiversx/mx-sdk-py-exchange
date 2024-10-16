
from multiprocessing import Pool
import os
import time
import json
from typing import Any, List, Optional, Union
from tools.scripts import esdt_pb2
from multiversx_sdk import GenericError
from multiversx_sdk_network_providers import ApiNetworkProvider, ProxyNetworkProvider
from multiversx_sdk_core import Address
from multiversx_sdk_network_providers.config import DefaultPagination
from multiversx_sdk_network_providers.tokens import NonFungibleTokenOfAccountOnNetwork
from multiversx_sdk_network_providers.transactions import TransactionOnNetwork
import requests
from requests.adapters import HTTPAdapter, Retry
from utils.utils_chain import base64_to_hex, base64_to_string, string_to_hex, decode_merged_attributes
from utils.decoding_structures import LKMEX_ATTRIBUTES_V2, LKMEX_ATTRIBUTES_V1
import sys

from multiversx_sdk_network_providers.interface import IAddress, IPagination

API_URL = "https://next-api.multiversx.com"
DEEP_PROXY_URL = "https://***REMOVED***deep-history.multiversx.com:4443/mainnet-gateway"
LOCKED_ASSET_CONTRACT = Address.from_bech32("erd1qqqqqqqqqqqqqpgqjpt0qqgsrdhp2xqygpjtfrpwf76f9nvg2jpsg4q7th")
SAVED_FILE = "txs.json"
BQ_FILE = "bq-results-3.json"


class CustomPagination(IPagination):
    def __init__(self, start_timestamp: int, before_timestamp: int, size: int):
        self.start = start_timestamp
        self.before = before_timestamp
        self.size = size

    def get_start(self) -> int:
        return self.start
    
    def get_before(self) -> int:
        return self.before

    def get_size(self) -> int:
        return self.size
    

class ResultsFlags:
    def __init__(self, with_sc_results: bool, with_operations: bool, with_logs: bool):
        self.with_sc_results = with_sc_results
        self.with_operations = with_operations
        self.with_logs = with_logs

    def get_flags(self) -> str:
        flags = f"&withScResults={str(self.with_sc_results).lower()}&withOperations={str(self.with_operations).lower()}&withLogs={str(self.with_logs).lower()}"
        return flags
    

class OptionalFlags:
    def __init__(self, status: str = None, function: str = None):
        if status not in ["success", "pending", "invalid", "fail", ""]:
            raise ValueError("Invalid status")
        self.status = status
        self.function = function

    def get_flags(self) -> str:
        flags = ""
        if flags:
            flags += f"&status={self.status}"
        if self.function:
            flags += f"&function={self.function}"
        return flags


class CustomApiNetworkProvider(ApiNetworkProvider):
    def __do_get_unparsed(self, resource_url: str) -> Any:
        url = f'{self.url}/{resource_url}'
        try:
            response = requests.get(url, auth=self.auth)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as err:
            error_data = self._extract_error_from_response(err.response)
            raise GenericError(url, error_data)
        except requests.ConnectionError as err:
            raise GenericError(url, err)
        except Exception as err:
            raise GenericError(url, err)
        
    def __do_get_enhanced(self, url: str) -> Any:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
            rq_session = requests.Session()
            retries = Retry(total=3, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504, 408])
            rq_session.mount('https://', HTTPAdapter(max_retries=retries))
            response = rq_session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            parsed = response.json()
            return self._get_data(parsed, url)
        except requests.HTTPError as err:
            error_data = self._extract_error_from_response(err.response)
            raise GenericError(url, error_data)
        except requests.ConnectionError as err:
            raise GenericError(url, err)
        except Exception as err:
            raise GenericError(url, err)
        
    def do_get_generic_collection_enhanced(self, resource_url: str) -> List[Any]:
        url = f'{self.url}/{resource_url}'
        response = self.__do_get_enhanced(url)
        return response
        
    def get_transactions_count(self, address: Address) -> int:
        return self.__do_get_unparsed(f'accounts/{address.bech32()}/transactions/count')
    
    def _build_scroll_pagination_params(self, pagination: CustomPagination) -> str:
        return f'after={pagination.get_start()}&before={pagination.get_before()}&size={pagination.get_size()}'
    
    def _build_url_flags(self, url: str, results_flags: ResultsFlags, optional_flags: OptionalFlags) -> str:
        if results_flags:
            url += f"{results_flags.get_flags()}"
        if optional_flags:
            url += f"{optional_flags.get_flags()}"
        return url

    def get_paginated_account_transactions(self, address: IAddress, start_timestamp: int, 
                                           results_flags: ResultsFlags = None, optional_flags: OptionalFlags = None) -> List[TransactionOnNetwork]:
        count_url = f'accounts/{address.bech32()}/transactions/count?after={start_timestamp}'
        count_url = self._build_url_flags(count_url, results_flags, optional_flags)
        count = self.__do_get_unparsed(count_url)
        print(f"Found {count} searched transactions on account {address.bech32()}")

        def get_txs(addr: str, pagination: CustomPagination, results_flags: ResultsFlags = None, optional_flags: OptionalFlags = None) -> List[TransactionOnNetwork]:
            url = f"accounts/{addr}/transactions?{self._build_scroll_pagination_params(pagination)}"
            url = self._build_url_flags(url, results_flags, optional_flags)

            response = self.do_get_generic_collection_enhanced(url)
            transactions = [TransactionOnNetwork.from_api_http_response(tx.get("txHash", ""), tx) for tx in response]
            return transactions

        transactions = []
        from_tx = 0
        before_timestamp = int(time.time())
        pagination_size = 50 if results_flags else 10000
        batch = 0

        while from_tx <= count:
            pagination = CustomPagination(start_timestamp, before_timestamp, pagination_size)
            tx_page = get_txs(address, pagination, results_flags, optional_flags)
            transactions.extend(tx_page)

            from_tx = from_tx + pagination_size
            before_timestamp = tx_page[-1].timestamp
            batch += 1
            print(f"Fetched batch {batch} totaling {from_tx} txs out of {count}\n")
            time.sleep(2)

        return transactions


class CustomProxyNetworkProvider(ProxyNetworkProvider):
    def get_nonfungible_token_of_account_deep(self, address: IAddress, collection: str, nonce: int, block_nonce: int) -> NonFungibleTokenOfAccountOnNetwork:
        response = self.do_get_generic(f'address/{address.bech32()}/nft/{collection}/nonce/{nonce}?blockNonce={block_nonce}')
        token = NonFungibleTokenOfAccountOnNetwork.from_proxy_http_response_by_nonce(response.get('tokenData', ''))

        return token
    

class Token:
    def __init__(self, collection: str, nonce_hex: str, attributes: str = "") -> None:
        self.collection = collection
        self.nonce = nonce_hex
        self.attributes = attributes

    @classmethod
    def from_unknown(cls, token: Union[dict, str]) -> "Token":
        """Either from concatenated string or dictionary as in TokenOnNetwork"""
        if type(token) is dict:
            collection = token.get("identifier", "")[:token.get("identifier", "").rfind("-")]
            nonce = token.get("identifier", "")[token.get("identifier", "").rfind("-") + 1:]
        if type(token) is str:
            collection = token[:token.rfind("-")]
            nonce = token[token.rfind("-") + 1:]
        return Token(collection, nonce)
    

class BQTx:
    def __init__(self, tx: dict[str, Any]) -> None:
        self.hash = tx.get("_id")
        self.sender = Address.from_bech32(tx.get("sender"))
        self.source_nonce = tx.get("source_nonce")
        self.source_epoch: int = tx.get("source_epoch")
        self.tokens = [Token.from_unknown(token) for token in tx.get("tokens", [])]
        self.cross_attrs = tx.get("cross_attrs", "")
        self.attrs = tx.get("attributes", "")
        self.amounts = tx.get("amount", [])
    

def select_transactions_from_chain(address: Address, searched_method: str, since_when: int) -> list[TransactionOnNetwork]:
    custom_api = CustomApiNetworkProvider(API_URL)

    txs = []
    no_txs = int(custom_api.get_transactions_count(address))
    print(f"Total transactions on account: {no_txs}")

    flags = ResultsFlags(False, True, False)
    opt_flags = OptionalFlags("success", searched_method)
    txs = custom_api.get_paginated_account_transactions(address, since_when, flags, opt_flags)
    
    print(f"Retrieved {len(txs)} {searched_method} transactions.")

    return txs


def save_transactions_to_file(txs: list[TransactionOnNetwork]):
    with open(SAVED_FILE, "w") as f:
        json.dump([tx.to_dictionary() for tx in txs], f)


def load_transactions_from_file() -> list[TransactionOnNetwork]:
    with open(SAVED_FILE, "r") as f:
        txs = json.load(f)

    return [TransactionOnNetwork.from_api_http_response(tx.get("hash"), tx) for tx in txs]


def load_bq_from_file() -> list:
    txs = []
    with open(BQ_FILE, "r") as f:
        for line in f:
            txs.append(json.loads(line))

    return txs


def get_tokens_from_tx(tx: Union[dict, TransactionOnNetwork]) -> list:
    if "tokens" in tx:
        return tx.get("tokens")
    else:
        return tx.raw_response.get("action", {}).get("arguments", {}).get("transfers", [])


def get_token_attributes_from_sc_result(sc_result: str) -> str:
    converted = base64_to_string(sc_result)
    split = converted.split('@')
    if len(split) < 5:
        raise ValueError("Scam sc_result")
    attributes_hex = split[4]

    esdt = esdt_pb2.ESDigitalToken()
    esdt.ParseFromString(bytes.fromhex(attributes_hex))

    return bytes.hex(esdt.TokenMetaData.Attributes)


def get_token_attributes_from_api(token: Token, address: Address) -> str:
    api = ApiNetworkProvider(API_URL)
    token_on_network = api.get_non_fungible_token(token.collection, int(token.nonce, 16))
    return base64_to_hex(token_on_network.attributes)


def get_token_attributes_from_dh(token: Token, address: Address, block: int) -> str:
    deep_proxy = CustomProxyNetworkProvider(DEEP_PROXY_URL)
    token_on_dh = deep_proxy.get_nonfungible_token_of_account_deep(address, token.collection, int(token.nonce, 16), block)
    return base64_to_hex(token_on_dh.attributes)


def get_token_attributes_from_bq(tx: BQTx, token: Token) -> str:
    attributes_hex = ""

    if tx.cross_attrs:
        # cross shard tx; attributes available here
        attributes_hex = get_token_attributes_from_sc_result(tx.cross_attrs)
    else:
        # # intra shard tx; attributes available either in api or dh
        # try:
        #     attributes_hex = get_token_attributes_from_api(token, tx.sender)
        # except Exception as e:
        #     if e.data.get("statusCode") == 404:
        #         print(f"Could not find token {token.collection} {token.nonce} from api for hash {tx.hash}. Falling back to deep proxy.")
        #         # try to get it from deep proxy
        #         attributes_hex = get_token_attributes_from_dh(token, tx.sender, tx.source_nonce - 1)        
        try:
            attributes_hex = get_token_attributes_from_dh(token, tx.sender, tx.source_nonce - 1)
        except Exception as e:
            # retry after 5 seconds
            time.sleep(5)
            attributes_hex = get_token_attributes_from_dh(token, tx.sender, tx.source_nonce - 1)

    return attributes_hex


def get_decoded_token_attributes_by_unknown_token(attributes: str) -> dict[str, Any]:
    decoded = {}
    try:
        decoded = decode_merged_attributes(attributes, LKMEX_ATTRIBUTES_V2)
        v2_checksum = 0
        for schedule in decoded.get("unlock_schedule_list", []):
            v2_checksum += schedule.get("unlock_percent", 0)
        if v2_checksum != 100000:
            print(f"Checksum failed for v2 attributes {attributes}")
            raise ValueError("Checksum failed")
    except ValueError as e:
        try:
            decoded = decode_merged_attributes(attributes, LKMEX_ATTRIBUTES_V1)
            v1_checksum = 0
            for schedule in decoded.get("unlock_schedule_list", []):
                v1_checksum += schedule.get("unlock_percent", 0)
            if v1_checksum != 100:
                print(f"Checksum failed for v1 attributes {attributes}")
                raise ValueError("Checksum failed")
        except Exception as e:
            print(f"Could not decode attributes {attributes} due to {e}")
    except Exception as e:
        print(f"Could not decode attributes {attributes} due to {e}")

    return decoded


def get_decoded_token_attributes_by_known_token(attributes: str, token: Any) -> dict[str, Any]:
    decoded = {}
    if type(token) is not Token:
        tk = Token.from_unknown(token)
    else:
        tk = token

    if int(tk.nonce, 16) >= 2286815:
        decoded = decode_merged_attributes(attributes, LKMEX_ATTRIBUTES_V2)
        v2_checksum = 0
        for schedule in decoded.get("unlock_schedule_list", []):
            v2_checksum += schedule.get("unlock_percent", 0)
        if v2_checksum != 100000:
            print(f"Checksum failed for v2 attributes {attributes}")
            raise ValueError("Checksum failed")
    else:
        decoded = decode_merged_attributes(attributes, LKMEX_ATTRIBUTES_V1)
        v1_checksum = 0
        for schedule in decoded.get("unlock_schedule_list", []):
            v1_checksum += schedule.get("unlock_percent", 0)
        if v1_checksum != 100:
            print(f"Checksum failed for v1 attributes {attributes}")
            raise ValueError("Checksum failed")

    return decoded


def check_affected_token_attributes(attributes: str, unlock_epoch: int) -> bool:
    affected = False

    decoded_attrs = get_decoded_token_attributes_by_unknown_token(attributes)
    if not decoded_attrs:
        print(f"Token has no decoded attributes")
        raise ValueError("Token has no decoded attributes")
    
    # if token unlock epoch is lower than 30 days, it's affected
    for schedule in decoded_attrs.get("unlock_schedule_list", []):
        token_unlock_epoch = schedule.get("unlock_epoch")
        if unlock_epoch - 30 < token_unlock_epoch < unlock_epoch:
            affected = True
            print(f"Token unlock epoch {token_unlock_epoch} is affected by tx unlock epoch {unlock_epoch}: {attributes}")
            break

    return affected


def check_affected_tx(tx: Union[BQTx, dict[str, Any]]) -> bool:
    if type(tx) is dict:
        tx_obj = BQTx(tx)
    else:
        tx_obj = tx

    affected = False

    tokens = tx_obj.tokens
    if not len(tokens):
        print(f"Transaction {tx_obj.hash} has no tokens")
        return

    for token in tokens:
        attributes_hex = get_token_attributes_from_bq(tx_obj, token)

        # process attributes to see if it's affected
        if not attributes_hex:
            # TODO: this case can still add uncertainty
            print(f"Tx {tx_obj.hash} token {token.collection} {token.nonce} has no attributes")
            return False
        
        affected = affected or check_affected_token_attributes(attributes_hex, tx_obj.source_epoch)

        # if affected is True, write original tx along with the attributes to a file
        if affected and type(tx) is dict:
            tx['attributes'] = attributes_hex
            with open("affected_full_txs.json", "a") as f:
                json.dump(tx, f)
                f.write("\n")

    return affected


def find_affected_txs(txs: list[dict]) -> list[dict]:
    parallel = True
    affected = []

    if parallel:
        pool = Pool(20)
        affected = pool.map(check_affected_tx, txs)
    else:
        i = 1
        total = len(txs)
        print(f"Checking {total} transactions for affected tokens")
        for tx in txs:
            print(f"Checking tx {i} / {total}: {tx.get('_id')}")
            affected.append(check_affected_tx(tx))
            i += 1

    return [txs[i] for i in range(len(txs)) if affected[i]]


def find_showing_effects():
    custom_api = CustomApiNetworkProvider(API_URL)
    fees_collector_contract = Address.from_bech32("erd1qqqqqqqqqqqqqpgqjsnxqprks7qxfwkcg2m2v9hxkrchgm9akp2segrswt")

    affected_accounts = []

    no_txs = int(custom_api.get_transactions_count(fees_collector_contract))
    print(f"Total transactions on account: {no_txs}")

    flags = ResultsFlags(False, True, False)
    opt_flags = OptionalFlags("fail")
    txs = custom_api.get_paginated_account_transactions(fees_collector_contract, 1670612112, flags, opt_flags)

    for tx in txs:
        for operation in tx.raw_response.get("operations", []):
            if "Cannot unwrap value" in operation.get("message", ""):
                if tx.sender.bech32() not in affected_accounts:
                    affected_accounts.append(tx.sender.bech32())
                    print("Found affected account: ", tx.sender.bech32())

    return affected_accounts


def find_affected(source: str):
    if source == "api":
        if not os.path.exists(SAVED_FILE):
            txs = select_transactions_from_chain(LOCKED_ASSET_CONTRACT, "unlockAssets", 1670612112)
            
            # save txs into json file
            save_transactions_to_file(txs)
        else:
            txs = load_transactions_from_file()
    else:
        # load txs from json file
        txs = load_bq_from_file()

    affected_txs = find_affected_txs(txs)
    accounts = [tx.get("sender", "") for tx in affected_txs]

    # save affected txs into json file
    with open("affected_txs.json", "w") as f:
        json.dump(affected_txs, f)

    # save affected accounts into json file
    with open("affected_accounts.json", "w") as f:
        json.dump(accounts, f)


def get_full_txs_from_file() -> list[dict[str, Any]]:
    txs = []
    with open("full_txs_with_amounts.json", "r") as f:
        for line in f:
            tx_obj = json.loads(line)
            txs.append(tx_obj)

    return txs


def calculate_energy_difference() -> list[dict[str, Any]]:
    txs = get_full_txs_from_file()

    for tx in txs:
        tx_obj = BQTx(tx)
        if not tx_obj.attrs:
            print(f"Tx {tx_obj.hash} has no attributes")
            continue

        decoded_attrs = get_decoded_token_attributes_by_known_token(tx_obj.attrs, tx_obj.tokens[0])
        energy_diff = 0
        print(decoded_attrs)

        # if token unlock epoch is lower than 30 days, it's affected
        for schedule in decoded_attrs.get("unlock_schedule_list", []):
            token_unlock_epoch = int(schedule.get("unlock_epoch"))
            if tx_obj.source_epoch - 30 < token_unlock_epoch < tx_obj.source_epoch:
                denominator = 100 if int(tx_obj.tokens[0].nonce, 16) < 2286815 else 100000
                remainder_tk_amount = int(tx_obj.amounts[0]) * token_unlock_epoch // denominator
                energy_diff += remainder_tk_amount * (tx_obj.source_epoch - token_unlock_epoch)
                print(f"Tx {tx_obj.hash} of user {tx_obj.sender.bech32()} has energy difference of {energy_diff} from token {tx_obj.tokens[0].collection} {tx_obj.tokens[0].nonce}, unlock epoch {token_unlock_epoch}")

    return txs
    


def confirm_affected_accounts(accounts: list[str]):
    uniques = list(set(accounts))
    
    print(f"Identified {len(accounts)} affected txs")
    print(f"Found {len(uniques)} unique affected accounts")


def main(args):
    ### first step
    # accounts = find_showing_effects()

    ### second step
    # find_affected("bq")

    ### third step
    # txs = get_full_txs_from_file()
    # print(len(txs))
    
    ### fourth step
    # with open("affected_accounts.json", "r") as f:
    #     accounts = json.load(f)
    # confirm_affected_accounts(accounts)

    ### fifth step
    calculate_energy_difference()

if __name__ == "__main__":
    main(sys.argv[1:])
