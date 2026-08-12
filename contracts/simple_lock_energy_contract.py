from typing import Dict, List, Any

from contracts.contract_identities import (DEXContractInterface, _as_addresses, _ConfigField,
                                           _Endpoint)
from utils.contract_data_fetchers import SimpleLockEnergyContractDataFetcher
from utils import decoding_structures
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue
import config


logger = get_logger(__name__)

# The ESDT issue cost, sent with each of the three token issuances and with nothing else.
_ISSUE_COST = "50000000000000000"


def _issue_arguments(args: list) -> list:
    """A token issued under one name: display name, ticker, decimals."""
    return [args[0], args[0], 18]


# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below is a hand-off to it carrying only
# the signature and the argument documentation its callers depend on.
_ISSUE_LOCKED_LP_TOKEN = _Endpoint("Issue locked LP token", 100000000, "issueLpProxyToken",
                                   build=_issue_arguments, value=_ISSUE_COST)
_ISSUE_LOCKED_FARM_TOKEN = _Endpoint("Issue locked Farm token", 100000000, "issueFarmProxyToken",
                                     build=_issue_arguments, value=_ISSUE_COST)
_ISSUE_LOCKED_TOKEN = _Endpoint("Issue locked token", 100000000, "issueLockedToken",
                                exactly=2, build=lambda args: [*args, 18], value=_ISSUE_COST)

_SET_TRANSFER_ROLE_LOCKED_TOKEN = _Endpoint("Set transfer role locked token", 100000000,
                                            "setTransferRoleLockedToken")
_SET_BURN_ROLE_LOCKED_TOKEN = _Endpoint("set burn roles on locked token for address", 100000000,
                                        "setBurnRoleLockedToken", at_least=1)
_SET_OLD_LOCKED_ASSET_FACTORY = _Endpoint("set old locked asset factory address", 10000000,
                                          "setOldLockedAssetFactoryAddress", at_least=1)
_SET_FEES_COLLECTOR = _Endpoint("set fees collector address", 10000000,
                                "setFeesCollectorAddress", at_least=1)
# Announces itself as the fees collector setter. Copied from the declaration above it and preserved:
# the purpose is what `logs/trace.log` is grepped for, so correcting it is a behaviour change.
_SET_TOKEN_UNSTAKE = _Endpoint("set fees collector address", 10000000,
                               "setTokenUnstakeAddress", at_least=1)

_ADD_LOCK_OPTIONS = _Endpoint("add lock options", 10000000, "addLockOptions", at_least=1)
_REMOVE_LOCK_OPTIONS = _Endpoint("remove lock options", 10000000, "removeLockOptions", at_least=1)
_SET_PENALTY_PERCENTAGE = _Endpoint("set penalty percentage", 10000000, "setPenaltyPercentage",
                                    exactly=2)
_SET_FEES_BURN_PERCENTAGE = _Endpoint("set fees burn percentage", 10000000,
                                      "setFeesBurnPercentage", exactly=1)

_ADD_SC_TO_WHITELIST = _Endpoint("Add SC to Whitelist in simple lock energy contract", 50000000,
                                 "addSCAddressToWhitelist", build=_as_addresses)
_REMOVE_SC_FROM_WHITELIST = _Endpoint("Remove SC from Whitelist in simple lock energy contract",
                                      50000000, "removeSCAddressFromWhitelist", build=_as_addresses)
_ADD_SC_TO_TOKEN_TRANSFER_WHITELIST = _Endpoint(
    "Add SC to Token Transfer Whitelist in simple lock energy contract", 50000000,
    "addToTokenTransferWhitelist", build=_as_addresses)
_REMOVE_SC_FROM_TOKEN_TRANSFER_WHITELIST = _Endpoint(
    "Remove SC from Token Transfer Whitelist in simple lock energy contract", 50000000,
    "removeFromTokenTransferWhitelist", build=_as_addresses)
_ADD_SC_TO_UNLOCKED_TOKEN_MINT_WHITELIST = _Endpoint(
    "Add SCs to Unlocked Token Mint Whitelist in simple lock energy contract", 50000000,
    "addToUnlockedTokenMintWhitelist", build=_as_addresses)
_REMOVE_SC_FROM_UNLOCKED_TOKEN_MINT_WHITELIST = _Endpoint(
    "Remove SCs from Unlocked Token Mint Whitelist in simple lock energy contract", 50000000,
    "removeFromUnlockedTokenMintWhitelist", build=_as_addresses)
_SET_MULTISIG_ADDRESS = _Endpoint("Set multisig address for claims in simple lock energy contract",
                                  10000000, "setMultisigAddress", build=_as_addresses)

_SET_ENERGY_FOR_OLD_TOKENS = _Endpoint(
    "Set energy for old tokens in simple lock energy contract", 50000000, "setEnergyForOldTokens",
    exactly=3, build=lambda args: [Address(args[0]), *args[1:]])
# The same endpoint as above, at a fifth of the gas and with its arguments sent exactly as given.
# Which of the two is right is a behaviour decision; both are preserved as they were.
_SET_ENERGY_ENTRY = _Endpoint("Set energy entry", 10000000, "setEnergyForOldTokens")
_ADJUST_USER_ENERGY = _Endpoint("adjust delta difference for user energy", 10000000,
                                "adjustUserEnergy")

