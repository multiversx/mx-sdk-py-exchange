from typing import Any
from contracts.base_contracts import BaseBoostedContract
from contracts.pair_contract import PairContract
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider, SmartContractTransactionsFactory, TransactionComputer
from multiversx_sdk.abi import Abi, U64Value, StringValue
from utils.contract_data_fetchers import FeeCollectorContractDataFetcher


logger = get_logger(__name__)
transaction_computer = TransactionComputer()

class FeesCollectorContract(BaseBoostedContract):
    def __init__(self, address: str = ""):
        self.address = address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return FeesCollectorContract(address=config_dict['address'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

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
        function_purpose = f"Add known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        print(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownContracts", sc_args)

    def add_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Add known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addKnownTokens", args)

    def remove_known_contracts(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Remove known contract in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000 + len(args) * 1000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownContracts", sc_args)

    def remove_known_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: tokens
        """
        function_purpose = f"Remove known tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeKnownTokens", sc_args)

    def add_reward_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        function_purpose = f"Add reward tokens in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addRewardTokens", args)
    
    def remove_reward_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        function_purpose = f"Remove reward tokens from fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 80000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeRewardTokens", args)

    def add_admin(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Add admin in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addAdmin", sc_args)
    
    def remove_admin(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Remove admin in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeAdmin", sc_args)

    def add_sc_address_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: Address):
        """ Expected as args:
                type[str..]: addresses
        """
        function_purpose = f"Add SC address to whitelist in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addSCAddressToWhitelist", sc_args)

    def remove_sc_address_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, args: Address):
        """ Expected as args:
                type[str..]: addresse
        """
        function_purpose = f"Remove SC address to whitelist in fees collector contract"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeSCAddressToWhitelist", sc_args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, factory_address: str):
        """ Expected as args:
                    type[str]: energy factory address
        """
        function_purpose = f"Set Energy factory address in fees collector contract"
        logger.info(function_purpose)

        if not factory_address:
            log_unexpected_args(function_purpose, factory_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(factory_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress", sc_args)

    def set_router_address(self, deployer: Account, proxy: ProxyNetworkProvider, router_address: str):
        """ Expected as args:
            type[str]: router address
        """
        function_purpose = f"Set router address in fees collector"
        logger.info(function_purpose)

        if not router_address:
            log_unexpected_args(function_purpose, router_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(router_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setRouterAddress", sc_args)

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """ Expected as args:
            type[str]: locking address
        """
        function_purpose = f"Set locking address in fees collector"
        logger.info(function_purpose)

        if not locking_address:
            log_unexpected_args(function_purpose, locking_address)
            return ""

        gas_limit = 30000000
        sc_args = [
            Address(locking_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingScAddress", sc_args)

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        function_purpose = f"Set lock epochs in fees collector"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            lock_epochs
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockEpochs", sc_args)

    def set_locked_tokens_per_epoch(self, deployer: Account, proxy: ProxyNetworkProvider, locked_tokens_per_epoch: int):
        function_purpose = f"Set locked tokens per epoch"
        logger.info(function_purpose)

        gas_limit = 5000000
        sc_args = [
            locked_tokens_per_epoch
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockedTokensPerEpoch", sc_args)

    def set_base_token_burn_percent(self, deployer: Account, proxy: ProxyNetworkProvider, base_token_burn_percentage: int):
        function_purpose = f"Set base token burn percentage"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            base_token_burn_percentage
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setBaseTokenBurnPercent", sc_args)

    def claim_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimRewards", sc_args)
    
    def claim_boosted_rewards(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Claim rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "claimBoostedRewards", sc_args)

    def redistribute_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Redistribute rewards from fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "redistributeRewards", sc_args)
    
    def deposit_swap_fees(self, user: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Deposit swap fees in fees collector"
        logger.info(function_purpose)

        gas_limit = 80000000
        sc_args = [
        ]
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "depositSwapFees", sc_args)

    def swap_to_base_token(self, user: Account, proxy: ProxyNetworkProvider, abi: Abi, sc_args: list):
        """ Expected as args:
            token[str]: token address
            swap_operations[list]: `swap_operations` are pairs of (pair address, pair function name, token wanted, min amount out)" -> Address,bytes,TokenIdentifier,BigUint
                "\"pair function name\" can only be \"swapTokensFixedInput\" or \"swapTokensFixedOutput\\",
                "\"min amount out\" is a minimum of 1"
        """

        function_purpose = f"Swap tokens to base token in fees collector"
        logger.info(function_purpose)   
        gas_limit = 80000000

        return endpoint_call(proxy, gas_limit, user, Address(self.address), "swapTokenToBaseToken", sc_args, abi = abi)
    
    def get_reward_tokens(self, proxy: ProxyNetworkProvider) -> list[str]:
        """Query the contract for the list of reward tokens.
        
        Returns:
            list[str]: List of reward token addresses
        """
        
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        hex_results = data_fetcher.get_data("getRewardTokens")
        if not hex_results:
            return []
            
        return [hex_to_string(token) for token in hex_results]
    
    def get_accumulated_fees(self, proxy: ProxyNetworkProvider, token: str) -> int:
        """Query the contract for the accumulated fees (current week).
        
        Returns:
            int: accumulated fees for token
        """
        
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        current_week = self.get_current_week(proxy)
        result = data_fetcher.get_data("getAccumulatedFees", [U64Value(current_week), StringValue(token)])
        if not result:
            return 0
            
        return int(result)
    
    def get_total_rewards_for_week(self, proxy: ProxyNetworkProvider, week: int, abi: Abi) -> int:
        """Query the contract for rewards to distribute in a specific week (last 4 weeks).
        
        Returns:
            list[TokenPayment]: List of reward tokens
        """        
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        hex_results = data_fetcher.get_data("getTotalRewardsForWeek", [U64Value(week)])
        if not hex_results:
            return []
        
        decoded = abi.decode_endpoint_output_parameters("getTotalRewardsForWeek", [bytes.fromhex(hex_results)])
        if len(decoded) == 0:
            return []
        return decoded[0]
    
    def get_rewards_claimed(self, proxy: ProxyNetworkProvider, week: int, token: str) -> int:
        """Query the contract for rewards claimed in a specific week (last 4 weeks).
        
        Returns:
            int: rewards claimed for week
        """
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        result = data_fetcher.get_data("getRewardsClaimed", [U64Value(week), StringValue(token)])
        if not result:
            return 0
            
        return int(result)
    
    def get_known_contracts(self, proxy: ProxyNetworkProvider) -> list[str]:
        """Query the contract for the list of reward tokens.
        
        Returns:
            list[str]: List of known contract addresses
        """
        data_fetcher = FeeCollectorContractDataFetcher(Address(self.address), proxy.url)
        hex_results = data_fetcher.get_data("getAllKnownContracts")
        if not hex_results:
            return []
            
        return [Address.from_hex(address).to_bech32() for address in hex_results]
    
    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed fees collector contract: {self.address}")

