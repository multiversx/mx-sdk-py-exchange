"""
Reference (off-chain) implementation of the xExchange safe-price oracle.

A faithful Python port of the on-chain logic, used to compute the *exact
expected value* a safe-price view should return, so tests can assert equality
instead of mere inequalities (gap G2 in SAFE_PRICE_TEST_PLAN.md).

Ported from (mx-exchange-sc, the version deployed in the pair contracts loaded
into the chain simulator):
    dex/pair/src/safe_price.rs       — observation recording state machine
    dex/pair/src/safe_price_view.rs  — TWAP computation, binary search, interpolation

KEY MECHANISM: the oracle accumulates TIME-WEIGHTED RESERVES (reserve * delta_rounds),
not time-weighted price. The safe price over [start, end] is
    weighted_second_reserve / weighted_first_reserve
i.e. a time-weighted reserve ratio. For constant reserves this equals spot.

This (older/mainnet) version is simple: there is no round_save_interval and no
intermediate observation — EVERY state-changing op at a new round stores an
observation directly; a second op in the same round is skipped. Observations
carry no timestamp; the timestamp-offset view just divides by SECONDS_PER_ROUND.

The on-chain buffer starts EMPTY in the chainsim harness (conftest strips
price_observations.* / safe_price_current_index), so this recorder also starts
empty and replays exactly the ops a test performs, in round order:

    rec = SafePriceRecorder()
    rec.update_safe_price(first_reserve, second_reserve, lp_supply, round)
    ...
    view = SafePriceView(rec)
    out = view.get_safe_price_by_round_offset(
        round_offset, input_amount, input_is_first,
        cur_first, cur_second, cur_lp, current_round,
    )
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_OBSERVATIONS = 65_536
DEFAULT_SAFE_PRICE_ROUNDS_OFFSET = 10 * 60  # 600
SECONDS_PER_ROUND = 6


def weighted_average(
    first_value: int, first_weight: int, second_value: int, second_weight: int
) -> int:
    """(a*wa + b*wb) // (wa + wb), integer floor."""
    weight_sum = first_weight + second_weight
    weighted_sum = first_value * first_weight + second_value * second_weight
    return weighted_sum // weight_sum


@dataclass
class PriceObservation:
    first_token_reserve_accumulated: int = 0
    second_token_reserve_accumulated: int = 0
    weight_accumulated: int = 0
    recording_round: int = 0
    lp_supply_accumulated: int = 0

    def clone(self) -> PriceObservation:
        return PriceObservation(
            self.first_token_reserve_accumulated,
            self.second_token_reserve_accumulated,
            self.weight_accumulated,
            self.recording_round,
            self.lp_supply_accumulated,
        )


class SafePriceError(Exception):
    """Mirrors the contract's require!/sc_panic! failures."""


# ---------------------------------------------------------------------------
# Recorder: replays safe_price.rs :: update_safe_price
# ---------------------------------------------------------------------------


class SafePriceRecorder:
    def __init__(self, max_observations: int = MAX_OBSERVATIONS):
        self.max_observations = max_observations
        # VecMapper is 1-indexed; index 0 is an unused placeholder.
        self._observations: list = [None]
        self.current_index = 0  # safe_price_current_index

    # -- VecMapper helpers (1-indexed) --
    def _len(self) -> int:
        return len(self._observations) - 1

    def _get(self, index: int) -> PriceObservation:
        return self._observations[index]

    def _set(self, index: int, obs: PriceObservation) -> None:
        self._observations[index] = obs

    def _push(self, obs: PriceObservation) -> None:
        self._observations.append(obs)

    def _is_empty(self) -> bool:
        return self._len() == 0

    def _compute_new_observation(
        self,
        new_round: int,
        first_reserve: int,
        second_reserve: int,
        lp_supply: int,
        base: PriceObservation,
    ) -> PriceObservation:
        new_weight = 1 if base.recording_round == 0 else new_round - base.recording_round
        obs = base.clone()
        obs.first_token_reserve_accumulated += new_weight * first_reserve
        obs.second_token_reserve_accumulated += new_weight * second_reserve
        obs.lp_supply_accumulated += new_weight * lp_supply
        obs.weight_accumulated += new_weight
        obs.recording_round = new_round
        return obs

    def update_safe_price(
        self,
        first_reserve: int,
        second_reserve: int,
        lp_supply: int,
        current_round: int,
    ) -> None:
        """Replay one state-changing op (swap / add / remove liquidity)."""
        if first_reserve == 0 or second_reserve == 0 or lp_supply == 0:
            return

        if self.current_index > self.max_observations:
            raise SafePriceError("ERROR_SAFE_PRICE_CURRENT_INDEX")

        last = PriceObservation()
        new_index = 1
        if not self._is_empty():
            last = self._get(self.current_index)
            new_index = (self.current_index % self.max_observations) + 1

        # Only the first op in a given round is recorded.
        if last.recording_round == current_round:
            return

        new_obs = self._compute_new_observation(
            current_round, first_reserve, second_reserve, lp_supply, last
        )

        if self._len() == self.max_observations:
            self._set(new_index, new_obs)
        else:
            self._push(new_obs)
        self.current_index = new_index


