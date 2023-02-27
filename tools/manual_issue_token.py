import logging
import sys
from argparse import ArgumentParser
from typing import List

import config
from arrows.stress.esdtnft.shared import (build_token_name, build_token_ticker,
                                          load_contracts, make_call_arg_ascii,
                                          make_call_arg_pubkey)
from arrows.stress.shared import BunchOfAccounts, broadcast_transactions
from erdpy.contracts import SmartContract
from erdpy.proxy.core import ElrondProxy
from erdpy.transactions import Transaction


def main(cli_args: List[str]):
    logging.basicConfig(level=logging.ERROR)

    parser = ArgumentParser()
    parser.add_argument("--proxy", default=config.DEFAULT_PROXY)
    parser.add_argument("--accounts", default=config.DEFAULT_OWNER)
    parser.add_argument("--sleep-between-chunks", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--from-shard")
    parser.add_argument("--via-shard")
    parser.add_argument("--base-gas-limit", type=int, default=config.DEFAULT_GAS_BASE_LIMIT_ISSUE)
    parser.add_argument("--gas-limit", type=int, default=0)
    parser.add_argument("--supply", type=int, default=1000000000000000000)
    parser.add_argument("--token-id")
    parser.add_argument("--yes", action="store_true", default=False)
    parser.add_argument("--mode", choices=["direct", "via"], default="direct")

    args = parser.parse_args(cli_args)

    proxy = ElrondProxy(args.proxy)
    network = proxy.get_network_config()

    bunch_of_accounts = BunchOfAccounts.load_accounts_from_files([args.accounts])
    # bunch_of_accounts.sync_nonces(proxy)
    accounts = bunch_of_accounts.get_all() if args.from_shard is None else bunch_of_accounts.get_in_shard(int(args.from_shard))
    account = accounts[0]  # issue tokens only for SC owner account to improve times on large number of accounts
    account.sync_nonce(proxy)

    supply = args.supply
    token_id = args.token_id
    print("Token id: ", token_id)
    print("Supply: ", supply)

    def issue_token():
        for account in accounts:
            sc_args = [f'str:{token_id}', supply]

            receiver_address = SmartContract(address=account.address)
            tx_data = receiver_address.prepare_execute_transaction_data("ESDTLocalMint", sc_args)

            gas_limit = args.gas_limit or args.base_gas_limit + 50000 + 1500 * len(tx_data)
            value = "0"

            tx = Transaction()
            tx.nonce = account.nonce
            tx.value = value
            tx.sender = account.address.bech32()
            tx.receiver = receiver_address.address.bech32()
            tx.gasPrice = network.min_gas_price
            tx.gasLimit = gas_limit
            tx.data = tx_data
            tx.chainID = str(network.chain_id)
            tx.version = network.min_tx_version
            tx.sign(account)

            print("Holder account: ", account.address)
            print("Token id: ", token_id)

            transactions.append(tx)
            account.nonce += 1

    transactions: List[Transaction] = []

    issue_token()

    hashes = broadcast_transactions(transactions, proxy, args.chunk_size, sleep=args.sleep_between_chunks, confirm_yes=args.yes)

    return hashes


if __name__ == "__main__":
    main(sys.argv[1:])
