import logging
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import List

from ported_arrows.stress.contracts.transaction_builder import (number_as_arg,
                                                         token_id_as_arg)
from utils.utils_tx import broadcast_transactions
from utils.utils_chain import BunchOfAccounts
from multiversx_sdk_cli.accounts import Account
from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_cli.transactions import Transaction


def main(cli_args: List[str]):
    logging.basicConfig(level=logging.ERROR)

    parser = ArgumentParser()
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--minter", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--amount-atoms", type=int, required=True)
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    accounts = BunchOfAccounts.load_accounts_from_files([Path(args.accounts)])
    minter = Account(pem_file=Path(args.minter))
    minter.sync_nonce(proxy)

    transactions: List[Transaction] = []

    for account in accounts.get_all():

        transaction = Transaction()
        transaction.nonce = minter.nonce
        transaction.sender = minter.address.bech32()
        transaction.receiver = account.address.bech32()
        transaction.data = f"ESDTTransfer@{token_id_as_arg(args.token)}@{number_as_arg(args.amount_atoms)}"
        transaction.value = "0"
        transaction.gasPrice = network.min_gas_price
        transaction.gasLimit = 250000 + 50000 + 1500 * len(transaction.data)
        transaction.chainID = network.chain_id
        transaction.version = network.min_transaction_version
        transaction.sign(minter)
        minter.nonce += 1

        transactions.append(transaction)

    broadcast_transactions(transactions, proxy, 10, confirm_yes=True)


if __name__ == "__main__":
    main(sys.argv[1:])
