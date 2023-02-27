from typing import Optional

from contracts.contract_identities import PairContractVersion, RouterContractVersion, \
    FarmContractVersion, StakingContractVersion, ProxyContractVersion
from contracts.dex_proxy_contract import DexProxyContract
from contracts.farm_contract import FarmContract
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.metastaking_contract import MetaStakingContract
from contracts.pair_contract import PairContract
import config
from contracts.router_contract import RouterContract
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from contracts.staking_contract import StakingContract
from contracts.unstaker_contract import UnstakerContract
from utils.contract_data_fetchers import PairContractDataFetcher, RouterContractDataFetcher, \
    FarmContractDataFetcher, SimpleLockEnergyContractDataFetcher, StakingContractDataFetcher, \
    MetaStakingContractDataFetcher, ProxyContractDataFetcher
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


def retrieve_unstaker_by_address(address: str) -> Optional[UnstakerContract]:
    contract = UnstakerContract(address)
    return contract


def retrieve_fees_collector_by_address(address: str) -> Optional[FeesCollectorContract]:
    contract = FeesCollectorContract(address)
    return contract


def retrieve_staking_by_address(address: str) -> Optional[StakingContract]:
    data_fetcher = StakingContractDataFetcher(Address(address), config.DEFAULT_PROXY)
    farming_token = hex_to_string(data_fetcher.get_data("getFarmingTokenId"))
    farm_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
    division_constant = data_fetcher.get_data("getDivisionSafetyConstant")
    max_apr = data_fetcher.get_data("getAnnualPercentageRewards")
    unbond_epochs = data_fetcher.get_data("getMinUnbondEpochs")
    rewards_per_block = data_fetcher.get_data("getPerBlockRewardAmount")

    contract = StakingContract(farming_token, max_apr, rewards_per_block, unbond_epochs, StakingContractVersion.V1,
                               farm_token, address)
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
