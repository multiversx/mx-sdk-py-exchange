from typing import Callable, Dict, Optional

from multiversx_sdk import ProxyNetworkProvider, TransactionComputer
from multiversx_sdk.core.address import Address
from multiversx_sdk.network_providers.network_config import NetworkConfig
from multiversx_sdk.network_providers.transaction_status import \
    TransactionStatus
from multiversx_sdk.network_providers.transactions import (
    ITransaction, TransactionOnNetwork)


class MockNetworkProvider(ProxyNetworkProvider):
    def __init__(self) -> None:
        super().__init__("https://example.multiversx.com")

        self.transactions: Dict[str, TransactionOnNetwork] = {}
        self.transaction_computer = TransactionComputer()

    def get_network_config(self) -> NetworkConfig:
        network_config = NetworkConfig()
        network_config.chain_id = "T"
        network_config.gas_per_data_byte = 1500
        network_config.min_gas_limit = 50000
        network_config.min_gas_price = 1000000000
        return network_config

    def mock_update_transaction(self, hash: str, mutate: Callable[[TransactionOnNetwork], None]) -> None:
        transaction = self.transactions.get(hash, None)

        if transaction:
            mutate(transaction)

    def mock_put_transaction(self, hash: str, transaction: TransactionOnNetwork) -> None:
        self.transactions[hash] = transaction

    def get_transaction(self, tx_hash: str, with_process_status: Optional[bool] = False) -> TransactionOnNetwork:
        transaction = self.transactions.get(tx_hash, None)
        if transaction:
            return transaction

        raise Exception("Transaction not found")

    def get_transaction_status(self, tx_hash: str) -> TransactionStatus:
        transaction = self.get_transaction(tx_hash)
        return transaction.status

    def send_transaction(self, transaction: ITransaction) -> str:
        hash = self.transaction_computer.compute_transaction_hash(transaction).hex()

        transaction_on_network = TransactionOnNetwork()
        transaction_on_network.hash = hash
        transaction_on_network.sender = Address.from_bech32(transaction.sender)
        transaction_on_network.receiver = Address.from_bech32(transaction.receiver)
        transaction_on_network.value = transaction.value
        transaction_on_network.gas_limit = transaction.gas_limit
        transaction_on_network.gas_price = transaction.gas_price
        transaction_on_network.data = transaction.data.decode("utf-8")
        transaction_on_network.signature = transaction.signature.hex()

        self.mock_put_transaction(hash, transaction_on_network)

        return hash
