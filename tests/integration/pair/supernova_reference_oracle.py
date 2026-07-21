"""Supernova safe-price reference model.

This mirrors the safe-price logic from mx-exchange-sc rc/supernova-updates:

- observations accumulate first reserve, second reserve, LP supply, and weight;
- observations store recording round and timestamp;
- the first update uses the legacy 6,000 ms weight and subsequent updates use
  the actual timestamp delta;
- the pair keeps an intermediate observation and finalizes it after the
  configured timestamp interval has accumulated;
- round and timestamp views interpolate the same timestamp-weighted cumulative
  observations.

The model intentionally stays small and deterministic so chain-simulator tests
can replay the same trade tape against different pair bytecode and compare the
on-chain view output with this off-chain reference.
"""

from __future__ import annotations

from dataclasses import dataclass


MAX_OBSERVATIONS = 65_536
LEGACY_ROUND_DURATION_MS = 6_000


class SupernovaSafePriceError(Exception):
    """Raised when the on-chain view would reject the requested window."""


@dataclass
class PriceObservation:
    first_token_reserve_accumulated: int = 0
    second_token_reserve_accumulated: int = 0
    weight_accumulated: int = 0
    recording_round: int = 0
    recording_timestamp: int = 0
    lp_supply_accumulated: int = 0

    def clone(self) -> "PriceObservation":
        return PriceObservation(
            self.first_token_reserve_accumulated,
            self.second_token_reserve_accumulated,
            self.weight_accumulated,
            self.recording_round,
            self.recording_timestamp,
            self.lp_supply_accumulated,
        )


def weighted_average(first_value: int, first_weight: int, second_value: int, second_weight: int) -> int:
    weight_sum = first_weight + second_weight
    if weight_sum == 0:
        raise SupernovaSafePriceError("cannot interpolate with zero total weight")
    return (first_value * first_weight + second_value * second_weight) // weight_sum


