import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import List
from multiversx_sdk_core import Address, Transaction
from ported_arrows.stress.contracts.transaction_builder import (number_as_arg,
                                                         string_as_arg,
                                                         token_id_as_arg)
from utils.account import Account
from utils.utils_tx import broadcast_transactions
from utils.utils_chain import BunchOfAccounts
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider
from multiversx_sdk_network_providers.network_config import NetworkConfig


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--token-one", required=True)
    parser.add_argument("--token-two", required=True)
    parser.add_argument("--pair", required=True)
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    pair = Address(args.pair, "erd")
    accounts = BunchOfAccounts.load_accounts_from_files([Path(args.accounts)])

    for _ in range(0, 100):
        accounts.sync_nonces(proxy)

        transactions: List[Transaction] = []

        for account in accounts.get_all():
            transactions.append(create_swap_fixed_input(pair, account, args.token_one, args.token_two, network))
            transactions.append(create_swap_fixed_input(pair, account, args.token_two, args.token_one, network))

        broadcast_transactions(transactions, proxy, 1000, confirm_yes=True)
        time.sleep(60 * 3)


def create_swap_fixed_input(pair: Address, caller: Account, token_from: str, token_to: str, network: NetworkConfig) -> Transaction:
    amount_from = 100000
    amount_to_min = 1
    tx_data = f"ESDTTransfer@{token_id_as_arg(token_from)}@{number_as_arg(amount_from)}@{string_as_arg('swapTokensFixedInput')}@{token_id_as_arg(token_to)}@{number_as_arg(amount_to_min)}"

    transaction = Transaction(
        chain_id=network.chain_id,
        sender=caller.address.bech32(),
        receiver=pair.bech32(),
        gas_limit=8000000
    )
    transaction.nonce = caller.nonce
    transaction.value = "0"
    transaction.data = tx_data
    transaction.gasPrice = network.min_gas_price
    transaction.version = network.min_tx_version

    signature = caller.sign_transaction(transaction)
    transaction.signature = signature

    return transaction


if __name__ == "__main__":
    main(sys.argv[1:])
