
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils import utils_generic as utils
from utils.utils_chain import WrapperAddress as Address
from multiversx_sdk_network_providers.tokens import FungibleTokenOfAccountOnNetwork


class BunchOfTracks:
    def __init__(self, prefix: str = "") -> None:
        self.accounts_by_token: Dict[str, Any] = dict()
        self.tokens_by_holder: Dict[List[str]] = dict()
        self.all_tokens: List[str] = []
        self.prefix = prefix.upper()

    def put_for_account(self, address: Address, tokens: List[FungibleTokenOfAccountOnNetwork]):
        for token in tokens:
            if not token.identifier.startswith(self.prefix):
                continue

            balance = token.balance

            if token not in self.accounts_by_token:
                self.accounts_by_token[token.identifier] = dict()

            self.accounts_by_token[token.identifier][address.bech32()] = balance

    def put_all_tokens(self, tokens: List[str]):
        self.all_tokens = [token for token in tokens if token.startswith(self.prefix)]

    def get_all_tokens(self) -> List[str]:
        return self.all_tokens

    def get_all_individual_assets(self) -> List[Tuple[Address, str]]:
        result: List[Tuple[Address, str]] = []

        for key in self.accounts_by_token:
            address = self.accounts_by_token[key]
            result.append((address, key))

        return result

    def get_whale(self, identifier: str) -> Address:
        holders = self.accounts_by_token[identifier]

        max_balance = 0
        whale = None

        for holder in holders:
            balance = int(holders[holder])

            if balance > max_balance:
                max_balance = balance
                whale = holder

        return Address(whale)

    @classmethod
    def load(cls, file: str) -> BunchOfTracks:
        instance = cls()
        if not Path(file).exists():
            return instance

        with open(file) as f:
            data = json.load(f)

        instance.accounts_by_token = data.get("accounts_by_token", dict())
        instance.all_tokens = data.get("all_tokens", [])
        instance.build_index_tokens_by_holder()

        return instance

    def save(self, file: str):
        print(file)
        utils.ensure_folder(Path(file).parent)
        utils.write_json_file(str(file), {
            "accounts_by_token": self.accounts_by_token,
            "all_tokens": self.all_tokens
        })

    def build_index_tokens_by_holder(self):
        print("build_index_tokens_by_holder - begin")

        for token in self.accounts_by_token:
            holders = self.accounts_by_token[token]

            for address in holders:
                if address not in self.tokens_by_holder:
                    self.tokens_by_holder[address] = []

                self.tokens_by_holder[address].append(token)

        print("build_index_tokens_by_holder - end")

    def get_tokens_by_holder(self, address: Address):
        result = self.tokens_by_holder.get(address.bech32(), [])
        return result