class SupernovaSafePriceRecorder:
    def __init__(
        self,
        timestamp_save_interval: int,
        legacy_round_duration_ms: int = LEGACY_ROUND_DURATION_MS,
    ):
        if timestamp_save_interval <= 0:
            raise ValueError("timestamp_save_interval must be greater than 0")
        if legacy_round_duration_ms <= 0:
            raise ValueError("legacy_round_duration_ms must be greater than 0")
        self.timestamp_save_interval = timestamp_save_interval
        self.legacy_round_duration_ms = legacy_round_duration_ms
        self.observations: list[PriceObservation] = []
        self.current_index = 0  # 1-based, like VecMapper storage
        self.current_intermediate: PriceObservation | None = None

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    def update_safe_price(
        self,
        first_token_reserve: int,
        second_token_reserve: int,
        lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> None:
        if first_token_reserve == 0 or second_token_reserve == 0 or lp_supply == 0:
            return

        last_observation = self._last_observation()
        latest_observation = self._latest_observation()
        if (
            latest_observation.weight_accumulated > 0
            and latest_observation.recording_timestamp >= current_timestamp
        ):
            return

        new_observation = self._compute_new_observation(
            current_round,
            current_timestamp,
            first_token_reserve,
            second_token_reserve,
            lp_supply,
            latest_observation,
        )
        accumulated_weight = (
            new_observation.weight_accumulated
            - last_observation.weight_accumulated
        )
        if accumulated_weight >= self.timestamp_save_interval:
            self._save_observation_to_storage(new_observation)
        else:
            self.current_intermediate = new_observation

    def get_safe_price_by_round_offset(
        self,
        round_offset: int,
        input_amount: int,
        input_is_first: bool,
        current_first_reserve: int,
        current_second_reserve: int,
        current_lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> int:
        if round_offset <= 0 or round_offset >= current_round:
            raise SupernovaSafePriceError("bad round offset")
        return self.get_safe_price(
            current_round - round_offset,
            current_round,
            input_amount,
            input_is_first,
            current_first_reserve,
            current_second_reserve,
            current_lp_supply,
            current_round,
            current_timestamp,
        )

    def get_safe_price_by_timestamp_offset(
        self,
        timestamp_offset: int,
        input_amount: int,
        input_is_first: bool,
        current_first_reserve: int,
        current_second_reserve: int,
        current_lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> int:
        if timestamp_offset <= 0 or timestamp_offset >= current_timestamp:
            raise SupernovaSafePriceError("bad timestamp offset")
        first_observation = self._get_price_observation_by_timestamp(
            current_timestamp - timestamp_offset,
            current_first_reserve,
            current_second_reserve,
            current_lp_supply,
            current_round,
            current_timestamp,
        )
        last_observation = self._get_price_observation_by_timestamp(
            current_timestamp,
            current_first_reserve,
            current_second_reserve,
            current_lp_supply,
            current_round,
            current_timestamp,
        )
        return self._price_from_observations(
            first_observation, last_observation, input_amount, input_is_first
        )

    def get_safe_price(
        self,
        start_round: int,
        end_round: int,
        input_amount: int,
        input_is_first: bool,
        current_first_reserve: int,
        current_second_reserve: int,
        current_lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> int:
        if end_round <= start_round:
            raise SupernovaSafePriceError("end round must be after start round")

        first_observation = self._get_price_observation(
            start_round,
            current_first_reserve,
            current_second_reserve,
            current_lp_supply,
            current_round,
            current_timestamp,
        )
        last_observation = self._get_price_observation(
            end_round,
            current_first_reserve,
            current_second_reserve,
            current_lp_supply,
            current_round,
            current_timestamp,
        )

        return self._price_from_observations(
            first_observation, last_observation, input_amount, input_is_first
        )

    def _price_from_observations(
        self,
        first_observation: PriceObservation,
        last_observation: PriceObservation,
        input_amount: int,
        input_is_first: bool,
    ) -> int:
        weight_diff = last_observation.weight_accumulated - first_observation.weight_accumulated
        if weight_diff <= 0:
            raise SupernovaSafePriceError("same accumulated weights")

        first_reserve_diff = (
            last_observation.first_token_reserve_accumulated
            - first_observation.first_token_reserve_accumulated
        )
        second_reserve_diff = (
            last_observation.second_token_reserve_accumulated
            - first_observation.second_token_reserve_accumulated
        )
        weighted_first_reserve = first_reserve_diff // weight_diff
        weighted_second_reserve = second_reserve_diff // weight_diff

        if weighted_first_reserve <= 0 or weighted_second_reserve <= 0:
            raise SupernovaSafePriceError("zero weighted reserve")

        if input_is_first:
            return input_amount * weighted_second_reserve // weighted_first_reserve
        return input_amount * weighted_first_reserve // weighted_second_reserve

    def _last_observation(self) -> PriceObservation:
        if not self.observations or self.current_index == 0:
            return PriceObservation()
        return self.observations[self.current_index - 1].clone()

    @staticmethod
    def _observation_is_after(
        candidate: PriceObservation, reference: PriceObservation
    ) -> bool:
        return (
            candidate.recording_timestamp > reference.recording_timestamp
            or (
                candidate.recording_timestamp == reference.recording_timestamp
                and candidate.recording_round > reference.recording_round
            )
        )

    def _latest_observation(self) -> PriceObservation:
        last_observation = self._last_observation()
        if (
            self.current_intermediate is not None
            and self._observation_is_after(
                self.current_intermediate, last_observation
            )
        ):
            return self.current_intermediate.clone()
        return last_observation

    def _oldest_observation(self) -> PriceObservation:
        if not self.observations:
            raise SupernovaSafePriceError("no observations")
        if len(self.observations) == MAX_OBSERVATIONS:
            return self.observations[self.current_index % MAX_OBSERVATIONS].clone()
        return self.observations[0].clone()

    def _save_observation_to_storage(self, observation: PriceObservation) -> None:
        if self.current_index > MAX_OBSERVATIONS:
            raise SupernovaSafePriceError("bad current index")

        if not self.observations:
            self.observations.append(observation.clone())
            self.current_index = 1
        elif len(self.observations) == MAX_OBSERVATIONS:
            self.current_index = (self.current_index % MAX_OBSERVATIONS) + 1
            self.observations[self.current_index - 1] = observation.clone()
        else:
            self.observations.append(observation.clone())
            self.current_index = len(self.observations)

        self.current_intermediate = None

    def _accumulate_into_observation(
        self,
        observation: PriceObservation,
        current_round: int,
        current_timestamp: int,
        first_token_reserve: int,
        second_token_reserve: int,
        lp_supply: int,
    ) -> None:
        weight = self.legacy_round_duration_ms
        if observation.recording_timestamp > 0:
            weight = current_timestamp - observation.recording_timestamp
        if weight < 0:
            raise SupernovaSafePriceError("observation timestamp is in the future")

        observation.first_token_reserve_accumulated += weight * first_token_reserve
        observation.second_token_reserve_accumulated += weight * second_token_reserve
        observation.lp_supply_accumulated += weight * lp_supply
        observation.weight_accumulated += weight
        observation.recording_round = current_round
        observation.recording_timestamp = current_timestamp

    def _compute_new_observation(
        self,
        new_round: int,
        new_timestamp: int,
        new_first_reserve: int,
        new_second_reserve: int,
        new_lp_supply: int,
        current_observation: PriceObservation,
    ) -> PriceObservation:
        new_observation = current_observation.clone()
        self._accumulate_into_observation(
            new_observation,
            new_round,
            new_timestamp,
            new_first_reserve,
            new_second_reserve,
            new_lp_supply,
        )
        return new_observation

    def _get_price_observation(
        self,
        search_round: int,
        current_first_reserve: int,
        current_second_reserve: int,
        current_lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> PriceObservation:
        if not self.observations:
            raise SupernovaSafePriceError("no observations")

        oldest = self._oldest_observation()
        if oldest.recording_round > search_round:
            raise SupernovaSafePriceError("observation does not exist")

        last = self._latest_observation()
        if last.recording_round == search_round:
            return last

        if last.recording_round < search_round:
            if search_round > current_round:
                raise SupernovaSafePriceError("future observation does not exist")
            search_timestamp = self._timestamp_for_round(
                search_round, current_round, current_timestamp
            )
            return self._compute_new_observation(
                search_round,
                search_timestamp,
                current_first_reserve,
                current_second_reserve,
                current_lp_supply,
                last,
            )

        observations = self._query_observations_in_round_order()
        for observation in observations:
            if observation.recording_round == search_round:
                return observation.clone()

        left = None
        right = None
        for observation in observations:
            if observation.recording_round < search_round:
                left = observation
            elif observation.recording_round > search_round:
                right = observation
                break

        if left is None or right is None:
            raise SupernovaSafePriceError("cannot interpolate observation")
        return self._interpolate_observation_by_round(left, right, search_round)

    def _get_price_observation_by_timestamp(
        self,
        search_timestamp: int,
        current_first_reserve: int,
        current_second_reserve: int,
        current_lp_supply: int,
        current_round: int,
        current_timestamp: int,
    ) -> PriceObservation:
        if not self.observations:
            raise SupernovaSafePriceError("no observations")

        observations = self._query_observations_in_round_order()
        oldest = observations[0]
        if search_timestamp < oldest.recording_timestamp:
            raise SupernovaSafePriceError("timestamp observation does not exist")

        last = observations[-1]
        if search_timestamp == last.recording_timestamp:
            return last
        if search_timestamp > current_timestamp:
            raise SupernovaSafePriceError("future observation does not exist")
        if search_timestamp > last.recording_timestamp:
            search_round = self._round_for_timestamp(
                last,
                current_round,
                current_timestamp,
                search_timestamp,
            )
            return self._compute_new_observation(
                search_round,
                search_timestamp,
                current_first_reserve,
                current_second_reserve,
                current_lp_supply,
                last,
            )

        for observation in observations:
            if observation.recording_timestamp == search_timestamp:
                return observation.clone()

        left = None
        right = None
        for observation in observations:
            if observation.recording_timestamp < search_timestamp:
                left = observation
            elif observation.recording_timestamp > search_timestamp:
                right = observation
                break

        if left is None or right is None:
            raise SupernovaSafePriceError("cannot interpolate timestamp")
        return self._interpolate_observation_by_timestamp(
            left, right, search_timestamp
        )

    def _timestamp_for_round(
        self, search_round: int, current_round: int, current_timestamp: int
    ) -> int:
        observations = self._observations_in_round_order()
        for observation in observations:
            if observation.recording_round == search_round:
                return observation.recording_timestamp

        left = None
        right = None
        for observation in observations:
            if observation.recording_round < search_round:
                left = observation
            elif observation.recording_round > search_round:
                right = observation
                break

        if left is not None and right is not None:
            return weighted_average(
                left.recording_timestamp,
                right.recording_round - search_round,
                right.recording_timestamp,
                search_round - left.recording_round,
            )
        if left is None or search_round > current_round:
            raise SupernovaSafePriceError("cannot map round to timestamp")
        return weighted_average(
            left.recording_timestamp,
            current_round - search_round,
            current_timestamp,
            search_round - left.recording_round,
        )

    @staticmethod
    def _round_for_timestamp(
        left: PriceObservation,
        current_round: int,
        current_timestamp: int,
        search_timestamp: int,
    ) -> int:
        if current_timestamp == left.recording_timestamp:
            return left.recording_round
        return weighted_average(
            left.recording_round,
            current_timestamp - search_timestamp,
            current_round,
            search_timestamp - left.recording_timestamp,
        )

    def _observations_in_round_order(self) -> list[PriceObservation]:
        if len(self.observations) < MAX_OBSERVATIONS:
            return [obs.clone() for obs in self.observations]
        start = self.current_index % MAX_OBSERVATIONS
        return [self.observations[(start + i) % MAX_OBSERVATIONS].clone() for i in range(MAX_OBSERVATIONS)]

    def _query_observations_in_round_order(self) -> list[PriceObservation]:
        observations = self._observations_in_round_order()
        if self.current_intermediate is None:
            return observations
        if not observations or self._observation_is_after(
            self.current_intermediate, observations[-1]
        ):
            observations.append(self.current_intermediate.clone())
        return observations

    def _interpolate_observation_by_round(
        self, left: PriceObservation, right: PriceObservation, search_round: int
    ) -> PriceObservation:
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
            weight_accumulated=weighted_average(
                left.weight_accumulated,
                left_weight,
                right.weight_accumulated,
                right_weight,
            ),
            recording_round=search_round,
            recording_timestamp=weighted_average(
                left.recording_timestamp,
                left_weight,
                right.recording_timestamp,
                right_weight,
            ),
            lp_supply_accumulated=weighted_average(
                left.lp_supply_accumulated,
                left_weight,
                right.lp_supply_accumulated,
                right_weight,
            ),
        )

    def _interpolate_observation_by_timestamp(
        self,
        left: PriceObservation,
        right: PriceObservation,
        search_timestamp: int,
    ) -> PriceObservation:
        left_weight = right.recording_timestamp - search_timestamp
        right_weight = search_timestamp - left.recording_timestamp
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
            weight_accumulated=weighted_average(
                left.weight_accumulated,
                left_weight,
                right.weight_accumulated,
                right_weight,
            ),
            recording_round=weighted_average(
                left.recording_round,
                left_weight,
                right.recording_round,
                right_weight,
            ),
            recording_timestamp=search_timestamp,
            lp_supply_accumulated=weighted_average(
                left.lp_supply_accumulated,
                left_weight,
                right.lp_supply_accumulated,
                right_weight,
            ),
        )
