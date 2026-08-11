from abc import abstractmethod, ABC
from collections.abc import Callable, Mapping
from enum import Enum

from typing import Any
from utils.contract_data_fetchers import DataFetcher
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils.utils_tx import endpoint_call
from utils.logger import get_logger
from multiversx_sdk import ProxyNetworkProvider


logger = get_logger(__name__)


class DEXContractIdentityInterface(ABC):

    address: str = NotImplemented


class DEXContractInterface(ABC):

    address: str = NotImplemented

    def _query_view(self,
                    proxy: ProxyNetworkProvider,
                    fetcher: type[DataFetcher],
                    view_name: str,
                    args: list | None = None,
                    *,
                    returns: Any = int,
                    fallback: Callable[[], Any] | None = None) -> Any:
        """Run one read-only contract view and return its result as `returns`.

        `returns` is the type the caller wants back — `int`, `str` for a hex-encoded string, `bool`,
        or a decoding structure from `utils.decoding_structures` for a struct. A view that answers
        with nothing yields that type's zero value (`0`, `""`, `False`, `{}`) rather than raising,
        which is the guard every hand-written View Getter carried.

        `fallback` covers the other case. A `DataFetcher` returns `-1` from an integer view whose
        query *failed*, as opposed to `0` for a view that is genuinely empty, so a negative result
        is the only signal that the chain did not answer. Getters that can answer such a query some
        other way — from raw storage, from a related view — pass that second source here. Getters
        without one leave `fallback` unset and pass the `-1` on to their caller, unchanged.
        """
        data_fetcher = fetcher(Address(self.address), proxy.url)
        raw_result = data_fetcher.get_data(view_name, args if args is not None else [])

        if not raw_result:
            return {} if isinstance(returns, Mapping) else returns()

        if fallback is not None and isinstance(raw_result, int) and raw_result < 0:
            return fallback()

        if isinstance(returns, Mapping):
            return decode_merged_attributes(raw_result, returns)
        if returns is str:
            return hex_to_string(raw_result)
        return returns(raw_result)

    @abstractmethod
    def get_config_dict(self) -> dict[str, Any]:
        pass

    @classmethod
    @abstractmethod
    def load_config_dict(cls, config_dict: dict):
        pass

    @classmethod
    @abstractmethod
    def load_contract_by_address(cls, address: str):
        pass

    @abstractmethod
    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list) -> tuple[str, str]:
        pass

    @abstractmethod
    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    @abstractmethod
    def print_contract_info(self):
        pass

    @abstractmethod
    def get_contract_tokens(self) -> list[str]:
        pass

    def change_owner_address(self, deployer: Account, proxy: ProxyNetworkProvider, new_address: str) -> str:
        function_purpose = "Change owner address of the contract"
        logger.info(function_purpose)
        
        gas_limit = 20000000
        sc_args = [new_address]
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "ChangeOwnerAddress", sc_args)
    
    def claim_developer_rewards(self, deployer: Account, proxy: ProxyNetworkProvider) -> str:
        function_purpose = "Claim developer rewards"
        logger.info(function_purpose)
        
        gas_limit = 20000000
        sc_args = []
        logger.debug(f"Arguments: {sc_args}")
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "ClaimDeveloperRewards", sc_args)


class PriceDiscoveryContractIdentity(DEXContractIdentityInterface):
    launched_token_id: str
    accepted_token: str
    redeem_token: str
    first_redeem_token_nonce: int
    second_redeem_token_nonce: int
    address: str
    locking_sc_address: str
    min_launched_token_price: int
    start_block: int
    no_limit_phase_duration_blocks: int
    linear_penalty_phase_duration_blocks: int
    fixed_penalty_phase_duration_blocks: int
    unlock_epoch: int
    min_penalty_percentage: int
    max_penalty_percentage: int
    fixed_penalty_percentage: int


class ProxyContractVersion(Enum):
    V1 = 1
    V2 = 2


class FarmContractVersion(Enum):
    V12 = 1
    V14Unlocked = 2
    V14Locked = 3
    V2Boosted = 4


class RouterContractVersion(Enum):
    V1 = 1
    V2 = 2


class PairContractVersion(Enum):
    V1 = 1
    V2 = 2


class StakingContractVersion(Enum):
    V1 = 1
    V2 = 2
    V3Boosted = 3


class MetaStakingContractVersion(Enum):
    V1 = 1
    V2 = 2
    V3Boosted = 3


class FarmContractIdentity(DEXContractIdentityInterface):
    farmingToken: str
    farmToken: str
    farmedToken: str
    address: str
    version: FarmContractVersion
    last_token_nonce: int


class StakingContractIdentity(DEXContractIdentityInterface):
    address: str
    farming_token: str
    farm_token: str
    farmed_token: str
    max_apr: int
    rewards_per_block: int
    unbond_epochs: int


class MetaStakingContractIdentity(DEXContractIdentityInterface):
    address: str
    metastake_token: str
    staking_token: str
    lp_address: str
    farm_address: str
    stake_address: str
    lp_token: str
    farm_token: str
    stake_token: str


class RouterContractIdentity(DEXContractIdentityInterface):
    address: str


class PairContractIdentity(DEXContractIdentityInterface):
    address: str
    first_token: str
    second_token: str
    lp_token: str


class SimpleLockContractIdentity(DEXContractIdentityInterface):
    address: str
    locked_token: str
    lp_proxy_token: str


class ProxyContractIdentity(DEXContractIdentityInterface):
    address: str
    token: str
    locked_token: str
    proxy_lp_token: str
    proxy_farm_token: str


class LockedAssetContractIdentity(DEXContractIdentityInterface):
    address: str
    unlocked_asset: str
    locked_asset: str


