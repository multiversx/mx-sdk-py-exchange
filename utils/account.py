import logging
from pathlib import Path
from typing import Any, Optional
from multiversx_sdk_core import Address, MessageV1, Transaction
from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_wallet import UserSigner


logger = logging.getLogger("accounts")


class AccountBase():
    def __init__(self, address: Any = None):
        self.address = Address(address, "erd")
        self.nonce: int = 0

    def sync_nonce(self, proxy: ProxyNetworkProvider):
        logger.debug("AccountBase.sync_nonce()")
        self.nonce = proxy.get_account(self.address).nonce
        logger.debug(f"AccountBase.sync_nonce() done: {self.nonce}")

    def sign_transaction(self, transaction: Transaction) -> str:
        raise NotImplementedError

    def sign_message(self, data: bytes) -> str:
        raise NotImplementedError


class Account(AccountBase):
    def __init__(self,
                 address: Any = None,
                 pem_file: Optional[str] = None,
                 pem_index: int = 0,
                 key_file: str = "",
                 password: str = ""):
        super().__init__(address)

        if pem_file:
            pem_path = Path(pem_file).expanduser().resolve()
            self.signer = UserSigner.from_pem_file(pem_path, pem_index)
            self.address = Address(self.signer.get_pubkey().buffer, "erd")
        elif key_file and password:
            key_file_path = Path(key_file).expanduser().resolve()
            self.signer = UserSigner.from_wallet(key_file_path, password)
            self.address = Address(self.signer.get_pubkey().buffer, "erd")

    def sign_transaction(self, transaction: Transaction) -> str:
        assert self.signer is not None
        return self.signer.sign(transaction).hex()

    def sign_message(self, data: bytes) -> str:
        assert self.signer is not None
        message = MessageV1(data)
        signature = self.signer.sign(message)

        logger.debug(f"Account.sign_message(): raw_data_to_sign = {data.hex()}, message_data_to_sign = {message.serialize_for_signing().hex()}, signature = {signature.hex()}")
        return signature.hex()
