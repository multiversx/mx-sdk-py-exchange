import logging
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import List
from utils.utils_chain import Account
from utils.utils_tx import broadcast_transactions
from utils.utils_chain import BunchOfAccounts
from multiversx_sdk import ProxyNetworkProvider, TokenPayment, Transaction
from multiversx_sdk.core.transaction_builders import MultiESDTNFTTransferBuilder, DefaultTransactionBuildersConfiguration


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

        send_config = DefaultTransactionBuildersConfiguration(network.chain_id)
        payments = [TokenPayment.fungible_from_integer(args.token, args.amount_atoms, 18)]
        transaction = MultiESDTNFTTransferBuilder(
            config=send_config,
            sender=minter.address,
            destination=account.address,
            payments=payments,
        ).build()
        transaction.nonce = minter.nonce
        transaction.signature = minter.sign_transaction(transaction)
        minter.nonce += 1

        transactions.append(transaction)

    broadcast_transactions(transactions, proxy, 10, confirm_yes=True)


if __name__ == "__main__":
    main(sys.argv[1:])
