from typing import Optional

from contracts.contract_identities import PairContractVersion, RouterContractVersion, \
    FarmContractVersion, StakingContractVersion, ProxyContractVersion, MetaStakingContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from contracts.farm_contract import FarmContract
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.metastaking_contract import MetaStakingContract
from contracts.pair_contract import PairContract
from contracts.locked_asset_contract import LockedAssetContract
import config
from contracts.position_creator_contract import PositionCreatorContract
from contracts.router_contract import RouterContract
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from contracts.staking_contract import StakingContract
from contracts.unstaker_contract import UnstakerContract
from utils.contract_data_fetchers import PairContractDataFetcher, \
    FarmContractDataFetcher, SimpleLockEnergyContractDataFetcher, StakingContractDataFetcher, \
    MetaStakingContractDataFetcher, ProxyContractDataFetcher, LockedAssetContractDataFetcher
from utils.utils_chain import hex_to_string, WrapperAddress as Address


def retrieve_pair_by_address(address: str) -> Optional[PairContract]:
    data_fetcher = PairContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    first_token = hex_to_string(data_fetcher.get_data("getFirstTokenId"))
    second_token = hex_to_string(data_fetcher.get_data("getSecondTokenId"))
    lp_token = hex_to_string(data_fetcher.get_data("getLpTokenIdentifier"))
    version = PairContractVersion.V1    # TODO: find a way to determine this automatically

    if not first_token or not second_token:
        return None

    contract = PairContract(first_token, second_token, version, lp_token, address)
    return contract


def retrieve_farm_by_address(address: str) -> Optional[FarmContract]:
    data_fetcher = FarmContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    farming_token = hex_to_string(data_fetcher.get_data("getFarmingTokenId"))
    farm_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
    farmed_token = hex_to_string(data_fetcher.get_data("getRewardTokenId"))
    version = FarmContractVersion.V2Boosted    # TODO: find a way to determine this automatically

    if not farming_token or not farmed_token:
        return None

    contract = FarmContract(farming_token, farm_token, farmed_token, address, version)
    return contract


def retrieve_router_by_address(address: str) -> Optional[RouterContract]:
    version = RouterContractVersion.V1  # TODO: find a way to determine this automatically

    contract = RouterContract(version, address)
    return contract


def retrieve_simple_lock_energy_by_address(address: str) -> Optional[SimpleLockEnergyContract]:
    data_fetcher = SimpleLockEnergyContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    base_token = hex_to_string(data_fetcher.get_data("getBaseAssetTokenId"))
    locked_token = hex_to_string(data_fetcher.get_data("getLockedTokenId"))

    contract = SimpleLockEnergyContract(base_token=base_token, locked_token=locked_token, address=address)
    return contract


def retrieve_locked_asset_factory_by_address(address: str) -> Optional[LockedAssetContract]:
    data_fetcher = LockedAssetContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    base_token = hex_to_string(data_fetcher.get_data("getAssetTokenId"))
    locked_token = hex_to_string(data_fetcher.get_data("getLockedAssetTokenId"))

    contract = LockedAssetContract(locked_asset=locked_token, unlocked_asset=base_token, address=address)
    return contract


def retrieve_unstaker_by_address(address: str) -> Optional[UnstakerContract]:
    contract = UnstakerContract(address)
    return contract


def retrieve_fees_collector_by_address(address: str) -> Optional[FeesCollectorContract]:
    contract = FeesCollectorContract(address)
    return contract


def retrieve_staking_by_address(address: str, version: StakingContractVersion) -> Optional[StakingContract]:
    data_fetcher = StakingContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    farming_token = hex_to_string(data_fetcher.get_data("getFarmingTokenId"))
    farm_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
    max_apr = data_fetcher.get_data("getAnnualPercentageRewards")
    unbond_epochs = data_fetcher.get_data("getMinUnbondEpochs")
    rewards_per_block = data_fetcher.get_data("getPerBlockRewardAmount")

    contract = StakingContract(farming_token, max_apr, rewards_per_block, unbond_epochs, version,
                               farm_token, address)
    return contract


def retrieve_proxy_staking_by_address(address: str,
                                      version: MetaStakingContractVersion) -> Optional[MetaStakingContract]:
    data_fetcher = MetaStakingContractDataFetcher(Address(address), config.DEFAULT_PROXY)

    staking_token = hex_to_string(data_fetcher.get_data("getStakingTokenId"))
    lp_token = hex_to_string(data_fetcher.get_data("getLpTokenId"))
    farm_token = hex_to_string(data_fetcher.get_data("getLpFarmTokenId"))
    stake_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
    lp_address = Address.from_hex(data_fetcher.get_data("getPairAddress")).bech32()
    farm_address = Address.from_hex(data_fetcher.get_data("getLpFarmAddress")).bech32()
    stake_address = Address.from_hex(data_fetcher.get_data("getStakingFarmAddress")).bech32()
    metastake_token = hex_to_string(data_fetcher.get_data("getDualYieldTokenId"))

    contract = MetaStakingContract(staking_token, lp_token, farm_token, stake_token, lp_address,
                                   farm_address, stake_address, version, metastake_token, address)
    return contract


def retrieve_proxy_by_address(address: str) -> Optional[DexProxyContract]:
    data_fetcher = ProxyContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    locked_tokens = [hex_to_string(res) for res in data_fetcher.get_data("getLockedTokenIds")]
    token = hex_to_string(data_fetcher.get_data("getAssetTokenId"))
    proxy_lp_token = data_fetcher.get_data("getWrappedLpTokenId")
    proxy_farm_token = data_fetcher.get_data("getWrappedFarmTokenId")
    version = ProxyContractVersion.V2

    contract = DexProxyContract(locked_tokens, token, version, address, proxy_lp_token, proxy_farm_token)
    return contract


def retrieve_position_creator_by_address(address: str) -> Optional[PositionCreatorContract]:
    contract = PositionCreatorContract(address)
    return contract


def retrieve_contract_by_address(address: str, contract_type: type):
    if contract_type == PairContract:
        return retrieve_pair_by_address(address)

    if contract_type == RouterContract:
        return retrieve_router_by_address(address)

    if contract_type == FarmContract:
        return retrieve_farm_by_address(address)

    if contract_type == SimpleLockEnergyContract:
        return retrieve_simple_lock_energy_by_address(address)

    if contract_type == UnstakerContract:
        return retrieve_unstaker_by_address(address)

    if contract_type == FeesCollectorContract:
        return retrieve_fees_collector_by_address(address)

    if contract_type == DexProxyContract:
        return retrieve_proxy_by_address(address)
