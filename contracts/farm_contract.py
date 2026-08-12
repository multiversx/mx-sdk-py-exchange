from typing import Any, Dict

from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue

import config
from contracts.base_contracts import (
    BaseBoostedContract,
    BaseFarmContract,
    BasePermissionsHubContract,
    BaseSCWhitelistContract,
)
from contracts.contract_identities import (
    FarmContractVersion,
    _as_addresses,
    _ConfigField,
    _Endpoint,
)
from events.farm_events import (
    ClaimRewardsFarmEvent,
    CompoundRewardsFarmEvent,
    EnterFarmEvent,
    ExitFarmEvent,
    MergePositionFarmEvent,
    MigratePositionFarmEvent,
)
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.logger import get_logger
from utils.utils_chain import Account, hex_to_string
from utils.utils_chain import WrapperAddress as Address
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_tx import (
    ESDTToken,
    NetworkProviders,
    deploy,
    upgrade_call,
)

logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature, the
# tokens it builds out of the event it was handed, and the argument documentation its callers
# depend on.
#
# The user-facing ten all transfer tokens; the two that claim on someone else's behalf are among
# the three wrappers in the codebase that log a second line naming the endpoint before calling it.
_ENTER_FARM = _Endpoint("enter farm", 100000000, "enterFarm", transfers=True,
                        announces_endpoint=True)
_ENTER_FARM_ON_BEHALF = _Endpoint("enter farm on behalf", 50000000, "enterFarmOnBehalf",
                                  transfers=True, announces_endpoint=True)
_EXIT_FARM = _Endpoint("exit farm", 50000000, "exitFarm", transfers=True)
_CLAIM_REWARDS = _Endpoint("claimRewards", 50000000, "claimRewards", transfers=True)
_CLAIM_REWARDS_ON_BEHALF = _Endpoint("claimRewardsOnBehalf", 50000000, "claimRewardsOnBehalf",
                                     transfers=True)
_CLAIM_BOOSTED_REWARDS = _Endpoint("claimBoostedRewards", 50000000, "claimBoostedRewards")
_COLLECT_UNDISTRIBUTED_BOOSTED_REWARDS = _Endpoint("collectUndistributedBoostedRewards", 500000000,
                                                   "collectUndistributedBoostedRewards")
_COMPOUND_REWARDS = _Endpoint("compoundRewards", 50000000, "compoundRewards", transfers=True)
_MIGRATE_POSITION = _Endpoint("migratePosition", 50000000, "migratePosition", transfers=True)
_MERGE_POSITIONS = _Endpoint("mergeFarmTokens", 50000000, "mergeFarmTokens", transfers=True)
_ALLOW_EXTERNAL_CLAIM = _Endpoint("allowExternalClaimBoostedRewards", 20000000,
                                  "allowExternalClaimBoostedRewards")

