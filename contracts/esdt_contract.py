from enum import Enum

from utils.logger import get_logger
from utils.utils_tx import endpoint_call
from utils.utils_generic import log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_network_providers import ProxyNetworkProvider

logger = get_logger(__name__)


class ESDTRoles(Enum):
    ESDTRoleLocalMint = 1
    ESDTRoleLocalBurn = 2


class ESDTContract:
    def __init__(self, esdt_address):
        self.address = esdt_address

    def set_special_role_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token_id
                type[str]: address to assign role to
                type[str]: role name
            """
        function_purpose = "set special role for token"
        logger.info(function_purpose)
        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""
        token_id = args[0]
        address = args[1]
        role = args[2]
        logger.info(f"Setting ESDT role {role} for {token_id} on address {address}")

        gas_limit = 100000000
        sc_args = [
            token_id,
            Address(address),
            role
        ]
        return endpoint_call(proxy, gas_limit, token_owner, Address(self.address), "setSpecialRole", sc_args)

    def unset_special_role_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        function_purpose = "unset special role for token"
        logger.info(function_purpose)
        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""
        token_id = args[0]
        address = args[1]
        role = args[2]
        logger.info(f"Set ESDT role {role} for {token_id} on address {address}")

        gas_limit = 10000000
        sc_args = [
            token_id,
            Address(address),
            role
        ]
        return endpoint_call(proxy, gas_limit, token_owner, Address(self.address), "unsetSpecialRole", sc_args)
