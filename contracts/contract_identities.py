from abc import abstractmethod, ABC
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from typing import Any, ClassVar
from utils.contract_data_fetchers import DataFetcher
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils.utils_tx import endpoint_call
from utils.logger import get_logger
from multiversx_sdk import ProxyNetworkProvider


logger = get_logger(__name__)

# The marker for "no value", distinct from every value a view could legitimately answer with.
_UNSET = object()

# What each return kind yields for a view that answers with nothing. `Address` and the custom
# converters are deliberately absent: an empty answer is not an address and not something a
# converter can be handed, so those getters either name an `empty` of their own or let the
# conversion raise — which is what the hand-written bodies did.
_EMPTY_RESULTS = {int: 0, str: "", bool: False}


def _empty_result(returns: Any) -> Any:
    """The value an empty view yields for this return kind, or `_UNSET` when it has none."""
    if isinstance(returns, list):
        return []
    if isinstance(returns, Mapping):
        return {}
    return _EMPTY_RESULTS.get(returns, _UNSET)


def _decode_view_result(raw_result: Any, returns: Any) -> Any:
    """Convert one raw view answer into the kind the caller asked for."""
    if isinstance(returns, list):
        element_kind, = returns
        return [_decode_view_result(entry, element_kind) for entry in raw_result]
    if isinstance(returns, Mapping):
        return decode_merged_attributes(raw_result, returns)
    if returns is str:
        return hex_to_string(raw_result)
    if returns is Address:
        return Address.from_hex(raw_result).bech32()
    return returns(raw_result)


@dataclass(frozen=True)
class _ConfigField:
    """One persisted attribute of a contract: how it is stored, and how it comes back.

    A contract declares an ordered tuple of these as `_CONFIG_FIELDS`, and that tuple is the whole
    of what `get_config_dict` and `load_config_dict` need to know. The order is the order the keys
    are written to `deployed_*.json` in, so it is part of the behaviour, not a detail.

    Every axis past `key` exists because the hand-written copies genuinely disagreed on it, and is
    a parameter rather than a smoothed-over single behaviour for exactly that reason. A field the
    copies agreed about needs only its `key`.
    """

    key: str                        # the key it is stored under, and the attribute it reads
    arg: str | None = None          # the constructor keyword it loads into, when not `key`
    enum: type[Enum] | None = None  # the enum it round-trips through, stored as its `.value`
    attr: str | None = None         # the attribute it reads, when not `key`
    optional: bool = False          # read with `.get`, yielding `None` when the key is absent

    @property
    def keyword(self) -> str:
        """The constructor keyword this field loads into.

        Five fields are stored under one name and constructed under another — `farmingToken` is
        built as `farming_token`, `accepted_token` as `accepted_token_id`, `template` as
        `template_name`. Both names are part of the surface: the stored one is in committed deploy
        state, the constructed one is in every caller that builds the contract directly.
        """
        return self.arg or self.key

    def dump(self, contract: Any) -> Any:
        """This field's value on `contract`, as it is stored."""
        value = getattr(contract, self.attr or self.key)
        return value.value if self.enum is not None else value

    def load(self, config_dict: dict) -> Any:
        """This field's value read out of a stored config, as the constructor wants it."""
        raw = config_dict.get(self.key) if self.optional else config_dict[self.key]
        return self.enum(raw) if self.enum is not None and raw is not None else raw


class DEXContractIdentityInterface(ABC):

    address: str = NotImplemented


class DEXContractInterface(ABC):

    address: str = NotImplemented

    # The persisted fields, in the order they are written to `deployed_*.json`. Left unset here so
    # that a class which declares neither this nor its own `get_config_dict` says so loudly rather
    # than serializing to an empty dict.
    _CONFIG_FIELDS: ClassVar[tuple[_ConfigField, ...] | None] = None

    # The attributes `get_contract_tokens` reports, in order. Most contracts bear no tokens, which
    # is why the default is the empty tuple rather than unset.
    _CONTRACT_TOKENS: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def _config_fields(cls) -> tuple[_ConfigField, ...]:
        if cls._CONFIG_FIELDS is None:
            raise NotImplementedError(
                f"{cls.__name__} neither declares _CONFIG_FIELDS nor implements get_config_dict "
                "and load_config_dict itself"
            )
        return cls._CONFIG_FIELDS

    def _query_view(self,
                    proxy: ProxyNetworkProvider,
                    fetcher: type[DataFetcher],
                    view_name: str,
                    args: list | None = None,
                    *,
                    returns: Any = int,
                    empty: Any = _UNSET,
                    fallback: Callable[[], Any] | None = None) -> Any:
        """Run one read-only contract view and return its result as `returns`.

        `returns` is the kind the caller wants back:

        | `returns`            | the answer becomes                                    |
        |----------------------|-------------------------------------------------------|
        | `int` / `bool`       | that type, built from the raw answer                  |
        | `str`                | text, decoded from a hex-encoded string               |
        | `Address`            | a bech32 address, decoded from a hex pubkey           |
        | a decoding structure | a `dict`, per `utils.decoding_structures`             |
        | `[<any of the above>]` | a list, each entry converted as that kind           |
        | any callable         | whatever it makes of the raw answer                   |

        A view that answers with nothing yields that kind's empty value — `0`, `""`, `False`, `{}`,
        `[]` — rather than raising, which is the guard every hand-written View Getter carried.
        `empty` overrides it, and is how the getters that disagree keep disagreeing: the permissions
        views report an empty answer as `-1`, the liquid-locking token lists report theirs as `{}`.
        `Address` and callable converters have no empty value of their own, so a getter that wants
        one names it and a getter that does not lets the conversion raise, as `get_pair_template_address`
        always has.

        `fallback` covers the other case. A `DataFetcher` returns `-1` from an integer view whose
        query *failed*, as opposed to `0` for a view that is genuinely empty, so a negative result
        is the only signal that the chain did not answer. Getters that can answer such a query some
        other way — from raw storage, from a related view — pass that second source here. Getters
        without one leave `fallback` unset and pass the `-1` on to their caller, unchanged.
        """
        data_fetcher = fetcher(Address(self.address), proxy.url)
        raw_result = data_fetcher.get_data(view_name, args if args is not None else [])

        if not raw_result:
            empty_result = _empty_result(returns) if empty is _UNSET else empty
            if empty_result is not _UNSET:
                return empty_result

        if fallback is not None and isinstance(raw_result, int) and raw_result < 0:
            return fallback()

        return _decode_view_result(raw_result, returns)

    def get_config_dict(self) -> dict[str, Any]:
        """This contract as the dict `save_deployed_contracts` writes to `deployed_*.json`.

        Driven by `_CONFIG_FIELDS`, in declaration order — the file is written verbatim, so a
        reordering here would rewrite every committed deploy state file with no change in it.
        """
        return {field.key: field.dump(self) for field in self._config_fields()}

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        """Rebuild a contract from a dict `get_config_dict` wrote.

        Each field names the constructor keyword it loads into, so a class whose stored keys and
        constructor parameters disagree — as five of them do — keeps both names exactly as they
        are. Anything the constructor defaults and `_CONFIG_FIELDS` does not name is simply not
        persisted, which is how `FarmContract.proxyContract` and `PositionCreatorContract`'s three
        collaborator addresses have always survived a save/load round trip: they do not.
        """
        return cls(**{field.keyword: field.load(config_dict) for field in cls._config_fields()})

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

    def get_contract_tokens(self) -> list[str]:
        """The tokens this contract issues, read off the attributes `_CONTRACT_TOKENS` names."""
        return [getattr(self, name) for name in self._CONTRACT_TOKENS]

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


