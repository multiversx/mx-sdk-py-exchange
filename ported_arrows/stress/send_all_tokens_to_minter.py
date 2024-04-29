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
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    accounts = BunchOfAccounts.load_accounts_from_files([Path(args.accounts)])
    minter = Account(pem_file=Path(args.minter))
    minter.sync_nonce(proxy)

    transactions: List[Transaction] = []

    for account in accounts.get_all():
        account.sync_nonce(proxy)
        fungibles = proxy.get_fungible_tokens_of_account(account.address)
        nonfungibles = proxy.get_nonfungible_tokens_of_account(account.address)

        def prep_txs(payments: List[TokenPayment]):
            if len(payments) == 0:
                return
            send_config = DefaultTransactionBuildersConfiguration(network.chain_id)
            transaction = MultiESDTNFTTransferBuilder(
                config=send_config,
                sender=account.address,
                destination=minter.address,
                payments=payments,
            ).build()
            transaction.nonce = account.nonce
            transaction.signature = account.sign_transaction(transaction)
            account.nonce += 1

            transactions.append(transaction)
        
        payments: List[TokenPayment] = []

        for fungible in fungibles:
            payments.append(TokenPayment.fungible_from_integer(fungible.identifier, fungible.balance, 18))

        for nonfungible in nonfungibles:
            if "XMEX" in nonfungible.collection:
                continue
            payments.append(TokenPayment.meta_esdt_from_integer(nonfungible.collection, nonfungible.nonce, nonfungible.balance, 18))
        
        prep_txs(payments)

    broadcast_transactions(transactions, proxy, 10, confirm_yes=True)


if __name__ == "__main__":
    main(sys.argv[1:])
