from typing import Any, Dict
import config
from contracts.contract_identities import (StakingContractVersion, _as_addresses, _ConfigField,
                                           _Endpoint)
from contracts.base_contracts import (BaseFarmContract, BaseBoostedContract,
                                      BaseSCWhitelistContract, BasePermissionsHubContract)
from utils.logger import get_logger
from utils.utils_tx import NetworkProviders, ESDTToken, deploy, upgrade_call
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string, base64_to_hex
from utils.contract_data_fetchers import StakingContractDataFetcher
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider, Token
from multiversx_sdk.abi import AddressValue
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from events.farm_events import (EnterFarmEvent, ExitFarmEvent,
                                ClaimRewardsFarmEvent, CompoundRewardsFarmEvent)

from utils.decoding_structures import STAKE_V1_TOKEN_ATTRIBUTES, STAKE_V2_TOKEN_ATTRIBUTES, STAKE_UNBOND_TOKEN_ATTRIBUTES


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature, the
# tokens it builds out of the event it was handed, and the argument documentation its callers
# depend on.
#
# Read alongside `farm_contract.py`: the two contracts wrap the same boosted-farm endpoints, and
# the purposes differ only in saying "stake contract" where the farm says "farm".
_STAKE_FARM = _Endpoint("stakeFarm", 50000000, "stakeFarm", transfers=True)
_STAKE_FARM_ON_BEHALF = _Endpoint("stake farm on behalf", 50000000, "stakeFarmOnBehalf",
                                  transfers=True, announces_endpoint=True)
_UNSTAKE_FARM = _Endpoint("unstakeFarm", 50000000, "unstakeFarm", transfers=True)
_UNBOND_FARM = _Endpoint("unbondFarm", 50000000, "unbondFarm", transfers=True)
_CLAIM_REWARDS = _Endpoint("claimRewards", 50000000, "claimRewards", transfers=True)
_CLAIM_REWARDS_ON_BEHALF = _Endpoint("claimRewardsOnBehalf", 50000000, "claimRewardsOnBehalf",
                                     transfers=True)
_CLAIM_BOOSTED_REWARDS = _Endpoint("claimBoostedRewards", 50000000, "claimBoostedRewards")
_COLLECT_UNDISTRIBUTED_BOOSTED_REWARDS = _Endpoint("collectUndistributedBoostedRewards", 500000000,
                                                   "collectUndistributedBoostedRewards")
_COMPOUND_REWARDS = _Endpoint("compoundRewards", 50000000, "compoundRewards", transfers=True)
_ALLOW_EXTERNAL_CLAIM = _Endpoint("allowExternalClaimBoostedRewards", 20000000,
                                  "allowExternalClaimBoostedRewards")

_REGISTER_FARM_TOKEN = _Endpoint("Register stake token", 100000000, "registerFarmToken", exactly=2,
                                 build=lambda args: [*args, 18],
                                 value=config.DEFAULT_ISSUE_TOKEN_PRICE)
_SET_LOCAL_ROLES_FARM_TOKEN = _Endpoint("Set local roles for stake token", 100000000,
                                        "setLocalRolesFarmToken")

_SET_REWARDS_PER_BLOCK = _Endpoint("Set rewards per block in stake contract", 50000000,
                                   "setPerBlockRewardAmount")
_SET_REWARDS_PER_SECOND = _Endpoint("Set rewards per second in stake contract", 50000000,
                                    "setPerSecondRewardAmount")
# The one deployer-facing endpoint on either contract that carries a token transfer: the rewards
# being topped up are sent with the call.
_TOPUP_REWARDS = _Endpoint("Topup rewards in stake contract", 50000000, "topUpRewards",
                           transfers=True)
_SET_BOOSTED_YIELDS_FACTORS = _Endpoint("Set boosted yield factors", 70000000,
                                        "setBoostedYieldsFactors", exactly=5)
_SET_BOOSTED_YIELDS_REWARDS_PERCENTAGE = _Endpoint("Set boosted yield rewards percentage", 70000000,
                                                   "setBoostedYieldsRewardsPercentage")