_LOCK_TOKENS = _Endpoint("lock tokens", 10000000, "lockTokens", at_least=2, transfers=True)
_UNLOCK_TOKENS = _Endpoint("unlock tokens", 10000000, "unlockTokens", at_least=1, transfers=True)
_UNLOCK_EARLY = _Endpoint("unlock tokens early", 50000000, "unlockEarly", exactly=1, transfers=True)
_REDUCE_LOCK = _Endpoint("reduce lock period", 20000000, "reduceLockPeriod", exactly=2,
                         transfers=True)
_EXTEND_LOCK = _Endpoint("extend lock period", 10000000, "extendLockingPeriod", exactly=2,
                         transfers=True)
_ADD_LIQUIDITY_LOCKED_TOKEN = _Endpoint("add liquidity for locked token", 20000000,
                                        "addLiquidityLockedToken", exactly=3, transfers=True)
# Announces itself as its add-liquidity neighbour, for the same reason `_SET_TOKEN_UNSTAKE` does.
_REMOVE_LIQUIDITY_LOCKED_TOKEN = _Endpoint("add liquidity for locked token", 20000000,
                                           "removeLiquidityLockedToken", exactly=3, transfers=True)
_ENTER_FARM_LOCKED_TOKEN = _Endpoint("enter farm with locked token", 30000000,
                                     "enterFarmLockedToken", exactly=1, transfers=True)
_EXIT_FARM_LOCKED_TOKEN = _Endpoint("exit farm with locked token", 30000000, "exitFarmLockedToken",
                                    exactly=1, transfers=True)
_CLAIM_FARM_LOCKED_TOKEN = _Endpoint("claim farm with locked token", 30000000,
                                     "farmClaimRewardsLockedToken", exactly=1, transfers=True)

# Announces itself as `resume`, for the same reason `_SET_TOKEN_UNSTAKE` does.
_PAUSE = _Endpoint("Resume simple lock energy contract", 10000000, "pause")
_RESUME = _Endpoint("Resume simple lock energy contract", 10000000, "unpause")


class SimpleLockEnergyContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("base_token"),
        _ConfigField("locked_token"),
        _ConfigField("lp_proxy_token"),
        _ConfigField("farm_proxy_token"),
    )
    _CONTRACT_TOKENS = ("locked_token",)

    def __init__(self, base_token: str, locked_token: str = "", lp_proxy_token: str = "", farm_proxy_token: str = "",
                 address: str = ""):
        self.address = address
        self.base_token = base_token
        self.locked_token = locked_token
        self.lp_proxy_token = lp_proxy_token
        self.farm_proxy_token = farm_proxy_token

    @classmethod
    def load_contract_by_address(cls, address: str):
        data_fetcher = SimpleLockEnergyContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        base_token = hex_to_string(data_fetcher.get_data("getBaseAssetTokenId"))
        locked_token = hex_to_string(data_fetcher.get_data("getLockedTokenId"))

        return SimpleLockEnergyContract(base_token, locked_token, "", "", address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        function_purpose = "Deploy simple lock energy contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 5:
            log_unexpected_args(function_purpose, args)
            return "", ""
        arguments = [
            self.base_token,   # base token id
            args[0],           # legacy token id
            Address(args[1]),   # locked asset factory address
            args[2]   # min migrated token locking epochs
        ]
        lock_fee_pairs = list(zip(args[3], args[4]))
        lock_options = [item for sublist in lock_fee_pairs for item in sublist]
        arguments.extend(lock_options)  # lock_options

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list, no_init=False):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        function_purpose = "Upgrade simple lock energy contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            if len(args) != 5:
                log_unexpected_args(function_purpose, args)
                return ""
            arguments = [
                self.base_token,   # base token id
                args[0],           # legacy token id
                Address(args[1]),   # locked asset factory address
                args[2]   # min migrated token locking epochs
            ]

            lock_fee_pairs = list(zip(args[3], args[4]))
            lock_options = [item for sublist in lock_fee_pairs for item in sublist]
            arguments.extend(lock_options)  # lock_options

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, [])

    def issue_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, locked_lp_token: str):
        return self._call_endpoint(_ISSUE_LOCKED_LP_TOKEN, deployer, proxy, [locked_lp_token])

    def issue_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, locked_lp_token: str):
        return self._call_endpoint(_ISSUE_LOCKED_FARM_TOKEN, deployer, proxy, [locked_lp_token])

    def issue_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_ISSUE_LOCKED_TOKEN, deployer, proxy, args)

    def set_transfer_role_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: new role address; empty will assign the role to the contract itself
        """
        return self._call_endpoint(_SET_TRANSFER_ROLE_LOCKED_TOKEN, deployer, proxy, args)

    def set_burn_role_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: new role address
        """
        return self._call_endpoint(_SET_BURN_ROLE_LOCKED_TOKEN, deployer, proxy, args)

    def set_old_locked_asset_factory(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: old locked asset factory address
        """
        return self._call_endpoint(_SET_OLD_LOCKED_ASSET_FACTORY, deployer, proxy, args)

    def set_fees_collector(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: fees collector address
        """
        return self._call_endpoint(_SET_FEES_COLLECTOR, deployer, proxy, args)

    def set_token_unstake(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token unstake address
        """
        return self._call_endpoint(_SET_TOKEN_UNSTAKE, deployer, proxy, args)

    def add_lock_options(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        return self._call_endpoint(_ADD_LOCK_OPTIONS, deployer, proxy, args)

    def remove_lock_options(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        return self._call_endpoint(_REMOVE_LOCK_OPTIONS, deployer, proxy, args)

    def set_penalty_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: min penalty 0 - 10000
            type[int]: max penalty - 10000
        """
        return self._call_endpoint(_SET_PENALTY_PERCENTAGE, deployer, proxy, args)

    def set_fees_burn_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: burn percentage 0 - 10000
        """
        return self._call_endpoint(_SET_FEES_BURN_PERCENTAGE, deployer, proxy, args)

    def add_sc_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        return self._call_endpoint(_ADD_SC_TO_WHITELIST, deployer, proxy, [contract_address])

    def remove_sc_from_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        return self._call_endpoint(_REMOVE_SC_FROM_WHITELIST, deployer, proxy, [contract_address])

    def add_sc_to_token_transfer_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        return self._call_endpoint(_ADD_SC_TO_TOKEN_TRANSFER_WHITELIST, deployer, proxy,
                                   [contract_address])

    def remove_sc_from_token_transfer_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        return self._call_endpoint(_REMOVE_SC_FROM_TOKEN_TRANSFER_WHITELIST, deployer, proxy,
                                   [contract_address])

    def add_sc_to_unlocked_token_mint_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_addresses: List[str]):
        """ Expected as args:
            type[List[str]]: addresses
        """
        return self._call_endpoint(_ADD_SC_TO_UNLOCKED_TOKEN_MINT_WHITELIST, deployer, proxy,
                                   contract_addresses)

    def remove_sc_from_unlocked_token_mint_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_addresses: List[str]):
        """ Expected as args:
            type[List[str]]: addresses
        """
        return self._call_endpoint(_REMOVE_SC_FROM_UNLOCKED_TOKEN_MINT_WHITELIST, deployer, proxy,
                                   contract_addresses)

    def set_multisig_address(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        return self._call_endpoint(_SET_MULTISIG_ADDRESS, deployer, proxy, [contract_address])

    def set_energy_for_old_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: address
            type[int]: token_amount
            type[int]: energy_amount
        """
        return self._call_endpoint(_SET_ENERGY_FOR_OLD_TOKENS, deployer, proxy, args)

    def lock_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: lock epochs
            opt: type[address]: destination address
        """
        return self._call_endpoint(_LOCK_TOKENS, user, proxy, args)

    def unlock_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            opt: type[address]: destination address
        """
        return self._call_endpoint(_UNLOCK_TOKENS, user, proxy, args)

    def unlock_early(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_UNLOCK_EARLY, user, proxy, args)

    def reduce_lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: epochs to reduce
        """
        return self._call_endpoint(_REDUCE_LOCK, user, proxy, args)

    def extend_lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: new lock option
        """
        return self._call_endpoint(_EXTEND_LOCK, user, proxy, args)

    def add_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        return self._call_endpoint(_ADD_LIQUIDITY_LOCKED_TOKEN, user, proxy, args)

    def remove_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        return self._call_endpoint(_REMOVE_LIQUIDITY_LOCKED_TOKEN, user, proxy, args)

    def enter_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_ENTER_FARM_LOCKED_TOKEN, user, proxy, args)

    def exit_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_EXIT_FARM_LOCKED_TOKEN, user, proxy, args)

    def claim_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        return self._call_endpoint(_CLAIM_FARM_LOCKED_TOKEN, user, proxy, args)

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_PAUSE, deployer, proxy, [])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [])

    def set_energy_entry(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: user address
            type[str]: energy
            type[str]: amount
        """
        return self._call_endpoint(_SET_ENERGY_ENTRY, deployer, proxy, args)

    def adjust_user_energy(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: user address
            type[str]: energy
            type[str]: amount
        """
        return self._call_endpoint(_ADJUST_USER_ENERGY, deployer, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed simple lock energy contract: {self.address}")
        log_substep(f"Base token: {self.base_token}")
        log_substep(f"Locked token: {self.locked_token}")
        log_substep(f"Locked LP token: {self.lp_proxy_token}")
        log_substep(f"Locked Farm token: {self.farm_proxy_token}")

    def get_lock_options(self, proxy: ProxyNetworkProvider) -> List[Dict[str, Any]]:
        return self._query_view(proxy, SimpleLockEnergyContractDataFetcher, "getLockOptions",
                                returns=[decoding_structures.LOCK_OPTIONS])

    def get_energy_for_user(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        return self._query_view(proxy, SimpleLockEnergyContractDataFetcher, 'getEnergyEntryForUser',
                                [AddressValue.new_from_address(Address(user_address))],
                                returns=decoding_structures.ENERGY_ENTRY)
