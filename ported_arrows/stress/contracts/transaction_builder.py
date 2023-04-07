
from typing import Any, List, Tuple

from utils.utils_chain import Account, Address
from utils.utils_tx import Transaction
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider


class ArgLengths:
    def __init__(self, lengths: List[int]):
        self.lengths = lengths

    def as_bytes(self):
        result = bytearray()

        for length in self.lengths:
            result += length.to_bytes(4, byteorder="little")

        return bytes(result)

    def as_hex(self):
        result = self.as_bytes().hex()
        return result


class RawHex:
    def __init__(self, raw: str):
        self.raw = raw

    def as_hex(self):
        return self.raw


def transfer_multi_esdt_and_execute(contract_address: Address, caller: Account, transfers: List[Tuple[str, int]], function: str, args: List[Any], execute_gas_limit: int, network_config: ProxyNetworkProvider):
    tx_data_transfer = multi_esdt_transfer_data(contract_address, transfers)
    tx_data_execute = string_as_arg(function)

    for arg in args:
        tx_data_execute += f"@{any_as_arg(arg)}"

    tx = Transaction()
    tx.nonce = caller.nonce
    tx.sender = caller.address.bech32()
    tx.data = f"{tx_data_transfer}@{tx_data_execute}"
    tx.receiver = caller.address.bech32()
    tx.gasPrice = network_config.min_gas_price
    tx.gasLimit = 250000 * len(transfers) + 1000000 + 50000 + 1500 * len(tx.data) + execute_gas_limit
    tx.chainID = network_config.chain_id
    tx.version = network_config.min_tx_version
    tx.sign(caller)

    return tx


def multi_esdt_transfer_data(receiver: Address, transfers: List[Tuple[str, int]]):
    tx_data = f"MultiESDTNFTTransfer@{receiver.hex()}@{number_as_arg(len(transfers))}"
    for token_id, value in transfers:
        tx_data += f"@{token_id_as_arg(token_id)}@00@{number_as_arg(value)}"

    return tx_data


def any_as_arg(value: Any):
    if isinstance(value, str):
        return string_as_arg(value)
    if isinstance(value, int):
        return number_as_arg(value)
    if isinstance(value, Address):
        return value.hex()
    if isinstance(value, ArgLengths):
        return value.as_hex()
    if isinstance(value, RawHex):
        return value.as_hex()
    raise Exception(f"Unknown type: value = {value}.")


def token_id_as_arg(value: str):
    return string_as_arg(value)


def string_as_arg(value: str):
    return value.encode('ascii').hex()


def number_as_arg(value: int):
    result = format(value, "x")
    result = "0" + result if len(result) % 2 else result
    return result
