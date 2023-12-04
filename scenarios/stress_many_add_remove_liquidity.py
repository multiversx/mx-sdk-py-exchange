
import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import List
from multiversx_sdk_core import Address, Transaction

from ported_arrows.stress.contracts.transaction_builder import \
    transfer_multi_esdt_and_execute
from utils.utils_chain import Account
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
    parser.add_argument("--token-lp", required=True)
    parser.add_argument("--pair", required=True)
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    pair = Address(args.pair, "erd")
    accounts = BunchOfAccounts.load_accounts_from_files([Path(args.accounts)])

    for _ in range(0, 1000):
        accounts.sync_nonces(proxy)

        transactions: List[Transaction] = []

        for account in accounts.get_all() * 10:
            transactions.append(create_add_liquidity(pair, account, args.token_one, args.token_two, network))
            account.nonce += 1
            transactions.append(create_remove_liquidity(pair, account, args.token_lp, network))
            account.nonce += 1

        broadcast_transactions(transactions, proxy, 1000, confirm_yes=True)
        time.sleep(60 * 1)


def create_add_liquidity(pair: Address, caller: Account, token_one: str, token_two: str, network: NetworkConfig) -> Transaction:
    given_one = 100000
    given_two = 100000
    transfers = [(token_one, given_one), (token_two, given_two)]
    args = [1, 1]
    gas_limit = 8400000
    transaction = transfer_multi_esdt_and_execute(pair, caller, transfers, "addLiquidity", args, gas_limit, network)
    return transaction


def create_remove_liquidity(pair: Address, caller: Account, token_lp: str, network: NetworkConfig) -> Transaction:
    taken_one = 1
    taken_two = 1
    transfers = [(token_lp, 1)]
    args = [taken_one, taken_two]
    gas_limit = 750000
    transaction = transfer_multi_esdt_and_execute(pair, caller, transfers, "remove_liquidity", args, gas_limit, network)
    return transaction


if __name__ == "__main__":
    main(sys.argv[1:])
