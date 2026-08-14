from typing import Any
from contracts.base_contracts import BaseBoostedContract
from contracts.contract_identities import _as_addresses, _ConfigField, _Endpoint
from contracts.pair_contract import PairContract
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider, SmartContractTransactionsFactory, TransactionComputer
from multiversx_sdk.abi import Abi, U64Value, StringValue
from utils.contract_data_fetchers import FeeCollectorContractDataFetcher


logger = get_logger(__name__)
transaction_computer = TransactionComputer()

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# The four list endpoints disagree about gas in a way that reads as an oversight: adding tokens and
# removing contracts pay 1M per entry on top of their base, while removing tokens and adding
# contracts — the same work in the other direction — pay a flat 10M. Preserved as declared.
_ADD_KNOWN_CONTRACTS = _Endpoint("Add known contract in fees collector contract", 10000000,
                                 "addKnownContracts", at_least=1)
_ADD_KNOWN_TOKENS = _Endpoint("Add known tokens in fees collector contract", 10000000,
                              "addKnownTokens", at_least=1, gas_per_argument=1000000)
_REMOVE_KNOWN_CONTRACTS = _Endpoint("Remove known contract in fees collector contract", 10000000,
                                    "removeKnownContracts", at_least=1, gas_per_argument=1000000)
_REMOVE_KNOWN_TOKENS = _Endpoint("Remove known tokens in fees collector contract", 10000000,
                                 "removeKnownTokens", at_least=1)

_ADD_REWARD_TOKENS = _Endpoint("Add reward tokens in fees collector contract", 10000000,
                               "addRewardTokens", at_least=1)
_REMOVE_REWARD_TOKENS = _Endpoint("Remove reward tokens from fees collector contract", 80000000,
                                  "removeRewardTokens", at_least=1)

_ADD_ADMIN = _Endpoint("Add admin in fees collector contract", 10000000, "addAdmin", at_least=1)
_REMOVE_ADMIN = _Endpoint("Remove admin in fees collector contract", 10000000, "removeAdmin",
                          at_least=1)
_ADD_SC_ADDRESS_TO_WHITELIST = _Endpoint("Add SC address to whitelist in fees collector contract",
                                         10000000, "addSCAddressToWhitelist", at_least=1)
_REMOVE_SC_ADDRESS_TO_WHITELIST = _Endpoint(
    "Remove SC address to whitelist in fees collector contract", 10000000,
    "removeSCAddressToWhitelist", at_least=1)

# All three collaborator setters convert the bech32 text they are handed, and all three refuse an
# empty one — where the DEX proxy's seven equivalents do neither.
_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("Set Energy factory address in fees collector contract",
                                        30000000, "setEnergyFactoryAddress", rejects_empty=True,
                                        build=_as_addresses)
_SET_ROUTER_ADDRESS = _Endpoint("Set router address in fees collector", 30000000,
                                "setRouterAddress", rejects_empty=True, build=_as_addresses)
_SET_LOCKING_ADDRESS = _Endpoint("Set locking address in fees collector", 30000000,
                                 "setLockingScAddress", rejects_empty=True, build=_as_addresses)

_SET_LOCK_EPOCHS = _Endpoint("Set lock epochs in fees collector", 30000000, "setLockEpochs")
_SET_LOCKED_TOKENS_PER_EPOCH = _Endpoint("Set locked tokens per epoch", 5000000,
                                         "setLockedTokensPerEpoch")
_SET_BASE_TOKEN_BURN_PERCENT = _Endpoint("Set base token burn percentage", 30000000,
                                         "setBaseTokenBurnPercent")

_CLAIM_REWARDS = _Endpoint("Claim rewards from fees collector", 80000000, "claimRewards")
_CLAIM_BOOSTED_REWARDS = _Endpoint("Claim boosted rewards from fees collector", 80000000,
                                   "claimBoostedRewards")
_REDISTRIBUTE_REWARDS = _Endpoint("Redistribute rewards from fees collector", 80000000,
                                  "redistributeRewards")
_DEPOSIT_SWAP_FEES = _Endpoint("Deposit swap fees in fees collector", 80000000, "depositSwapFees")
# The one endpoint in `contracts/` whose caller hands it an `Abi`, to encode the nested swap
# operations; the ABI travels as an argument to `_call_endpoint` rather than as an axis here.
_SWAP_TOKEN_TO_BASE_TOKEN = _Endpoint("Swap tokens to base token in fees collector", 80000000,
                                      "swapTokenToBaseToken")