# ---------------------------------------------------------------------------
# View: replays safe_price_view.rs
# ---------------------------------------------------------------------------


@dataclass
class WeightedAmounts:
    weighted_first_token_reserve: int
    weighted_second_token_reserve: int
    weighted_lp_supply: int


class SafePriceView:
    def __init__(self, recorder: SafePriceRecorder):
        self.r = recorder

    def _oldest(self) -> PriceObservation:
        if self.r._is_empty():
            raise SafePriceError("ERROR_SAFE_PRICE_OBSERVATION_DOES_NOT_EXIST")
        oldest_index = 1
        if self.r._len() == self.r.max_observations:
            oldest_index = (self.r.current_index % self.r.max_observations) + 1
        return self.r._get(oldest_index)

    def _binary_search(self, search_round: int) -> tuple[PriceObservation, int]:
        idx = self.r.current_index
        search_index = 1
        first_obs = self.r._get(1)
        if first_obs.recording_round <= search_round:
            left, right = 1, idx - 1
        else:
            left, right = idx + 1, self.r._len()
        while left <= right:
            search_index = (left + right) // 2
            obs = self.r._get(search_index)
            if obs.recording_round == search_round:
                return obs, search_index
            if obs.recording_round < search_round:
                left = search_index + 1
            else:
                right = search_index - 1
        return PriceObservation(), search_index

    def _linear_interpolation(self, search_round: int, search_index: int) -> PriceObservation:
        max_obs = self.r.max_observations
        last_found = self.r._get(search_index)
        if last_found.recording_round < search_round:
            left = last_found
            right = self.r._get((search_index % max_obs) + 1)
        else:
            left_index = max_obs if search_index == 1 else search_index - 1
            left = self.r._get(left_index)
            right = last_found

        left_weight = right.recording_round - search_round
        right_weight = search_round - left.recording_round

        return PriceObservation(
            first_token_reserve_accumulated=weighted_average(
                left.first_token_reserve_accumulated,
                left_weight,
                right.first_token_reserve_accumulated,
                right_weight,
            ),
            second_token_reserve_accumulated=weighted_average(
                left.second_token_reserve_accumulated,
                left_weight,
                right.second_token_reserve_accumulated,
                right_weight,
            ),
            lp_supply_accumulated=weighted_average(
                left.lp_supply_accumulated, left_weight, right.lp_supply_accumulated, right_weight
            ),
            weight_accumulated=left.weight_accumulated + search_round - left.recording_round,
            recording_round=search_round,
        )

    def _get_price_observation(
        self, search_round: int, cur_first: int, cur_second: int, cur_lp: int, current_round: int
    ) -> PriceObservation:
        if self.r._is_empty():
            raise SafePriceError("ERROR_SAFE_PRICE_OBSERVATION_DOES_NOT_EXIST")
        last = self.r._get(self.r.current_index)
        if last.recording_round == search_round:
            return last
        if last.recording_round < search_round:
            if search_round > current_round:
                raise SafePriceError("ERROR_SAFE_PRICE_OBSERVATION_DOES_NOT_EXIST")
            return self.r._compute_new_observation(
                search_round, cur_first, cur_second, cur_lp, last
            )
        obs, last_search_index = self._binary_search(search_round)
        if obs.recording_round > 0:
            return obs
        return self._linear_interpolation(search_round, last_search_index)

    def compute_weighted_amounts(
        self, first_obs: PriceObservation, last_obs: PriceObservation
    ) -> WeightedAmounts:
        weight_diff = last_obs.weight_accumulated - first_obs.weight_accumulated
        if weight_diff <= 0:
            raise SafePriceError("ERROR_SAFE_PRICE_SAME_ROUNDS")
        first_diff = (
            last_obs.first_token_reserve_accumulated - first_obs.first_token_reserve_accumulated
        )
        second_diff = (
            last_obs.second_token_reserve_accumulated - first_obs.second_token_reserve_accumulated
        )
        wlp = 0
        if first_obs.lp_supply_accumulated > 0:
            wlp = (last_obs.lp_supply_accumulated - first_obs.lp_supply_accumulated) // weight_diff
        return WeightedAmounts(first_diff // weight_diff, second_diff // weight_diff, wlp)

    # -- token safe price --
    def get_safe_price(
        self,
        start_round: int,
        end_round: int,
        input_amount: int,
        input_is_first: bool,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> int:
        if end_round <= start_round:
            raise SafePriceError("ERROR_PARAMETERS")
        if self._oldest().recording_round > start_round:
            raise SafePriceError("ERROR_SAFE_PRICE_OBSERVATION_DOES_NOT_EXIST")
        first_obs = self._get_price_observation(
            start_round, cur_first, cur_second, cur_lp, current_round
        )
        last_obs = self._get_price_observation(
            end_round, cur_first, cur_second, cur_lp, current_round
        )
        w = self.compute_weighted_amounts(first_obs, last_obs)
        if input_is_first:
            return input_amount * w.weighted_second_token_reserve // w.weighted_first_token_reserve
        return input_amount * w.weighted_first_token_reserve // w.weighted_second_token_reserve

    def get_safe_price_by_round_offset(
        self,
        round_offset: int,
        input_amount: int,
        input_is_first: bool,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> int:
        if not (0 < round_offset < current_round):
            raise SafePriceError("ERROR_PARAMETERS")
        return self.get_safe_price(
            current_round - round_offset,
            current_round,
            input_amount,
            input_is_first,
            cur_first,
            cur_second,
            cur_lp,
            current_round,
        )

    def get_safe_price_by_timestamp_offset(
        self,
        timestamp_offset: int,
        input_amount: int,
        input_is_first: bool,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> int:
        round_offset = timestamp_offset // SECONDS_PER_ROUND
        return self.get_safe_price_by_round_offset(
            round_offset, input_amount, input_is_first, cur_first, cur_second, cur_lp, current_round
        )

    def get_default_offset_rounds(self, current_round: int) -> int:
        oldest = self._oldest()
        default_offset_rounds = current_round - oldest.recording_round
        if default_offset_rounds > DEFAULT_SAFE_PRICE_ROUNDS_OFFSET:
            default_offset_rounds = DEFAULT_SAFE_PRICE_ROUNDS_OFFSET
        return default_offset_rounds

    def get_safe_price_by_default_offset(
        self,
        input_amount: int,
        input_is_first: bool,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> int:
        start_round = current_round - self.get_default_offset_rounds(current_round)
        return self.get_safe_price(
            start_round,
            current_round,
            input_amount,
            input_is_first,
            cur_first,
            cur_second,
            cur_lp,
            current_round,
        )

    # -- LP token safe price --
    def get_lp_tokens_safe_price(
        self,
        start_round: int,
        end_round: int,
        liquidity: int,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> tuple[int, int]:
        if end_round <= start_round:
            raise SafePriceError("ERROR_PARAMETERS")
        if start_round < self._oldest().recording_round:
            raise SafePriceError("ERROR_SAFE_PRICE_OBSERVATION_DOES_NOT_EXIST")
        first_obs = self._get_price_observation(
            start_round, cur_first, cur_second, cur_lp, current_round
        )
        last_obs = self._get_price_observation(
            end_round, cur_first, cur_second, cur_lp, current_round
        )
        w = self.compute_weighted_amounts(first_obs, last_obs)
        weighted_lp = w.weighted_lp_supply
        if weighted_lp == 0:
            if cur_lp == 0:
                return (0, 0)
            weighted_lp = cur_lp
        first_worth = liquidity * w.weighted_first_token_reserve // weighted_lp
        second_worth = liquidity * w.weighted_second_token_reserve // weighted_lp
        return (first_worth, second_worth)

    def get_lp_tokens_safe_price_by_default_offset(
        self,
        liquidity: int,
        cur_first: int,
        cur_second: int,
        cur_lp: int,
        current_round: int,
    ) -> tuple[int, int]:
        start_round = current_round - self.get_default_offset_rounds(current_round)
        return self.get_lp_tokens_safe_price(
            start_round, current_round, liquidity, cur_first, cur_second, cur_lp, current_round
        )
