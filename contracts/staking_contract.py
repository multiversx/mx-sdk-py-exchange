import config
from contracts.contract_identities import DEXContractInterface, StakingContractVersion
from utils.logger import get_logger
from utils.utils_tx import NetworkProviders, ESDTToken, multi_esdt_endpoint_call, deploy, upgrade_call, endpoint_call
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from events.farm_events import (EnterFarmEvent, ExitFarmEvent,
                                ClaimRewardsFarmEvent, CompoundRewardsFarmEvent)


logger = get_logger(__name__)


class StakingContract(DEXContractInterface):
    def __init__(self, farming_token: str, max_apr: int, rewards_per_block: int, unbond_epochs: int,
                 version: StakingContractVersion, farm_token: str = "", address: str = ""):
        self.farming_token = farming_token
        self.farm_token = farm_token
        self.farmed_token = farming_token
        self.address = address
        self.max_apr = max_apr
        self.rewards_per_block = rewards_per_block
        self.unbond_epochs = unbond_epochs
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "farming_token": self.farming_token,
            "farm_token": self.farm_token,
            "address": self.address,
            "max_apr": self.max_apr,
            "rewards_per_block": self.rewards_per_block,
            "unbond_epochs": self.unbond_epochs,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return StakingContract(farming_token=config_dict['farming_token'],
                               farm_token=config_dict['farm_token'],
                               address=config_dict['address'],
                               max_apr=config_dict['max_apr'],
                               rewards_per_block=config_dict['rewards_per_block'],
                               unbond_epochs=config_dict['unbond_epochs'],
                               version=StakingContractVersion(config_dict['version']))

    def stake_farm(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent,
                   initial: bool = False) -> str:
        stake_farm_fn = "stakeFarm"
        logger.info(f"{stake_farm_fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if not initial:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))
        args = [tokens]

        return multi_esdt_endpoint_call(stake_farm_fn, network_provider.proxy, gas_limit, user,
                                        Address(self.address), stake_farm_fn, args)

    def unstake_farm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        unstake_fn = 'unstakeFarm'
        logger.info(f"{unstake_fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farm_token, event.nonce, event.amount)]
        args = [tokens]

        return multi_esdt_endpoint_call(unstake_fn, network_provider.proxy, gas_limit, user,
                                        Address(self.address), unstake_fn, args)

    def unbond_farm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        unbond_fn = 'unbondFarm'
        logger.info(f"{unbond_fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000

        tokens = [ESDTToken(event.farm_token, event.nonce, event.amount)]
        args = [tokens]

        return multi_esdt_endpoint_call(unbond_fn, network_provider.proxy, gas_limit, user,
                                        Address(self.address), unbond_fn, args)

    def claim_rewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        claim_fn = 'claimRewards'
        logger.info(f"{claim_fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000

        tokens = [ESDTToken(self.farm_token, event.nonce, event.amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(claim_fn, network_provider.proxy, gas_limit, user,
                                        Address(self.address), claim_fn, sc_args)

    def compound_rewards(self, network_provider: NetworkProviders, user: Account, event: CompoundRewardsFarmEvent) -> str:
        compound_fn = 'compoundRewards'
        logger.info(f"{compound_fn}")
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        tokens = [ESDTToken(self.farm_token, event.nonce, event.amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(compound_fn, network_provider.proxy, gas_limit, user,
                                        Address(self.address), compound_fn, sc_args)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """Expecting as args:percent
        type[str]: owner address - only from v2
        type[str]: admin address - only from v2
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        function_purpose = f"Deploy staking contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)
        gas_limit = 200000000

        arguments = [
            self.farming_token,
            1000000000000,
            self.max_apr,
            self.unbond_epochs
        ]
        if self.version == StakingContractVersion.V2 or self.version == StakingContractVersion.V3Boosted:
            arguments.extend(args)

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = [],
                         yes: bool = True):
        """Expecting as args:percent
        type[str]: owner address - only from v2
        type[str]: admin address - only from v2
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        function_purpose = f"Upgrade staking contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)
        gas_limit = 200000000

        arguments = [
            self.farming_token,
            1000000000000,
            self.max_apr,
            self.unbond_epochs,
        ]
        if self.version == StakingContractVersion.V2 or self.version == StakingContractVersion.V3Boosted:
            arguments.extend(args)

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, arguments)

    def register_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Register stake token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "registerFarmToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def set_local_roles_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Set local roles for stake token"
        logger.info(function_purpose)
        gas_limit = 100000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRolesFarmToken", sc_args)

    def set_rewards_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        function_purpose = f"Set rewards per block in stake contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            rewards_amount
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setPerBlockRewardAmount", sc_args)

    def topup_rewards(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        function_purpose = f"Topup rewards in stake contract"
        logger.info(function_purpose)

        gas_limit = 50000000

        tokens = [ESDTToken(self.farmed_token, 0, rewards_amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, deployer,
                                        Address(self.address), "topUpRewards", sc_args)

    def set_boosted_yields_factors(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Only V3Boosted.
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
        """Only V3Boosted.
        """
        function_purpose = "Set boosted yield rewards percentage"
        logger.info(function_purpose)

        gas_limit = 70000000
        sc_args = [percentage]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setBoostedYieldsRewardsPercentage",
                             sc_args)

    def collect_undistributed_boosted_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Resume stake contract"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "collectUndistributedBoostedRewards",
                             sc_args)

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Resume stake contract"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "resume", sc_args)

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Pause stake contract"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "pause", sc_args)

    def start_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Start producing rewards in stake contract"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "startProduceRewards", sc_args)

    def end_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Stop producing rewards in stake contract"
        logger.info(function_purpose)

        gas_limit = 10000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "endProduceRewards", sc_args)

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = f"Whitelist contract in staking"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_to_whitelist)
        ]

        endpoint_name = "addAddressToWhitelist" if self.version == StakingContractVersion.V1 \
            else "addSCAddressToWhitelist"
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), endpoint_name, sc_args)

    def set_burn_role_for_address(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = f"Set burn role for address"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_to_whitelist)
        ]

        endpoint_name = "setBurnRoleForAddress"
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), endpoint_name, sc_args)

    def add_admin(self, deployer: Account, proxy: ProxyNetworkProvider, address_to_whitelist: str):
        function_purpose = f"Add admin"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(address_to_whitelist)
        ]

        endpoint_name = "addAdmin"
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), endpoint_name, sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed staking contract: {self.address}")
        log_substep(f"Staking token: {self.farming_token}")
        log_substep(f"Stake token: {self.farm_token}")