class FeesCollectorContract(BaseBoostedContract):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        return FeesCollectorContract(address=address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
            type[str]: locked token
            type[str]: energy factory address
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return "", ""

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            args[0],
            Address(args[1])
        ]
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address
    
    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None,
                         no_init: bool = False):
        """ Expected as args:
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            # implement below in case of upgrade args needed
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)

        return tx_hash

    def add_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        # The only Endpoint Wrapper in `contracts/` that echoes its arguments to stdout; every
        # other one leaves that to the `Args: …` line `endpoint_call` logs at debug.
        print(f"Arguments: {args}")
        return self._call_endpoint(_ADD_KNOWN_CONTRACTS, deployer, proxy, args)

    def add_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        return self._call_endpoint(_ADD_KNOWN_TOKENS, deployer, proxy, args)

    def remove_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        return self._call_endpoint(_REMOVE_KNOWN_CONTRACTS, deployer, proxy, args)

    def remove_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        return self._call_endpoint(_REMOVE_KNOWN_TOKENS, deployer, proxy, args)

    def add_reward_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        return self._call_endpoint(_ADD_REWARD_TOKENS, deployer, proxy, args)

    def remove_reward_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        return self._call_endpoint(_REMOVE_REWARD_TOKENS, deployer, proxy, args)

    def add_admin(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        return self._call_endpoint(_ADD_ADMIN, deployer, proxy, args)

    def remove_admin(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        return self._call_endpoint(_REMOVE_ADMIN, deployer, proxy, args)

    def add_sc_address_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: Address):
        """ Expected as args:
                type[str..]: addresses
        """
        return self._call_endpoint(_ADD_SC_ADDRESS_TO_WHITELIST, deployer, proxy, args)

    def remove_sc_address_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: Address):
        """ Expected as args:
                type[str..]: addresse
        """
        return self._call_endpoint(_REMOVE_SC_ADDRESS_TO_WHITELIST, deployer, proxy, args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, factory_address: str):
        """ Expected as args:
                    type[str]: energy factory address
        """
        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy, [factory_address])

    def set_router_address(self, deployer: Account, proxy: ProxyNetworkProvider, router_address: str):
        """ Expected as args:
            type[str]: router address
        """
        return self._call_endpoint(_SET_ROUTER_ADDRESS, deployer, proxy, [router_address])

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """ Expected as args:
            type[str]: locking address
        """
        return self._call_endpoint(_SET_LOCKING_ADDRESS, deployer, proxy, [locking_address])

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        return self._call_endpoint(_SET_LOCK_EPOCHS, deployer, proxy, [lock_epochs])

    def set_locked_tokens_per_epoch(self, deployer: Account, proxy: ProxyNetworkProvider, locked_tokens_per_epoch: int):
        return self._call_endpoint(_SET_LOCKED_TOKENS_PER_EPOCH, deployer, proxy,
                                   [locked_tokens_per_epoch])

    def set_base_token_burn_percent(self, deployer: Account, proxy: ProxyNetworkProvider, base_token_burn_percentage: int):
        return self._call_endpoint(_SET_BASE_TOKEN_BURN_PERCENT, deployer, proxy,
                                   [base_token_burn_percentage])

    def claim_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_CLAIM_REWARDS, user, proxy, [])

    def claim_boosted_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_CLAIM_BOOSTED_REWARDS, user, proxy, [])

    def redistribute_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_REDISTRIBUTE_REWARDS, deployer, proxy, [])

    def deposit_swap_fees(self, user: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_DEPOSIT_SWAP_FEES, user, proxy, [])

    def swap_to_base_token(self, user: Account, proxy: ProxyNetworkProvider, abi: Abi, sc_args: list):
        """ Expected as args:
            token[str]: token address
            swap_operations[list]: `swap_operations` are pairs of (pair address, pair function name, token wanted, min amount out)" -> Address,bytes,TokenIdentifier,BigUint
                "\"pair function name\" can only be \"swapTokensFixedInput\" or \"swapTokensFixedOutput\\",
                "\"min amount out\" is a minimum of 1"
        """
        return self._call_endpoint(_SWAP_TOKEN_TO_BASE_TOKEN, user, proxy, sc_args, abi=abi)


    def get_reward_tokens(self, proxy: ProxyNetworkProvider) -> list[str]:
        """Query the contract for the list of reward tokens.
        
        Returns:
            list[str]: List of reward token addresses
        """
        
        return self._query_view(proxy, FeeCollectorContractDataFetcher, "getRewardTokens",
                                returns=[str])

    def get_accumulated_fees(self, proxy: ProxyNetworkProvider, token: str) -> int:
        """Query the contract for the accumulated fees (current week).

        Returns:
            int: accumulated fees for token
        """
        current_week = self.get_current_week(proxy)
        return self._query_view(proxy, FeeCollectorContractDataFetcher, "getAccumulatedFees",
                                [U64Value(current_week), StringValue(token)])

    def get_total_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int, abi: Abi) -> int:
        """Query the contract for rewards to distribute in a specific week (last 4 weeks).

        Returns:
            list[TokenPayment]: List of reward tokens
        """
        def decode_rewards(hex_result: str):
            decoded = abi.decode_endpoint_output_parameters("getTotalRewardsForWeek",
                                                            [bytes.fromhex(hex_result)])
            return decoded[0] if decoded else []

        return self._query_view(proxy, FeeCollectorContractDataFetcher, "getTotalRewardsForWeek",
                                [U64Value(week)], returns=decode_rewards, empty=[])

    def get_rewards_claimed(self, proxy: ProxyNetworkProvider, week: int, token: str) -> int:
        """Query the contract for rewards claimed in a specific week (last 4 weeks).

        Returns:
            int: rewards claimed for week
        """
        return self._query_view(proxy, FeeCollectorContractDataFetcher, "getRewardsClaimed",
                                [U64Value(week), StringValue(token)])

    def get_known_contracts(self, proxy: ProxyNetworkProvider) -> list[str]:
        """Query the contract for the list of reward tokens.

        Returns:
            list[str]: List of known contract addresses
        """
        return self._query_view(proxy, FeeCollectorContractDataFetcher, "getAllKnownContracts",
                                returns=[Address])
    
    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed fees collector contract: {self.address}")

