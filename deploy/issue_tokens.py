import sys
from argparse import ArgumentParser
from typing import List

import config
from utils.logger import get_logger
from utils.utils_chain import (Account, build_token_name, build_token_ticker)
from multiversx_sdk import ProxyNetworkProvider, Address, TokenPayment, Transaction
from multiversx_sdk.core.transaction_builders import ContractCallBuilder, DefaultTransactionBuildersConfiguration

from utils.utils_tx import broadcast_transactions

logger = get_logger(__name__)


def main(cli_args: List[str]):

    parser = ArgumentParser()
    parser.add_argument("--proxy", default=config.DEFAULT_PROXY)
    parser.add_argument("--account", default=config.DEFAULT_OWNER)
    parser.add_argument("--sleep-between-chunks", type=int, default=5)
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--from-shard")
    parser.add_argument("--via-shard")
    parser.add_argument("--base-gas-limit", type=int, default=config.DEFAULT_GAS_BASE_LIMIT_ISSUE)
    parser.add_argument("--gas-limit", type=int, default=0)
    parser.add_argument("--num-tokens", type=int, default=1)
    parser.add_argument("--num-decimals", type=int, default=18)
    parser.add_argument("--supply-exp", type=int, default=27)
    parser.add_argument("--tokens-prefix", default=config.DEFAULT_TOKEN_PREFIX)
    parser.add_argument("--value", default=str(config.DEFAULT_ISSUE_TOKEN_PRICE))
    parser.add_argument("--yes", action="store_true", default=False)
    parser.add_argument("--mode", choices=["direct", "via"], default="direct")

    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    builder_config = DefaultTransactionBuildersConfiguration(network.chain_id)

    account = Account(pem_file=args.account)
    account.sync_nonce(proxy)

    tokens_system_contract = Address.from_bech32(config.TOKENS_CONTRACT_ADDRESS)

    supply = pow(10, args.supply_exp)
    num_decimals = args.num_decimals
    prefix = args.tokens_prefix
    print("Supply: ", supply, "Decimals: ", num_decimals, "Prefix: ", prefix)
    print("Number of tokens: ", args.num_tokens)

    def issue_token():
        for i in range(0, args.num_tokens):
            token_name, token_name_hex = build_token_name(account.address, prefix)
            token_ticker, token_ticker_hex = build_token_ticker(account.address, prefix)
            value = args.value

            builder = ContractCallBuilder(
                config=builder_config,
                contract=tokens_system_contract,
                caller=account.address,
                function_name="issue",
                call_arguments=[
                    token_name,
                    token_ticker,
                    supply,
                    num_decimals
                ],
                value=TokenPayment.egld_from_integer(value)
            )

            # calculate precise gas limit
            tx_data = builder.build_payload()
            gas_limit = args.gas_limit or args.base_gas_limit + 50000 + 1500 * tx_data.length()
            builder.gas_limit = gas_limit

            tx = builder.build()
            tx.nonce = account.nonce
            tx.signature = account.sign_transaction(tx)

            print("Holder account: ", account.address.bech32())
            print("Token name: ", token_name)
            print("Token ticker: ", token_ticker)

            transactions.append(tx)
            account.nonce += 1

    transactions: List[Transaction] = []

    issue_token()

    hashes = broadcast_transactions(transactions, proxy, args.chunk_size,
                                    sleep=args.sleep_between_chunks, confirm_yes=args.yes)

    return hashes


if __name__ == "__main__":
    main(sys.argv[1:])