_REGISTER_FARM_TOKEN = _Endpoint("Register farm token", 100000000, "registerFarmToken", exactly=2,
                                 build=lambda args: [*args, 18],
                                 value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_SET_LOCAL_ROLES_FARM_TOKEN = _Endpoint("Set local roles for farm token", 100000000,
                                        "setLocalRolesFarmToken")
_SET_TRANSFER_ROLE_FARM_TOKEN = _Endpoint("Set transfer role farm token", 70000000,
                                          "setTransferRoleFarmToken")

_SET_REWARDS_PER_BLOCK = _Endpoint("Set rewards per block in farm", 50000000,
                                   "setPerBlockRewardAmount")
_SET_REWARDS_PER_SECOND = _Endpoint("Set rewards per second in farm", 50000000,
                                    "setPerSecondRewardAmount")
# The only two snake_case endpoints on this contract, and on the staking one: everything the farm
# gained after v1.2 is camelCase.
_SET_PENALTY_PERCENT = _Endpoint("Set penalty percent in farm", 20000000, "set_penalty_percent")
_SET_MINIMUM_FARMING_EPOCHS = _Endpoint("Set minimum farming epochs in farm", 50000000,
                                        "set_minimum_farming_epochs")
_SET_BOOSTED_YIELDS_FACTORS = _Endpoint("Set boosted yield factors", 70000000,
                                        "setBoostedYieldsFactors", exactly=5)
_SET_BOOSTED_YIELDS_REWARDS_PERCENTAGE = _Endpoint("Set boosted yield rewards percentage", 70000000,
                                                   "setBoostedYieldsRewardsPercentage")
_SET_LOCK_EPOCHS = _Endpoint("Set lock epochs in farm", 50000000, "setLockEpochs")

# Alone among the three collaborator setters, this one sends an address rather than the bech32 text
# it was handed. The staking contract's copy of it sends the text, as its two neighbours here do.
_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("Set energy factory address in farm", 70000000,
                                        "setEnergyFactoryAddress", build=_as_addresses)
_SET_LOCKING_ADDRESS = _Endpoint("Set locking sc address in farm", 70000000, "setLockingScAddress")
_UPDATE_OWNER_OR_ADMIN = _Endpoint("Update owner or admin", 70000000, "updateOwnerOrAdmin")

_RESUME = _Endpoint("Resume farm contract", 30000000, "resume")
_PAUSE = _Endpoint("Pause farm contract", 30000000, "pause")
_START_PRODUCE_REWARDS = _Endpoint("Start producing rewards in farm contract", 10000000,
                                   "startProduceRewards")
_END_PRODUCE_REWARDS = _Endpoint("Stop producing rewards in farm contract", 10000000,
                                 "endProduceRewards")


class FarmContract(BaseFarmContract, BaseBoostedContract, BaseSCWhitelistContract, BasePermissionsHubContract):
    _CONFIG_FIELDS = (
        _ConfigField("farmingToken", arg="farming_token"),
        _ConfigField("farmToken", arg="farm_token"),
        _ConfigField("farmedToken", arg="farmed_token"),
        _ConfigField("address"),
        _ConfigField("version", enum=FarmContractVersion),
    )
    _CONTRACT_TOKENS = ("farmToken",)

    def __init__(self, farming_token, farm_token, farmed_token, address, version: FarmContractVersion,
                 proxy_contract=None):
        self.farmingToken = farming_token
        self.farmToken = farm_token
        self.farmedToken = farmed_token
        self.address = address
        self.version = version
        self.last_token_nonce = 0
        self.proxyContract = proxy_contract

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
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk_amount > 0:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        return self._call_endpoint(_ENTER_FARM, user, network_provider.proxy, [tokens])

    def enter_farm_on_behalf(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk and event.farm_tk_amount > 0:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        return self._call_endpoint(_ENTER_FARM_ON_BEHALF, user, network_provider.proxy,
                                   [tokens, Address(event.on_behalf)])

    def exitFarm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        return self._call_endpoint(_EXIT_FARM, user, network_provider.proxy, [tokens])

    def claimRewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        return self._call_endpoint(_CLAIM_REWARDS, user, network_provider.proxy, [tokens])

    def claim_boosted_rewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address} claiming for {event.user}")

        # An event naming no user claims for the caller, which is what an empty argument list means.
        sc_args = [Address(event.user)] if event.user else []
        return self._call_endpoint(_CLAIM_BOOSTED_REWARDS, user, network_provider.proxy, sc_args)

    def claim_rewards_on_behalf(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        return self._call_endpoint(_CLAIM_REWARDS_ON_BEHALF, user, network_provider.proxy, [tokens])

    def collect_undistributed_boosted_rewards(self, proxy: ProxyNetworkProvider, user: Account) -> str:
        logger.debug(f"Account: {user.address}")

        return self._call_endpoint(_COLLECT_UNDISTRIBUTED_BOOSTED_REWARDS, user, proxy, [])

    def compoundRewards(self, network_provider: NetworkProviders, user: Account, event: CompoundRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        return self._call_endpoint(_COMPOUND_REWARDS, user, network_provider.proxy, [tokens])

    def migratePosition(self, network_provider: NetworkProviders, user: Account, event: MigratePositionFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount)]
        return self._call_endpoint(_MIGRATE_POSITION, user, network_provider.proxy,
                                   [tokens, user.address])

    def mergePositions(self, network_provider: NetworkProviders, user:Account, event_list: list[MergePositionFarmEvent]) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farmToken, event.nonce, event.amount) for event in event_list]

        original_caller = next((event.original_caller for event in event_list if hasattr(event, "original_caller")), None)

        sc_args = [tokens]

        # Sent as the bech32 text it arrived as, where every other on-behalf endpoint here converts
        # it to an address first.
        if original_caller:
            sc_args.append(original_caller)

        return self._call_endpoint(_MERGE_POSITIONS, user, network_provider.proxy, sc_args)

    def allow_external_claim(self, network_provider: NetworkProviders, user: Account) -> str:
        logger.debug(f"Account: {user.address}")

        return self._call_endpoint(_ALLOW_EXTERNAL_CLAIM, user, network_provider.proxy, [])

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
        return self._call_endpoint(_REGISTER_FARM_TOKEN, deployer, proxy, args)

    def set_local_roles_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_LOCAL_ROLES_FARM_TOKEN, deployer, proxy, [])

    def set_rewards_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        return self._call_endpoint(_SET_REWARDS_PER_BLOCK, deployer, proxy, [rewards_amount])

    def set_rewards_per_second(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        return self._call_endpoint(_SET_REWARDS_PER_SECOND, deployer, proxy, [rewards_amount])

    def set_penalty_percent(self, deployer: Account, proxy: ProxyNetworkProvider, percent: int):
        return self._call_endpoint(_SET_PENALTY_PERCENT, deployer, proxy, [percent])

    def set_minimum_farming_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, epochs: int):
        return self._call_endpoint(_SET_MINIMUM_FARMING_EPOCHS, deployer, proxy, [epochs])

    def set_boosted_yields_factors(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Only V2Boosted.
        Expecting as args:
        type[int]: max_rewards_factor
        type[int]: user_rewards_energy_const
        type[int]: user_rewards_farm_const
        type[int]: min_energy_amount
        type[int]: min_farm_amount
        """
        return self._call_endpoint(_SET_BOOSTED_YIELDS_FACTORS, deployer, proxy, args)

    def set_boosted_yields_rewards_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, percentage: int):
        """Only V2Boosted.
        """
        return self._call_endpoint(_SET_BOOSTED_YIELDS_REWARDS_PERCENTAGE, deployer, proxy,
                                   [percentage])

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_factory_address: str):
        """Only V2Boosted.
        """
        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy,
                                   [energy_factory_address])

    def set_locking_address(self, deployer: Account, proxy: ProxyNetworkProvider, locking_address: str):
        """Only V2Boosted.
        """
        return self._call_endpoint(_SET_LOCKING_ADDRESS, deployer, proxy, [locking_address])

    def set_lock_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, lock_epochs: int):
        """Only V2Boosted.
        """
        return self._call_endpoint(_SET_LOCK_EPOCHS, deployer, proxy, [lock_epochs])

    def update_owner_or_admin(self, deployer: Account, proxy: ProxyNetworkProvider, old_address: str):
        """Only V2Boosted.
        """
        return self._call_endpoint(_UPDATE_OWNER_OR_ADMIN, deployer, proxy, [old_address])

    def set_transfer_role_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, whitelisted_sc_address: str):
        """Only V2Boosted.
        """
        # No address at all is a supported call rather than a rejected one: it gives the role to the
        # contract itself.
        sc_args = [whitelisted_sc_address] if whitelisted_sc_address else []
        return self._call_endpoint(_SET_TRANSFER_ROLE_FARM_TOKEN, deployer, proxy, sc_args)

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [])

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_PAUSE, deployer, proxy, [])

    def start_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_START_PRODUCE_REWARDS, deployer, proxy, [])

    def end_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_END_PRODUCE_REWARDS, deployer, proxy, [])

    def get_lp_address(self, proxy: ProxyNetworkProvider) -> str:
        return self._query_view(proxy, FarmContractDataFetcher, 'getPairContractManagedAddress',
                                returns=Address, empty="")

    def get_permissions(self, address: str, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, FarmContractDataFetcher, 'getPermissions',
                                [AddressValue.new_from_address(Address(address))], empty=-1)
    
    def get_all_stats(self, proxy: ProxyNetworkProvider, week: int = None) -> Dict[str, Any]:
        all_stats = {}
        all_stats.update(self.get_all_farm_global_stats(proxy))
        all_stats.update(self.get_all_boosted_global_stats(proxy, week))
        return all_stats

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed farm contract: {self.address}")
        log_substep(f"Farming token: {self.farmingToken}")
        log_substep(f"Farmed token: {self.farmedToken}")
        log_substep(f"Farm token: {self.farmToken}")
