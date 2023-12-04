import logging
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import List
from multiversx_sdk_core import Transaction
from utils.utils_chain import Account
from utils.utils_chain import BunchOfAccounts
from utils.utils_tx import broadcast_transactions
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider


def main(cli_args: List[str]):
    logging.basicConfig(level=logging.ERROR)

    parser = ArgumentParser()
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--minter", required=True)
    parser.add_argument("--value-atoms", type=int, required=True)
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    accounts = BunchOfAccounts.load_accounts_from_files([Path(args.accounts)])
    minter = Account(pem_file=Path(args.minter))
    minter.sync_nonce(proxy)

    print("Minter", minter.address, "nonce", minter.nonce)

    transactions: List[Transaction] = []

    for account in accounts.get_all():
        if account.address.bech32() == minter.address.bech32():
            continue

        transaction = Transaction(
            chain_id=network.chain_id,
            sender=minter.address,
            receiver=account.address,
            gas_limit=50000,
        )
        transaction.nonce = minter.nonce
        transaction.value = str(args.value_atoms)
        transaction.gas_price = network.min_gas_price
        transaction.version = network.min_transaction_version

        signature = minter.sign_transaction(transaction)
        transaction.signature = signature
        minter.nonce += 1

        transactions.append(transaction)

    broadcast_transactions(transactions, proxy, 10, confirm_yes=True)


if __name__ == "__main__":
    main(sys.argv[1:])
