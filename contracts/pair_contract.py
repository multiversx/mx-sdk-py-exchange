import sys
import traceback
import config

from contracts.contract_identities import (DEXContractInterface, PairContractVersion)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import NetworkProviders, endpoint_call, upgrade_call, deploy, ESDTToken, multi_esdt_endpoint_call
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


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
    def __init__(self, firstToken: str, secondToken: str,  version: PairContractVersion,
                 lpToken: str = "", address: str = "", proxy_contract=None):
        self.firstToken = firstToken
        self.secondToken = secondToken
        self.version = version
        self.lpToken = lpToken
        self.address = address
        self.proxy_contract = proxy_contract

    def get_config_dict(self) -> dict:
        output_dict = {
            "firstToken": self.firstToken,
            "secondToken": self.secondToken,
            "lpToken": self.lpToken,
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return PairContract(firstToken=config_dict['firstToken'],
                            secondToken=config_dict['secondToken'],
                            lpToken=config_dict['lpToken'],
                            address=config_dict['address'],
                            version=PairContractVersion(config_dict['version']))
    
    def get_contract_tokens(self) -> list[str]:
        return [self.lpToken]

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
        function_purpose = f"swapFixedInput"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")
        logger.debug(f"{event.amountA} {event.tokenA} for minimum {event.amountBmin} {event.tokenB}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.tokenA, 0, event.amountA)]
        sc_args = [tokens,
                   event.tokenB,
                   event.amountBmin]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), "swapTokensFixedInput", sc_args)

    def swap_fixed_output(self, network_provider: NetworkProviders, user: Account, event: SwapFixedOutputEvent):
        function_purpose = f"swap tokens fixed output"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")
        logger.debug(f"Maximum {event.amountAmax} {event.tokenA} for {event.amountB} {event.tokenB}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.tokenA, 0, event.amountAmax)]
        sc_args = [tokens,
                   event.tokenB,
                   event.amountB]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), "swapTokensFixedOutput", sc_args)

    def add_liquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        function_purpose = f"addLiquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountA),
                  ESDTToken(event.tokenB, 0, event.amountB)]
        sc_args = [
            tokens,
            event.amountAmin,
            event.amountBmin,
        ]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, 20000000,
                                        user, Address(self.address), "addLiquidity", sc_args)

    def add_initial_liquidity(self, network_provider: NetworkProviders, user: Account, event: AddLiquidityEvent):
        function_purpose = f"addInitialLiquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.tokenA, 0, event.amountA),
                  ESDTToken(event.tokenB, 0, event.amountB)]

        sc_args = [tokens]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, 20000000,
                                        user, Address(self.address), "addInitialLiquidity", sc_args)

    def remove_liquidity(self, network_provider: NetworkProviders, user: Account, event: RemoveLiquidityEvent):
        function_purpose = f"remove liquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 20000000

        tokens = [ESDTToken(self.lpToken, 0, event.amount)]
        sc_args = [tokens,
                   event.amountA,   # slippage first token
                   event.amountB    # slippage second token
                   ]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), "removeLiquidity", sc_args)

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
        function_purpose = f"Whitelist contract in pair"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(contract_to_whitelist)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "whitelist", sc_args)

    def add_trusted_swap_pair(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: trusted swap pair address
            type[str]: trusted pair first token identifier
            type[str]: trusted pair second token identifier
        """
        function_purpose = f"Whitelist contract in pair"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            Address(args[0]),
            args[1],
            args[2]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addTrustedSwapPair", sc_args)

    def add_fees_collector(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: fees collector address
            type[str]: fees cut
        """
        function_purpose = f"Setup fees collector in pair"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 5000000
        sc_args = [
            Address(args[0]),
            args[1]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setupFeesCollector", sc_args)

    def set_fees_percents(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: total fee percent
            type[str]: special fee percent
        """
        function_purpose = f"Set fees in pair contract"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 5000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setFeePercents", sc_args)

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
        function_purpose = f"Set locking deadline epoch in pool"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            epoch
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingDeadlineEpoch", sc_args)

    def set_unlock_epoch(self, deployer: Account, proxy: ProxyNetworkProvider, epoch: int):
        function_purpose = f"Set unlock epoch in pool"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            epoch
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setUnlockEpoch", sc_args)

    def set_locking_sc_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        function_purpose = f"Set locking contract address in pool"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(locking_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingScAddress", sc_args)

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Resume swaps in pool"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "resume", sc_args)

    def set_active_no_swaps(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Set pair active no swaps"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setStateActiveNoSwaps", sc_args)
    
    def get_safe_price_round_save_interval(self, proxy: ProxyNetworkProvider):
        data_fetcher = PairContractDataFetcher(Address(self.address), proxy.url)
        return data_fetcher.get_data("getSafePriceRoundSaveInterval")

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed pair contract: {self.address}")
        log_substep(f"First token: {self.firstToken}")
        log_substep(f"Second token: {self.secondToken}")
        log_substep(f"LP token: {self.lpToken}")
