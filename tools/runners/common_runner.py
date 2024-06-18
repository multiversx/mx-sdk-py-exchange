import json
from typing import Any, List


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


def add_upgrade_command(subparsers, func: Any) -> None:
    """Add upgrade command"""

    command_parser = subparsers.add_parser('upgrade', help='upgrade contarct command')
    command_parser.add_argument('--compare-states', action='store_true',
                        help='compare states before and after upgrade')
    command_parser.add_argument('--address', type=str, help='contract address')
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
    command_parser.add_argument('--address', type=str, help='contract address')
    command_parser.add_argument('--accounts-export', type=str, help='accounts export file')
    command_parser.set_defaults(func=func)