_SET_MAX_APR = _Endpoint("Set max APR", 70000000, "setMaxApr")
# A tenth of the gas its three neighbours spend. Preserved as it is: 7M is enough for the call, so
# raising it to their 70M would change what a failed call costs and nothing else.
_SET_UNBOND_EPOCHS = _Endpoint("Set unbond epochs", 7000000, "setMinUnbondEpochs")

# Sent as the bech32 text it arrived as, where the farm's copy of this setter converts it to an
# address first — and where the three whitelisting endpoints just below convert theirs.
_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("Set energy factory address in stake contract", 50000000,
                                        "setEnergyFactoryAddress")
_WHITELIST_CONTRACT = _Endpoint("Whitelist contract in staking", 50000000,
                                "addSCAddressToWhitelist", build=_as_addresses)
# The same purpose against the endpoint the first version of the contract had.
_WHITELIST_CONTRACT_V1 = _Endpoint("Whitelist contract in staking", 50000000,
                                   "addAddressToWhitelist", build=_as_addresses)
_SET_BURN_ROLE_FOR_ADDRESS = _Endpoint("Set burn role for address", 50000000,
                                       "setBurnRoleForAddress", build=_as_addresses)
_ADD_ADMIN = _Endpoint("Add admin", 50000000, "addAdmin", build=_as_addresses)
_UPDATE_OWNER_OR_ADMIN = _Endpoint("Update owner or admin", 70000000, "updateOwnerOrAdmin")

_RESUME = _Endpoint("Resume stake contract", 30000000, "resume")
_PAUSE = _Endpoint("Pause stake contract", 30000000, "pause")
_START_PRODUCE_REWARDS = _Endpoint("Start producing rewards in stake contract", 10000000,
                                   "startProduceRewards")
_END_PRODUCE_REWARDS = _Endpoint("Stop producing rewards in stake contract", 10000000,
                                 "endProduceRewards")


