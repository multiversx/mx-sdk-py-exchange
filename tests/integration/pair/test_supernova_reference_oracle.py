"""Pure regression tests for the Supernova safe-price reference model."""

from types import SimpleNamespace

from tests.integration.pair.supernova_reference_oracle import SupernovaSafePriceRecorder
from tests.integration.pair.safe_price_helpers import (
    block_timestamp_milliseconds,
    network_status_timestamp_milliseconds,
    timestamp_offset_for_round_window,
)


def test_first_observation_uses_legacy_timestamp_weight():
    recorder = SupernovaSafePriceRecorder(timestamp_save_interval=12_000)

    recorder.update_safe_price(100, 200, 300, current_round=10, current_timestamp=100_000)
    assert recorder.observation_count == 0

    recorder.update_safe_price(200, 100, 300, current_round=11, current_timestamp=106_000)

    assert recorder.observation_count == 1
    observation = recorder.observations[0]
    assert observation.weight_accumulated == 12_000
    assert observation.first_token_reserve_accumulated == 100 * 6_000 + 200 * 6_000
    assert observation.second_token_reserve_accumulated == 200 * 6_000 + 100 * 6_000
    assert observation.lp_supply_accumulated == 300 * 12_000


def test_first_observation_is_finalized_when_legacy_weight_meets_interval():
    recorder = SupernovaSafePriceRecorder(timestamp_save_interval=1_200)

    recorder.update_safe_price(100, 200, 300, current_round=10, current_timestamp=100_000)

    assert recorder.observation_count == 1
    assert recorder.current_intermediate is None
    observation = recorder.observations[0]
    assert observation.weight_accumulated == 6_000
    assert observation.recording_round == 10
    assert observation.recording_timestamp == 100_000


def test_unequal_timestamp_gaps_control_weight_and_finalization():
    recorder = SupernovaSafePriceRecorder(timestamp_save_interval=18_000)

    recorder.update_safe_price(100, 400, 500, current_round=20, current_timestamp=200_000)
    recorder.update_safe_price(200, 200, 500, current_round=21, current_timestamp=206_000)
    assert recorder.observation_count == 0

    recorder.update_safe_price(400, 100, 500, current_round=22, current_timestamp=218_000)

    assert recorder.observation_count == 1
    observation = recorder.observations[0]
    assert observation.weight_accumulated == 24_000
    assert observation.first_token_reserve_accumulated == (
        100 * 6_000 + 200 * 6_000 + 400 * 12_000
    )
    assert observation.second_token_reserve_accumulated == (
        400 * 6_000 + 200 * 6_000 + 100 * 12_000
    )
    assert observation.recording_round == 22
    assert observation.recording_timestamp == 218_000


def test_timestamp_offset_uses_deployed_view_units():
    assert timestamp_offset_for_round_window(20, 6_000, uses_milliseconds=True) == 120_000
    assert timestamp_offset_for_round_window(20, 6_000, uses_milliseconds=False) == 120


def test_timestamp_helpers_preserve_gateway_millisecond_precision():
    status = SimpleNamespace(
        raw={"erd_block_timestamp_ms": 1_784_648_138_600},
        block_timestamp=1_784_648_138,
    )
    block = SimpleNamespace(
        raw={"timestampMs": 1_784_648_289_800},
        timestamp=1_784_648_289,
    )

    assert network_status_timestamp_milliseconds(status) == 1_784_648_138_600
    assert block_timestamp_milliseconds(block) == 1_784_648_289_800


def test_timestamp_helpers_fall_back_to_seconds_for_older_gateways():
    status = SimpleNamespace(raw={}, block_timestamp=1_784_648_138)
    block = SimpleNamespace(raw={}, timestamp=1_784_648_289)

    assert network_status_timestamp_milliseconds(status) == 1_784_648_138_000
    assert block_timestamp_milliseconds(block) == 1_784_648_289_000


def test_timestamp_query_includes_current_intermediate_observation():
    recorder = SupernovaSafePriceRecorder(timestamp_save_interval=12_000)
    recorder.update_safe_price(100, 200, 300, current_round=10, current_timestamp=100_000)
    recorder.update_safe_price(200, 100, 300, current_round=11, current_timestamp=106_000)
    recorder.update_safe_price(300, 100, 300, current_round=12, current_timestamp=112_000)

    result = recorder.get_safe_price_by_timestamp_offset(
        timestamp_offset=12_000,
        input_amount=1_000,
        input_is_first=True,
        current_first_reserve=400,
        current_second_reserve=100,
        current_lp_supply=300,
        current_round=13,
        current_timestamp=118_000,
    )

    assert result == 285
