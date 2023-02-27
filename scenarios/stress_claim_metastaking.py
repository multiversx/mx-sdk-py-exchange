import sys
import time
from argparse import ArgumentParser
from typing import List
from arrows.stress.contracts.transaction_builder import number_as_arg, string_as_arg
from arrows.stress.shared import broadcast_transactions
from erdpy.accounts import Account, Address
from erdpy.proxy.core import ElrondProxy
from erdpy.proxy.messages import NetworkConfig
from erdpy.transactions import Transaction


def claim_metastaking_rewards(caller: Account, contract_addr: Address, number_of_tokens: int, token_identifier: str,
                              token_nonce: str, token_quantity: int, network: NetworkConfig, method: str) -> Transaction:

    tx_data = f'MultiESDTNFTTransfer@{contract_addr.hex()}@{number_as_arg(number_of_tokens)}@{string_as_arg(token_identifier)}' \
              f'@{token_nonce}@{number_as_arg(token_quantity)}@{string_as_arg(method)}'

    transaction = Transaction()
    transaction.nonce = caller.nonce
    transaction.sender = caller.address.bech32()
    transaction.receiver = caller.address.bech32()
    transaction.value = '0'
    transaction.data = tx_data
    transaction.gasPrice = network.min_gas_price
    transaction.gasLimit = 40000000
    transaction.chainID = network.chain_id
    transaction.version = network.min_tx_version
    transaction.sign(caller)

    return transaction


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--token-nonce", required=True)
    parser.add_argument('--contract-address', required=True)
    args = parser.parse_args(cli_args)

    proxy = ElrondProxy(args.proxy)
    network = proxy.get_network_config()
    account = Account(pem_file=args.account)
    account.sync_nonce(proxy)
    token_identifier = args.token
    token_nonce = args.token_nonce
    token_quantity = 1000
    method = 'claimDualYield'
    contract_address = Address(args.contract_address)

    txs = []
    for _ in range(5):
        tx = claim_metastaking_rewards(account, contract_address, 1, token_identifier, token_nonce, token_quantity,
                                       network, method)

        txs.append(tx)
        account.nonce += 1

    broadcast_transactions(txs, proxy, 5, confirm_yes=True)


if __name__ == '__main__':
    main(sys.argv[1:])
