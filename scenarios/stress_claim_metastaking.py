import sys
from argparse import ArgumentParser
from typing import List
from multiversx_sdk_core import Address, Transaction
from ported_arrows.stress.contracts.transaction_builder import number_as_arg, string_as_arg
from utils.account import Account
from utils.utils_tx import broadcast_transactions
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider
from multiversx_sdk_network_providers.network_config import NetworkConfig


def claim_metastaking_rewards(caller: Account, contract_addr: Address, number_of_tokens: int, token_identifier: str,
                              token_nonce: str, token_quantity: int, network: NetworkConfig, method: str) -> Transaction:

    tx_data = f'MultiESDTNFTTransfer@{contract_addr.hex()}@{number_as_arg(number_of_tokens)}@{string_as_arg(token_identifier)}' \
              f'@{token_nonce}@{number_as_arg(token_quantity)}@{string_as_arg(method)}'

    transaction = Transaction(
        chain_id=network.chain_id,
        sender=caller.address.bech32(),
        receiver=caller.address.bech32(),
        gas_limit=40000000
    )
    transaction.nonce = caller.nonce
    transaction.value = '0'
    transaction.data = tx_data
    transaction.gasPrice = network.min_gas_price
    transaction.chainID = network.chain_id
    transaction.version = network.min_tx_version
    signature = caller.sign_transaction(transaction)
    transaction.signature = signature

    return transaction


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--proxy", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--token-nonce", required=True)
    parser.add_argument('--contract-address', required=True)
    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    network = proxy.get_network_config()
    account = Account(pem_file=args.account)
    account.sync_nonce(proxy)
    token_identifier = args.token
    token_nonce = args.token_nonce
    token_quantity = 1000
    method = 'claimDualYield'
    contract_address = Address(args.contract_address, "erd")

    txs = []
    for _ in range(5):
        tx = claim_metastaking_rewards(account, contract_address, 1, token_identifier, token_nonce, token_quantity,
                                       network, method)

        txs.append(tx)
        account.nonce += 1

    broadcast_transactions(txs, proxy, 5, confirm_yes=True)


if __name__ == '__main__':
    main(sys.argv[1:])
