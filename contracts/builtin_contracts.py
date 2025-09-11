from enum import Enum

from utils.logger import get_logger
from utils.utils_tx import endpoint_call
from utils.utils_generic import log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import ProxyNetworkProvider

logger = get_logger(__name__)


class ESDTRoles(Enum):
    ESDTRoleLocalMint = 1
    ESDTRoleLocalBurn = 2


class ESDTContract:
    def __init__(self, esdt_address):
        self.address = esdt_address

    def issue_fungible_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token name
                type[str]: token ticker
                type[int]: supply
                type[int]: decimals
                type[str...]: properties
        """
        function_purpose = "issue token"
        logger.info(function_purpose)
        if len(args) < 4:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, token_owner, Address(self.address), "issue", sc_args, value="50000000000000000")
    
    def issue_meta_esdt_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token name
                type[str]: token ticker
                type[int]: supply
                type[int]: decimals
                type[str...]: properties
        """
        function_purpose = "issue meta esdt token"
        logger.info(function_purpose)
        if len(args) < 4:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, token_owner, Address(self.address), "registerMetaESDT", sc_args, value="50000000000000000")
    
    def create_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token id
                type[int]: initial quantity
                type[str]: name
                type[int]: royalties
                type[str]: hash
                type[str]: attributes
                type[str...]: uri
        """
        function_purpose = "create token"
        logger.info(function_purpose)
        if len(args) < 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, token_owner, Address(self.address), "ESDTNFTCreate", sc_args)

    def set_special_role_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token_id
                type[str]: address to assign role to
                type[str..]: roles name: ESDTRoleLocalBurn, ESDTRoleLocalMint, ESDTTransferRole
            """
        function_purpose = "set special role for token"
        logger.info(function_purpose)
        if len(args) < 3:
            log_unexpected_args(function_purpose, args)
            return ""
        token_id = args[0]
        address = args[1]
        roles = args[2:]
        logger.info(f"Setting ESDT roles {roles} for {token_id} on address {address}")

        gas_limit = 100000000
        sc_args = [
            token_id,
            Address(address),
        ]
        sc_args.extend(roles)
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


class SFControlContract:
    def __init__(self, sf_control_address: str):
        self.address = sf_control_address
    
    def epochs_fast_forward(self, caller: Account, proxy: ProxyNetworkProvider, epochs: int, blocks_per_epoch: int):
        function_purpose = "fast forward epoch"
        logger.info(function_purpose)
        logger.info(f"Fast forwarding {epochs} epochs")
        gas_limit = 13000000

        if blocks_per_epoch < 9:
            logger.warning("Blocks per epoch is less than 9; defaulting to 9.")
            blocks_per_epoch = 9

        sc_args = [
            epochs,
            blocks_per_epoch
        ]
        return endpoint_call(proxy, gas_limit, caller, Address(self.address), "epochsFastForward", sc_args)