class StakingContract(BaseFarmContract, BaseBoostedContract, BaseSCWhitelistContract, BasePermissionsHubContract):
    _CONFIG_FIELDS = (
        _ConfigField("farming_token"),
        _ConfigField("farm_token"),
        _ConfigField("address"),
        _ConfigField("max_apr"),
        _ConfigField("rewards_per_block"),
        _ConfigField("unbond_epochs"),
        _ConfigField("version", enum=StakingContractVersion),
    )
    _CONTRACT_TOKENS = ("farm_token",)

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

    @classmethod
    def load_contract_by_address(cls, address: str, version=StakingContractVersion.V3Boosted):
        data_fetcher = StakingContractDataFetcher(Address(address), config.DEFAULT_PROXY)
        farming_token = hex_to_string(data_fetcher.get_data("getFarmingTokenId"))
        farm_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
        max_apr = data_fetcher.get_data("getAnnualPercentageRewards")
        unbond_epochs = data_fetcher.get_data("getMinUnbondEpochs")
        rewards_per_block = data_fetcher.get_data("getPerBlockRewardAmount")

        return StakingContract(
            farming_token,
            max_apr,
            rewards_per_block,
            unbond_epochs,
            version,
            farm_token,
            address
        )

    def stake_farm(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent,
                   initial: bool = False) -> str:
        logger.debug(f"Account: {user.address}")

        # Unlike the farm's, this one decides on the flag rather than on the event: an ordinary
        # stake sends the stake token whatever its amount, including zero.
        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if not initial:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        return self._call_endpoint(_STAKE_FARM, user, network_provider.proxy, [tokens])

    def stake_farm_on_behalf(self, network_provider: NetworkProviders, user: Account, event: EnterFarmEvent) -> str:
        """
        Stakes a farm on behalf of another user.
        Expected as args:
            type[List[ESDTToken]]: tokens to use
            type[str]: on behalf of address
        """
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.farming_tk, event.farming_tk_nonce, event.farming_tk_amount)]
        if event.farm_tk and event.farm_tk_amount > 0:
            tokens.append(ESDTToken(event.farm_tk, event.farm_tk_nonce, event.farm_tk_amount))

        return self._call_endpoint(_STAKE_FARM_ON_BEHALF, user, network_provider.proxy,
                                   [tokens, Address(event.on_behalf)])

    def unstake_farm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.farm_token, event.nonce, event.amount)]
        args = [tokens]
        # Only the boosted version takes an exit amount; the two before it read the transfer alone.
        if self.version == StakingContractVersion.V3Boosted:
            args.append(event.exit_amount)

        return self._call_endpoint(_UNSTAKE_FARM, user, network_provider.proxy, args)

    def unbond_farm(self, network_provider: NetworkProviders, user: Account, event: ExitFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(event.farm_token, event.nonce, event.amount)]
        return self._call_endpoint(_UNBOND_FARM, user, network_provider.proxy, [tokens])

    def claim_rewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farm_token, event.nonce, event.amount)]
        return self._call_endpoint(_CLAIM_REWARDS, user, network_provider.proxy, [tokens])

    def claim_boosted_rewards(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address} claiming for {event.user}")

        # An event naming no user claims for the caller, which is what an empty argument list means.
        sc_args = [Address(event.user)] if event.user else []
        return self._call_endpoint(_CLAIM_BOOSTED_REWARDS, user, network_provider.proxy, sc_args)

    def claim_rewards_on_behalf(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farm_token, event.nonce, event.amount)]
        return self._call_endpoint(_CLAIM_REWARDS_ON_BEHALF, user, network_provider.proxy, [tokens])

    def collect_undistributed_boosted_rewards(self, proxy: ProxyNetworkProvider, user: Account) -> str:
        logger.debug(f"Account: {user.address}")

        return self._call_endpoint(_COLLECT_UNDISTRIBUTED_BOOSTED_REWARDS, user, proxy, [])

    def compound_rewards(self, network_provider: NetworkProviders, user: Account, event: CompoundRewardsFarmEvent) -> str:
        logger.debug(f"Account: {user.address}")

        tokens = [ESDTToken(self.farm_token, event.nonce, event.amount)]
        return self._call_endpoint(_COMPOUND_REWARDS, user, network_provider.proxy, [tokens])

    def allow_external_claim(self, network_provider: NetworkProviders, user: Account) -> str:
        logger.debug(f"Account: {user.address}")

        return self._call_endpoint(_ALLOW_EXTERNAL_CLAIM, user, network_provider.proxy, [])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """Expecting as args:
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
        if self.version == StakingContractVersion.V2:
            arguments.extend([0, 0])
        if self.version == StakingContractVersion.V2 or self.version == StakingContractVersion.V3Boosted:
            arguments.extend(args)

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = [],
                         no_init: bool = False):
        """Expecting as args:
        type[str]: owner address - only from v2
        type[str]: admin address - only from v2
        self.version has to be initialized to correctly attempt the deploy for that specific type of farm.
        """
        function_purpose = f"Upgrade staking contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=False, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
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
        return self._call_endpoint(_REGISTER_FARM_TOKEN, deployer, proxy, args)

    def set_local_roles_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_LOCAL_ROLES_FARM_TOKEN, deployer, proxy, [])

    def set_rewards_per_block(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        return self._call_endpoint(_SET_REWARDS_PER_BLOCK, deployer, proxy, [rewards_amount])

    def set_rewards_per_second(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        return self._call_endpoint(_SET_REWARDS_PER_SECOND, deployer, proxy, [rewards_amount])

    def topup_rewards(self, deployer: Account, proxy: ProxyNetworkProvider, rewards_amount: int):
        tokens = [ESDTToken(self.farmed_token, 0, rewards_amount)]
        return self._call_endpoint(_TOPUP_REWARDS, deployer, proxy, [tokens])

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_address: str):
        # The one wrapper here that validates a value rather than an argument count, so the check
        # stays in the body: it hands `log_unexpected_args` the bare string rather than a list, and
        # that string is what appears in the trace. The purpose is announced first either way.
        if energy_address == "":
            logger.info(_SET_ENERGY_FACTORY_ADDRESS.purpose)
            log_unexpected_args(_SET_ENERGY_FACTORY_ADDRESS.purpose, energy_address)
            return ""

        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy, [energy_address])

    def set_boosted_yields_factors(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Only V3Boosted.
        Expecting as args:
        type[int]: max_rewards_factor
        type[int]: user_rewards_energy_const
        type[int]: user_rewards_farm_const
        type[int]: min_energy_amount
        type[int]: min_farm_amount
        """
        return self._call_endpoint(_SET_BOOSTED_YIELDS_FACTORS, deployer, proxy, args)

    def set_boosted_yields_rewards_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, percentage: int):
        """Only V3Boosted.
        """
        return self._call_endpoint(_SET_BOOSTED_YIELDS_REWARDS_PERCENTAGE, deployer, proxy,
                                   [percentage])

    def set_max_apr(self, deployer: Account, proxy: ProxyNetworkProvider, percentage: int):
        return self._call_endpoint(_SET_MAX_APR, deployer, proxy, [percentage])

    def set_unbond_epochs(self, deployer: Account, proxy: ProxyNetworkProvider, epochs: int):
        return self._call_endpoint(_SET_UNBOND_EPOCHS, deployer, proxy, [epochs])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_RESUME, deployer, proxy, [])

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_PAUSE, deployer, proxy, [])

    def start_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_START_PRODUCE_REWARDS, deployer, proxy, [])

    def end_produce_rewards(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_END_PRODUCE_REWARDS, deployer, proxy, [])

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        endpoint = (_WHITELIST_CONTRACT_V1 if self.version == StakingContractVersion.V1
                    else _WHITELIST_CONTRACT)
        return self._call_endpoint(endpoint, deployer, proxy, [contract_to_whitelist])

    def set_burn_role_for_address(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_SET_BURN_ROLE_FOR_ADDRESS, deployer, proxy,
                                   [contract_to_whitelist])

    def add_admin(self, deployer: Account, proxy: ProxyNetworkProvider, address_to_whitelist: str):
        return self._call_endpoint(_ADD_ADMIN, deployer, proxy, [address_to_whitelist])

    def update_owner_or_admin(self, deployer: Account, proxy: ProxyNetworkProvider, old_address: str):
        return self._call_endpoint(_UPDATE_OWNER_OR_ADMIN, deployer, proxy, [old_address])

    def get_reward_capacity(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, StakingContractDataFetcher, 'getRewardCapacity')

    def get_accumulated_rewards(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, StakingContractDataFetcher, 'getAccumulatedRewards')

    def get_max_apr(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, StakingContractDataFetcher, 'getAnnualPercentageRewards')

    def get_min_unbond_epochs(self, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, StakingContractDataFetcher, 'getMinUnbondEpochs')

    def get_permissions(self, address: str, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, StakingContractDataFetcher, 'getPermissions',
                                [AddressValue.new_from_address(Address(address))], empty=-1)
    
    def get_decoded_farm_token_attributes_from_proxy(self, proxy: ProxyNetworkProvider, 
                                                              holder_address: str, token_nonce: int) -> Dict[str, Any]:
        """ Get decoded attributes of the farm token from the proxy without underlying farm and stake tokens.
        Proxy usage requires to know the holder address."""
        farm_token_on_network = proxy.get_token_of_account(Address(holder_address), Token(self.farm_token, token_nonce))

        try:
            farm_token_decoded_attributes = decode_merged_attributes(farm_token_on_network.attributes.hex(), STAKE_V2_TOKEN_ATTRIBUTES)
        except ValueError as e:
            try:
                # handle for old stake token attributes
                farm_token_decoded_attributes = decode_merged_attributes(farm_token_on_network.attributes.hex(), STAKE_V1_TOKEN_ATTRIBUTES)
            except ValueError as e:
                # unstake token
                farm_token_decoded_attributes = decode_merged_attributes(farm_token_on_network.attributes.hex(), STAKE_UNBOND_TOKEN_ATTRIBUTES)

        logger.debug(f'Farm Tokens: {farm_token_decoded_attributes}')

        return farm_token_decoded_attributes
    
    def get_all_stats(self, proxy: ProxyNetworkProvider, week: int = None) -> Dict[str, Any]:
        all_stats = {}
        all_stats = {
            'reward_capacity': self.get_reward_capacity(proxy),
            'accumulated_rewards': self.get_accumulated_rewards(proxy)
        }
        all_stats.update(self.get_all_farm_global_stats(proxy))
        all_stats.update(self.get_all_boosted_global_stats(proxy, week))
        return all_stats

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        _ = self.start_produce_rewards(deployer, proxy)
        _ = self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed staking contract: {self.address}")
        log_substep(f"Staking token: {self.farming_token}")
        log_substep(f"Stake token: {self.farm_token}")
