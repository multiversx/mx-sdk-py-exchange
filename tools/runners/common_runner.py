from itertools import chain
from typing import Any, List
import json

from multiversx_sdk import Address, TokenPayment
from multiversx_sdk.core.transaction_builders.transfers_builders import EGLDTransferBuilder
from multiversx_sdk.core.transaction_builders import DefaultTransactionBuildersConfiguration
from tools.common import API, PROXY
from utils.utils_chain import Account, WrapperAddress
from utils.utils_generic import split_to_chunks
from utils.utils_tx import NetworkProviders
import config



class ExportedToken:
    def __init__(self, token_name: str, token_nonce_hex: str, supply: str, attributes: str):
        self.token_name = token_name
        self.token_nonce_hex = token_nonce_hex
        self.supply = supply
        self.attributes = attributes


class ExportedAccount:
    def __init__(self, address: str, nonce: int, value: int, account_tokens_supply: List[ExportedToken]):
        self.address = address
        self.nonce = nonce
        self.value = value
        self.account_tokens_supply = account_tokens_supply


def read_accounts_from_json(json_path: str) -> List[ExportedAccount]:
    """Read accounts from json file"""

    with open(json_path, 'r') as file:
        accounts = json.load(file)

    exported_accounts = []
    for account in accounts:
        exported_tokens = []
        for token in account['accountTokensSupply']:
            exported_token = ExportedToken(token['tokenName'], token['tokenNonceHex'], token['supply'], token['attributes'])
            exported_tokens.append(exported_token)
        account['accountTokensSupply'] = exported_tokens
        exported_accounts.append(ExportedAccount(account['address'], account['nonce'], account['value'], exported_tokens))

    return exported_accounts


def get_acounts_with_token(accounts: List[ExportedAccount], token_name: str) -> List[ExportedAccount]:
    """Get accounts with token"""

    accounts_with_token = []
    for account in accounts:
        for token in account.account_tokens_supply:
            if token.token_name == token_name:
                accounts_with_token.append(account)
                break

    return accounts_with_token


def sync_account_nonce(exported_account: ExportedAccount) -> ExportedAccount:
    """Sync account nonce"""
    network_providers = NetworkProviders(API, PROXY)
    account = Account(exported_account.address, config.DEFAULT_OWNER)
    account.address = WrapperAddress.from_bech32(exported_account.address)
    account.sync_nonce(network_providers.proxy)
    exported_account.nonce = account.nonce
    return exported_account


def get_default_signature() -> str:
    """Get default signature"""

    network_providers = NetworkProviders(API, PROXY)
    chain_id = network_providers.proxy.get_network_config().chain_id
    tx_config = DefaultTransactionBuildersConfiguration(chain_id=chain_id)
    funding_account = Account(address=None, pem_file=config.DEFAULT_OWNER)
    transaction = EGLDTransferBuilder(
        config=tx_config,
        sender=funding_account.address,
        receiver=funding_account.address,
        payment=TokenPayment.egld_from_amount(0.001),
        nonce=funding_account.nonce,
    ).build()
    return funding_account.sign_transaction(transaction)


def fund_shadowfork_accounts(accounts: List[ExportedAccount]) -> None:
    """Fund accounts"""

    network_providers = NetworkProviders(API, PROXY)
    chain_id = network_providers.proxy.get_network_config().chain_id
    tx_config = DefaultTransactionBuildersConfiguration(chain_id=chain_id)
    funding_account = Account(address=None, pem_file=config.DEFAULT_OWNER)
    funding_account.address = WrapperAddress.from_bech32(config.SHADOWFORK_FUNDING_ADDRESS)
    funding_account.sync_nonce(network_providers.proxy)
    signature = get_default_signature()

    transactions = []
    index = 1
    for account in accounts:
        if int(account.value) > 10000000000000000:
            continue

        print(f"Funding account {account.address} of {index}/{len(accounts)}")
        transaction = EGLDTransferBuilder(
            config=tx_config,
            sender=funding_account.address,
            receiver=Address.from_bech32(account.address),
            payment=TokenPayment.egld_from_amount(0.001),
            nonce=funding_account.nonce,
        ).build()
        transaction.signature = signature
        transactions.append(transaction)
        funding_account.nonce += 1

        index += 1

    transactions_chunks = split_to_chunks(transactions, 100)
    for transactions_chunk in transactions_chunks:
        network_providers.proxy.send_transactions(transactions_chunk)


def add_upgrade_command(subparsers, func: Any) -> None:
    """Add upgrade command"""

    command_parser = subparsers.add_parser('upgrade', help='upgrade contarct command')
    command_parser.add_argument('--compare-states', action='store_true',
                                help='compare states before and after upgrade')
    group = command_parser.add_mutually_exclusive_group()
    group.add_argument('--address', type=str, help='contract address')
    group.add_argument('--all', action='store_true', help='run command for all contracts')
    command_parser.set_defaults(func=func)


def add_upgrade_all_command(subparsers, func: Any) -> None:
    """Add upgrade all command"""

    command_parser = subparsers.add_parser('upgrade-all', help='upgrade all contracts command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    command_parser.set_defaults(func=func)


def add_generate_transaction_command(subparsers, func: Any, transaction_name: str, description: str) -> None:
    """Add generate transaction command"""

    command_parser = subparsers.add_parser(transaction_name, help=description)
    command_parser.add_argument('--accounts-export', type=str, help='accounts export file')
    group = command_parser.add_mutually_exclusive_group()
    group.add_argument('--address', type=str, help='contract address')
    group.add_argument('--all', action='store_true', help='generate transaction for all contracts')

    command_parser.set_defaults(func=func)
