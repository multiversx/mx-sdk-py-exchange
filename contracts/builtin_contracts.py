from enum import Enum

from utils.logger import get_logger
from contracts.contract_identities import _Endpoint, _EndpointCaller, _leading_addresses
from utils.utils_chain import Account
from multiversx_sdk import ProxyNetworkProvider

logger = get_logger(__name__)

# The chain's own builtin endpoints, one declaration each. Neither class here implements
# `DEXContractInterface` — there is nothing to deploy, upgrade or serialize — so both take their
# dispatch from `_EndpointCaller` alone, which asks for an address and nothing else.
#
# The two role endpoints are the reason `detail` exists: each describes what it is about to do in
# terms of the arguments themselves, so the line can only be written once the count is known to be
# right. `set_special_role_token` reads everything past the address as roles, which is why its check
# is a minimum where its opposite number's is exact.
_ISSUE = _Endpoint("issue token", 100000000, "issue", at_least=4, value="50000000000000000")
_REGISTER_META_ESDT = _Endpoint("issue meta esdt token", 100000000, "registerMetaESDT", at_least=4,
                                value="50000000000000000")
_ESDT_NFT_CREATE = _Endpoint("create token", 50000000, "ESDTNFTCreate", at_least=3)
_SET_SPECIAL_ROLE = _Endpoint(
    "set special role for token", 100000000, "setSpecialRole", at_least=3,
    build=lambda args: [args[0], *_leading_addresses(1)(args[1:])],
    detail=lambda args: f"Setting ESDT roles {args[2:]} for {args[0]} on address {args[1]}")
_UNSET_SPECIAL_ROLE = _Endpoint(
    "unset special role for token", 10000000, "unsetSpecialRole", exactly=3,
    build=lambda args: [args[0], *_leading_addresses(1)(args[1:])],
    detail=lambda args: f"Set ESDT role {args[2]} for {args[0]} on address {args[1]}")


def _at_least_nine_blocks(args: list) -> list:
    """The epoch count, and a block count of at least nine.

    The one argument builder in `contracts/` that changes a value rather than converting it: the
    shadowfork controller cannot advance an epoch in fewer than nine blocks, so a caller asking for
    fewer gets nine and a warning. The warning is here rather than in the wrapper because it belongs
    with the clamp, and because it must follow the two lines the declaration itself writes.
    """
    epochs, blocks_per_epoch = args
    if blocks_per_epoch < 9:
        logger.warning("Blocks per epoch is less than 9; defaulting to 9.")
        blocks_per_epoch = 9
    return [epochs, blocks_per_epoch]


_EPOCHS_FAST_FORWARD = _Endpoint("fast forward epoch", 13000000, "epochsFastForward",
                                 build=_at_least_nine_blocks,
                                 detail=lambda args: f"Fast forwarding {args[0]} epochs")


class ESDTRoles(Enum):
    ESDTRoleLocalMint = 1
    ESDTRoleLocalBurn = 2


class ESDTContract(_EndpointCaller):
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
        return self._call_endpoint(_ISSUE, token_owner, proxy, args)

    def issue_meta_esdt_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token name
                type[str]: token ticker
                type[int]: supply
                type[int]: decimals
                type[str...]: properties
        """
        return self._call_endpoint(_REGISTER_META_ESDT, token_owner, proxy, args)

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
        return self._call_endpoint(_ESDT_NFT_CREATE, token_owner, proxy, args)

    def set_special_role_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str]: token_id
                type[str]: address to assign role to
                type[str..]: roles name: ESDTRoleLocalBurn, ESDTRoleLocalMint, ESDTTransferRole
            """
        return self._call_endpoint(_SET_SPECIAL_ROLE, token_owner, proxy, args)

    def unset_special_role_token(self, token_owner: Account, proxy: ProxyNetworkProvider, args: list):
        return self._call_endpoint(_UNSET_SPECIAL_ROLE, token_owner, proxy, args)


class SFControlContract(_EndpointCaller):
    def __init__(self, sf_control_address: str):
        self.address = sf_control_address

    def epochs_fast_forward(self, caller: Account, proxy: ProxyNetworkProvider, epochs: int, blocks_per_epoch: int):
        return self._call_endpoint(_EPOCHS_FAST_FORWARD, caller, proxy, [epochs, blocks_per_epoch])
