import sys
import traceback
import config

from contracts.contract_identities import (DEXContractInterface, PairContractVersion,
                                           _as_addresses, _ConfigField, _Endpoint,
                                           _leading_addresses)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import NetworkProviders, upgrade_call, deploy, ESDTToken
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature, the
# tokens it builds out of the event it was handed, and the argument documentation its callers
# depend on.
#
# The five user-facing ones all transfer tokens, and all five name the account they sign with at
# debug from their own bodies: nothing further down the stack logs who signed.
_SWAP_TOKENS_FIXED_INPUT = _Endpoint("swapFixedInput", 20000000, "swapTokensFixedInput",
                                     transfers=True)
_SWAP_TOKENS_FIXED_OUTPUT = _Endpoint("swap tokens fixed output", 50000000,
                                      "swapTokensFixedOutput", transfers=True)
_ADD_LIQUIDITY = _Endpoint("addLiquidity", 20000000, "addLiquidity", transfers=True)
_ADD_INITIAL_LIQUIDITY = _Endpoint("addInitialLiquidity", 20000000, "addInitialLiquidity",
                                   transfers=True)
_REMOVE_LIQUIDITY = _Endpoint("remove liquidity", 20000000, "removeLiquidity", transfers=True)

_WHITELIST = _Endpoint("Whitelist contract in pair", 100000000, "whitelist", build=_as_addresses)
_REMOVE_WHITELIST = _Endpoint("Remove whitelist contract in pair", 100000000, "removeWhitelist",
                              build=_as_addresses)
# Announces the purpose of `whitelist_contract` above it, word for word, while calling a different
# endpoint. The purpose is what `logs/trace.log` is grepped for, so it is preserved as declared.
_ADD_TRUSTED_SWAP_PAIR = _Endpoint("Whitelist contract in pair", 100000000, "addTrustedSwapPair",
                                   exactly=3, build=_leading_addresses(1))

# The two cheapest calls on any contract in the DEX, at a twentieth of what their neighbours spend.
_SETUP_FEES_COLLECTOR = _Endpoint("Setup fees collector in pair", 5500000, "setupFeesCollector",
                                  exactly=2, build=_leading_addresses(1))
_SET_FEE_PERCENTS = _Endpoint("Set fees in pair contract", 5000000, "setFeePercents", exactly=2)

_SET_LOCKING_DEADLINE_EPOCH = _Endpoint("Set locking deadline epoch in pool", 100000000,
                                        "setLockingDeadlineEpoch")
_SET_UNLOCK_EPOCH = _Endpoint("Set unlock epoch in pool", 100000000, "setUnlockEpoch")
_SET_LOCKING_SC_ADDRESS = _Endpoint("Set locking contract address in pool", 100000000,
                                    "setLockingScAddress", build=_as_addresses)

_RESUME = _Endpoint("Resume swaps in pool", 10000000, "resume")
_SET_STATE_ACTIVE_NO_SWAPS = _Endpoint("Set pair active no swaps", 10000000,
                                       "setStateActiveNoSwaps")


class SwapFixedInputEvent:
    def __init__(self, tokenA: str, amountA: int, tokenB: str, amountBmin: int):
        self.tokenA = tokenA
        self.amountA = amountA
        self.tokenB = tokenB
        self.amountBmin = amountBmin


class SwapFixedOutputEvent:
    def __init__(self, tokenA: str, amountAmax: int, tokenB: str, amountB: int):
        self.tokenA = tokenA
        self.amountAmax = amountAmax
        self.tokenB = tokenB
        self.amountB = amountB


class AddLiquidityEvent:
    def __init__(self, tokenA: str, amountA: int, amountAmin: int, tokenB: str, amountB: int, amountBmin: int):
        self.tokenA = tokenA
        self.amountA = amountA
        self.amountAmin = amountAmin
        self.tokenB = tokenB
        self.amountB = amountB
        self.amountBmin = amountBmin


class RemoveLiquidityEvent:
    def __init__(self, amount: int, tokenA: str, amountA: int, tokenB: str, amountB: int):
        self.amount = amount
        self.tokenA = tokenA
        self.amountA = amountA
        self.tokenB = tokenB
        self.amountB = amountB


class SetCorrectReservesEvent:
    pass


class PairContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("firstToken"),
        _ConfigField("secondToken"),
        _ConfigField("lpToken"),
        _ConfigField("address"),
        _ConfigField("version", enum=PairContractVersion),
    )
    _CONTRACT_TOKENS = ("lpToken",)

    def __init__(self, firstToken: str, secondToken: str,  version: PairContractVersion,
                 lpToken: str = "", address: str = "", proxy_contract=None):
        self.firstToken = firstToken
        self.secondToken = secondToken
        self.version = version
        self.lpToken = lpToken
        self.address = address
        self.proxy_contract = proxy_contract

    @classmethod
    def load_contract_by_address(cls, address: str, version=PairContractVersion.V2, proxy_contract=None):
        data_fetcher = PairContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        first_token = hex_to_string(data_fetcher.get_data("getFirstTokenId"))
        second_token = hex_to_string(data_fetcher.get_data("getSecondTokenId"))
        lp_token = hex_to_string(data_fetcher.get_data("getLpTokenIdentifier"))

        if not first_token or not second_token:
            return None

        return PairContract(first_token, second_token, version, lp_token, address, proxy_contract)

    def hasProxy(self) -> bool:
        if self.proxy_contract is not None:
            return True
        return False

    def swap_fixed_input(self, network_provider: NetworkProviders, user: Account, event: SwapFixedInputEvent):
        logger.debug(f"Account: {user.address}")
        logger.debug(f"{event.amountA} {event.tokenA} for minimum {event.amountBmin} {event.tokenB}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountA)]

        return self._call_endpoint(_SWAP_TOKENS_FIXED_INPUT, user, network_provider.proxy,
                                   [tokens, event.tokenB, event.amountBmin])

    def swap_fixed_output(self, network_provider: NetworkProviders, user: Account, event: SwapFixedOutputEvent):
        logger.debug(f"Account: {user.address}")
        logger.debug(f"Maximum {event.amountAmax} {event.tokenA} for {event.amountB} {event.tokenB}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountAmax)]

        return self._call_endpoint(_SWAP_TOKENS_FIXED_OUTPUT, user, network_provider.proxy,
                                   [tokens, event.tokenB, event.amountB])

    def add_liquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountA),
                  ESDTToken(event.tokenB, 0, event.amountB)]

        return self._call_endpoint(_ADD_LIQUIDITY, user, network_provider.proxy,
                                   [tokens, event.amountAmin, event.amountBmin])

    def add_initial_liquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountA),
                  ESDTToken(event.tokenB, 0, event.amountB)]

        return self._call_endpoint(_ADD_INITIAL_LIQUIDITY, user, network_provider.proxy, [tokens])

    def remove_liquidity(self, network_provider: NetworkProviders, user: Account, event: RemoveLiquidityEvent):
        logger.debug(f"Account: {user.address}")

        # Alone among the five, the token identifier is the contract's rather than the event's.
        tokens = [ESDTToken(self.lpToken, 0, event.amount)]

        return self._call_endpoint(_REMOVE_LIQUIDITY, user, network_provider.proxy,
                                   [tokens,
                                    event.amountA,   # slippage first token
                                    event.amountB])  # slippage second token

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[str]: router address
            type[str]: whitelisted owner address
            type[str]: initial liquidity adder address (v2 required)
            type[any]: fee percentage
            type[any]: special fee
            type[str..]: admin addresses (v2 required)
        """
        function_purpose = f"Deploy pair contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)
        
        gas_limit = 200000000

        if len(args) < 5:
            log_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return "", ""

        arguments = [
            self.firstToken,
            self.secondToken,
            Address(args[0]),
            Address(args[1]),
            args[3],
            args[4],
            args[2]
        ]

        if self.version == PairContractVersion.V2:
            arguments.extend(args[5:])

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list, no_init: bool = False):
        """Expecting as args:
            type[str]: router address
            type[str]: whitelisted owner address
            type[str]: initial liquidity adder address (v2 required)
            type[any]: fee percentage
            type[any]: special fee
            type[str..]: admin addresses (v2 required)
        """
        function_purpose = f"Upgrade pair contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)
        
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            if len(args) < 5:
                log_unexpected_args(function_purpose, args)
                return ""

            arguments = [
                self.firstToken,
                self.secondToken,
                Address(args[0]),
                Address(args[1]),
                args[3],
                args[4],
                args[2]
            ]

            if self.version == PairContractVersion.V2:
                arguments.extend(args[5:])

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, arguments)

    def contract_deploy_via_router(self, deployer: Account, proxy: ProxyNetworkProvider, router_contract, args: list):
        """ Expected as args:
            type[str]: initial liquidity adder address
            type[any]: total fee percentage
            type[any]: special fee percentage
            type[str..]: admin addresses
        """
        pair_args = [self.firstToken, self.secondToken]
        pair_args.extend(args)
        tx_hash, address = router_contract.pair_contract_deploy(deployer, proxy, pair_args)
        return tx_hash, address

    def contract_upgrade_via_router(self, deployer: Account, proxy: ProxyNetworkProvider, router_contract, args: list) -> str:
        """ Expected as args:
            type[int]: total fee percentage
            type[int]: special fee percentage
            type[str]: initial liquidity adder
        """
        pair_args = [self.firstToken, self.secondToken]
        pair_args.extend(args)
        tx_hash = router_contract.pair_contract_upgrade(deployer, proxy, pair_args)
        return tx_hash

    def view_contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[str]: linked contract address
        """
        function_purpose = f"Deploy view contract for pair"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)

        gas_limit = 200000000

        if len(args) != 1:
            log_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return "", ""

        arguments = [
            Address(args[0]),
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def issue_lp_token_via_router(self, deployer: Account, proxy: ProxyNetworkProvider, router_contract, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Issue LP token via router"
        logger.info(function_purpose)

        if len(args) < 2:
            log_unexpected_args(function_purpose, args)
            return ""

        tx_hash = router_contract.issue_lp_token(deployer, proxy, [self.address, args[0], args[1]])
        return tx_hash

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_WHITELIST, deployer, proxy, [contract_to_whitelist])

    def remove_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_remove: str):
        return self._call_endpoint(_REMOVE_WHITELIST, deployer, proxy, [contract_to_remove])

    def add_trusted_swap_pair(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: trusted swap pair address
            type[str]: trusted pair first token identifier
            type[str]: trusted pair second token identifier
        """
        return self._call_endpoint(_ADD_TRUSTED_SWAP_PAIR, deployer, proxy, args)

    def add_fees_collector(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: fees collector address
            type[str]: fees cut
        """
        return self._call_endpoint(_SETUP_FEES_COLLECTOR, deployer, proxy, args)

    def set_fees_percents(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: total fee percent
            type[str]: special fee percent
        """
        return self._call_endpoint(_SET_FEE_PERCENTS, deployer, proxy, args)

    def set_lp_token_local_roles_via_router(self, deployer: Account, proxy: ProxyNetworkProvider, router_contract):
        function_purpose = f"Set lp token local roles via router"
        logger.info(function_purpose)
        tx_hash = router_contract.set_lp_token_local_roles(deployer, proxy, self.address)
        return tx_hash

    def set_fee_on_via_router(self, deployer: Account, proxy: ProxyNetworkProvider, router_contract, args: list):
        """ Expected as args:
            type[str]: address to receive fees
            type[str]: expected token
        """
        function_purpose = f"Set fee on via router"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        tx_hash = router_contract.set_fee_on(deployer, proxy, [self.address, args[0], args[1]])
        return tx_hash

    def set_locking_deadline_epoch(self, deployer: Account, proxy: ProxyNetworkProvider, epoch: int):
        return self._call_endpoint(_SET_LOCKING_DEADLINE_EPOCH, deployer, proxy, [epoch])

    def set_unlock_epoch(self, deployer: Account, proxy: ProxyNetworkProvider, epoch: int):
        return self._call_endpoint(_SET_UNLOCK_EPOCH, deployer, proxy, [epoch])

    def set_locking_sc_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        return self._call_endpoint(_SET_LOCKING_SC_ADDRESS, deployer, proxy, [locking_address])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [])

    def set_active_no_swaps(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_STATE_ACTIVE_NO_SWAPS, deployer, proxy, [])


    def get_safe_price_round_save_interval(self, proxy: ProxyNetworkProvider):
        return self._query_view(proxy, PairContractDataFetcher, "getSafePriceRoundSaveInterval")

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list | None = None):
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed pair contract: {self.address}")
        log_substep(f"First token: {self.firstToken}")
        log_substep(f"Second token: {self.secondToken}")
        log_substep(f"LP token: {self.lpToken}")
