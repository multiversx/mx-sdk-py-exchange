import config
from contracts.contract_identities import FarmContractVersion, DEXContractInterface
from contracts.base_contracts import (BaseFarmContract, BaseBoostedContract, 
                                      BaseSCWhitelistContract, BasePermissionsHubContract)
from utils import decoding_structures
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import NetworkProviders, ESDTToken, \
    multi_esdt_endpoint_call, deploy, upgrade_call, endpoint_call
from utils.utils_chain import Account, WrapperAddress as Address, base64_to_hex, decode_merged_attributes, get_all_token_nonces_details_for_account, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from events.farm_events import (EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent,
                                CompoundRewardsFarmEvent, MigratePositionFarmEvent)
from typing import Dict, Any

logger = get_logger(__name__)


class FarmContract(BaseFarmContract, BaseBoostedContract, BaseSCWhitelistContract, BasePermissionsHubContract):
    def __init__(self, farming_token, farm_token, farmed_token, address, version: FarmContractVersion,
                 proxy_contract=None):
        self.farmingToken = farming_token
        self.farmToken = farm_token
        self.farmedToken = farmed_token
        self.address = address
        self.version = version
        self.last_token_nonce = 0
        self.proxyContract = proxy_contract

    def get_config_dict(self) -> dict:
        output_dict = {
            "farmingToken": self.farmingToken,
            "farmToken": self.farmToken,
            "farmedToken": self.farmedToken,
            "address": self.address,
            "version": self.version.value,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return FarmContract(farming_token=config_dict['farmingToken'],
                            farm_token=config_dict['farmToken'],
                            farmed_token=config_dict['farmedToken'],
                            address=config_dict['address'],
                            version=FarmContractVersion(config_dict['version']))
    
    def get_contract_tokens(self) -> list[str]:
        return [self.farmToken]

    @classmethod
    def load_contract_by_address(cls, address: str):
        data_fetcher = FarmContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        farming_token = hex_to_string(data_fetcher.get_data("getFarmingTokenId"))
        farm_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
        farmed_token = hex_to_string(data_fetcher.get_data("getRewardTokenId"))
        version = FarmContractVersion.V2Boosted    # TODO: find a way to determine this automatically

        if not farming_token or not farmed_token:
            return None

        return FarmContract(farming_token, farm_token, farmed_token, address, version)

    def has_proxy(self) -> bool:
        if self.proxyContract is not None:
            return True
        return False

    def enterFarm(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent) -> str:
        # TODO: remove initial parameter by using the event data
        function_purpose = "enter farm"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        enterFarmFn = "enterFarm"
        logger.info(f"Calling {enterFarmFn} endpoint...")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk_amount > 0:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        sc_args = [tokens]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), enterFarmFn, sc_args)
    
    def enter_farm_on_behalf(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent) -> str:
        function_purpose = "enter farm on behalf"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        enterFarmFn = "enterFarmOnBehalf"

        logger.info(f"Calling {enterFarmFn} endpoint...")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        sc_args = [tokens,
                   Address(event.on_behalf)]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), enterFarmFn, sc_args)

    def exitFarm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        function_purpose = f"exit farm"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        sc_args = [
            tokens
        ]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "exitFarm", sc_args)

    def claimRewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        function_purpose = f"claimRewards"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        sc_args = [
            tokens
        ]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "claimRewards", sc_args)
    
    def claim_boosted_rewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        claim_fn = 'claimBoostedRewards'
        logger.info(f"{claim_fn}")
        logger.debug(f"Account: {user.address} claiming for {event.user}")

        gas_limit = 50000000

        sc_args = [Address(event.user)] if event.user else []
        return endpoint_call(network_provider.proxy, gas_limit, user, Address(self.address), claim_fn, sc_args)
    
    def claim_rewards_on_behalf(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        function_purpose = f"claimRewardsOnBehalf"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        sc_args = [
            tokens
        ]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "claimRewardsOnBehalf", sc_args)


    def compoundRewards(self, network_provider: NetworkProviders, user: Account, event: CompoundRewardsFarmEvent) -> str:
        function_purpose = f"compoundRewards"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        sc_args = [
            tokens
        ]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "compoundRewards", sc_args)

    def collectUndistributedRewards(self, network_provider: NetworkProviders, user: Account, weeks: list) -> str:
        function_purpose = f"collectUndistributedBoostedRewards"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        sc_args = []
        return endpoint_call(network_provider.proxy, gas_limit, user,
                                        Address(self.address), "collectUndistributedBoostedRewards", weeks)

    def migratePosition(self, network_provider: NetworkProviders, user: Account, event: MigratePositionFarmEvent) -> str:
        function_purpose = f"migratePosition"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        sc_args = [
            tokens,
            user.address
        ]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "migratePosition", sc_args)
    
    def allow_external_claim(self, network_provider: NetworkProviders, user: Account) -> str:
        fn = 'allowExternalClaimBoostedRewards'
        logger.info(f"{fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 20000000

        return endpoint_call(network_provider.proxy, gas_limit, user, Address(self.address), fn, [])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:percent
        type[str]: pair contract address
        type[str]: locked asset factory address (only V14Locked)
        type[str]: admin address (only V2Boosted)
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 350000000
        address = ""
        tx_hash = ""

        if (self.version in [FarmContractVersion.V12, FarmContractVersion.V14Unlocked] and len(args) < 1) or \
           (self.version in [FarmContractVersion.V14Locked, FarmContractVersion.V2Boosted] and len(args) != 2):
            log_unexpected_args(f"{function_purpose} version {self.version.name}", args)
            return tx_hash, address

        arguments = [
            self.farmedToken,
            self.farmingToken,
            1000000000000,
            Address(args[0])
        ]
        if self.version == FarmContractVersion.V14Locked:
            arguments.insert(2, Address(args[1]))
        if self.version == FarmContractVersion.V2Boosted:
            arguments.append(deployer.address)
            if args[1]:
                arguments.append(Address(args[1]))

        logger.debug(f"Arguments: {arguments}")

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = [],
                         no_init: bool = False):
        """Expecting as args:
        type[str]: pair contract address
        type[str]: locked asset factory address (only V14Locked)
        type[str]: admin address (only V2Boosted)
        self.version has to be initialized to correctly attempt the upgrade for that specific type of farm.
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 350000000
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            if (self.version in [FarmContractVersion.V12, FarmContractVersion.V14Unlocked] and len(args) < 1) or \
               (self.version in [FarmContractVersion.V14Locked, FarmContractVersion.V2Boosted] and len(args) != 2):
                log_unexpected_args(f"{function_purpose} version {self.version.name}", args)
                return tx_hash

            arguments = [
                self.farmedToken,
                self.farmingToken,
                1000000000000,
                Address(args[0])
            ]
            if self.version == FarmContractVersion.V14Locked:
                arguments.insert(2, Address(args[1]))
            if self.version == FarmContractVersion.V2Boosted:
                arguments.append(deployer.address)
                if args[1]:
                    arguments.append(Address(args[1]))

        logger.debug(f"Arguments: {arguments}")

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, arguments)
        return tx_hash

    def register_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:percent
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = "Register farm token"
        logger.info(function_purpose)
        tx_hash = ""

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]

        logger.debug(f"Arguments: {sc_args}")

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "registerFarmToken", sc_args,
                             config.DEFAULT_ISSUE_TOKEN_PRICE)

    def set_local_roles_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Set local roles for farm token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRolesFarmToken", sc_args)

    def set_rewards_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        function_purpose = "Set rewards per block in farm"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            rewards_amount
        ]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setPerBlockRewardAmount", sc_args)

    def set_penalty_percent(self, deployer: Account, proxy: ProxyNetworkProvider, percent: int):
        function_purpose = "Set penalty percent in farm"
        logger.info(function_purpose)

        gas_limit = 20000000
        sc_args = [
            percent
        ]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "set_penalty_percent", sc_args)

    def set_minimum_farming_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, epochs: int):
        function_purpose = "Set minimum farming epochs in farm"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            epochs
        ]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "set_minimum_farming_epochs", sc_args)

    def set_boosted_yields_factors(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Only V2Boosted.
        Expecting as args:
        type[int]: max_rewards_factor
        type[int]: user_rewards_energy_const
        type[int]: user_rewards_farm_const
        type[int]: min_energy_amount
        type[int]: min_farm_amount
        """
        function_purpose = "Set boosted yield factors"
        logger.info(function_purpose)

        if len(args) != 5:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 70000000
        sc_args = args
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setBoostedYieldsFactors", sc_args)

    def set_boosted_yields_rewards_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, percentage: int):
        """Only V2Boosted.
        """
        function_purpose = "Set boosted yield rewards percentage"
        logger.info(function_purpose)

        gas_limit = 70000000
        sc_args = [percentage]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setBoostedYieldsRewardsPercentage",
                             sc_args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_factory_address: str):
        """Only V2Boosted.
        """
        function_purpose = "Set energy factory address in farm"
        logger.info(function_purpose)

        gas_limit = 70000000
        sc_args = [Address(energy_factory_address)]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress", sc_args)

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """Only V2Boosted.
        """
        function_purpose = "Set locking sc address in farm"
        logger.info(function_purpose)

        gas_limit = 70000000
        sc_args = [locking_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockingScAddress", sc_args)

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        """Only V2Boosted.
        """
        function_purpose = "Set lock epochs in farm"
        logger.info(function_purpose)
        
        gas_limit = 50000000
        sc_args = [lock_epochs]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLockEpochs", sc_args)
    
    def update_owner_or_admin(self, deployer: Account, proxy: ProxyNetworkProvider, old_address: str):
        """Only V2Boosted.
        """
        function_purpose = "Update owner or admin"
        logger.info(function_purpose)
        
        gas_limit = 70000000
        sc_args = [old_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "updateOwnerOrAdmin", sc_args)
    
    def set_transfer_role_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str):
        """Only V2Boosted.
        """
        function_purpose = "Set transfer role farm token"
        logger.info(function_purpose)

        gas_limit = 70000000
        sc_args = [whitelisted_sc_address] if whitelisted_sc_address else []
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setTransferRoleFarmToken", sc_args)

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Resume farm contract"
        logger.info(function_purpose)
        
        gas_limit = 30000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "resume", sc_args)

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Pause farm contract"
        logger.info(function_purpose)
        
        gas_limit = 30000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "pause", sc_args)

    def start_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Start producing rewards in farm contract"
        logger.info(function_purpose)
        
        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "startProduceRewards", sc_args)

    def end_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Stop producing rewards in farm contract"
        logger.info(function_purpose)
        
        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "endProduceRewards", sc_args)

    def get_lp_address(self, proxy: ProxyNetworkProvider) -> str:
        data_fetcher = FarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getPairContractManagedAddress')
        if not raw_results:
            return ""
        address = Address.from_hex(raw_results).bech32()

        return address
    
    def get_permissions(self, address: str, proxy: ProxyNetworkProvider) -> int:
        data_fetcher = FarmContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getPermissions', [Address(address).get_public_key()])
        if not raw_results:
            return -1
        return int(raw_results)
    
    def get_all_stats(self, proxy: ProxyNetworkProvider, week: int = None) -> Dict[str, Any]:
        all_stats = {}
        all_stats.update(self.get_all_farm_global_stats(proxy))
        all_stats.update(self.get_all_boosted_global_stats(proxy, week))
        return all_stats

    def get_user_farm_token_stats(self, user: Account, proxy: ProxyNetworkProvider):
        tokens_in_account = get_all_token_nonces_details_for_account(self.farmingToken, user.address.bech32(), proxy)
        print(f'Account: {user.address.bech32()}')
        print(f'Looking for {self.farmingToken} and {self.farmToken} tokens')
        print(f'Farming Tokens in account:')
        for token in tokens_in_account:
            print(f'\t{token}')
        tokens_in_account = get_all_token_nonces_details_for_account(self.farmToken, user.address.bech32(), proxy)
        print(f'Farm Tokens in account:')
        all_decoded_attributes = []
        for token in tokens_in_account:
            print(f'\t{token}')
            decoded_attributes = decode_merged_attributes(base64_to_hex(token["attributes"]), decoding_structures.FARM_TOKEN_ATTRIBUTES)
            print(f'\t\t{decoded_attributes}')
            all_decoded_attributes.append(decoded_attributes)
            
        return all_decoded_attributes

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed farm contract: {self.address}")
        log_substep(f"Farming token: {self.farmingToken}")
        log_substep(f"Farmed token: {self.farmedToken}")
        log_substep(f"Farm token: {self.farmToken}")
