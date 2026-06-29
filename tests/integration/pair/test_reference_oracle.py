"""
Pure-Python unit tests for reference_oracle.py (no chain simulator needed).

Validates the faithful port against hand-derived closed forms:
- weighted_average primitive
- constant reserves => safe price == spot ratio exactly
- time-weighting across a step change in reserves
- round vs timestamp offset equivalence (timestamp_offset // 6)
- circular-buffer wrap / oldest-eviction
- simulate-from-current-reserves beyond the last recorded observation

Run standalone:   PYTHONPATH=. python tests/integration/pair/test_reference_oracle.py
Run via pytest:   PYTHONPATH=. python -m pytest tests/integration/pair/test_reference_oracle.py -v
"""

from tests.integration.pair.reference_oracle import (
    SECONDS_PER_ROUND,
    SafePriceError,
    SafePriceRecorder,
    SafePriceView,
    weighted_average,
)

E18 = 10**18


def test_weighted_average():
    assert weighted_average(100, 1, 200, 1) == 150
    assert weighted_average(100, 4, 200, 5) == (100 * 4 + 200 * 5) // 9
    assert weighted_average(10, 0, 999, 7) == 999  # zero weight on left
    print("OK weighted_average")


def test_constant_reserves_equals_spot():
    """Constant reserves over the whole window => weighted ratio == spot ratio, exactly."""
    F, S, L = 2000 * E18, 1000 * E18, 1414 * E18
    rec = SafePriceRecorder()
    for r in range(1, 11):  # ops at rounds 1..10
        rec.update_safe_price(F, S, L, r)

    view = SafePriceView(rec)
    out = view.get_safe_price(
        start_round=1,
        end_round=10,
        input_amount=E18,
        input_is_first=True,
        cur_first=F,
        cur_second=S,
        cur_lp=L,
        current_round=10,
    )
    assert out == E18 * S // F, f"{out} != {E18 * S // F}"

    out_rev = view.get_safe_price(
        start_round=1,
        end_round=10,
        input_amount=E18,
        input_is_first=False,
        cur_first=F,
        cur_second=S,
        cur_lp=L,
        current_round=10,
    )
    assert out_rev == E18 * F // S
    print("OK constant_reserves_equals_spot")


def test_time_weighting_step_change():
    """(F1,S1) over rounds 1..5, then (F2,S2) over 6..10.

    Over [1,10] the accumulator diff covers 4 intervals at level1 and 5 at level2,
    so weighted_reserve = (4*level1 + 5*level2) // 9.
    """
    F1, S1, L = 2000 * E18, 1000 * E18, 1414 * E18
    F2, S2 = 1000 * E18, 1000 * E18
    rec = SafePriceRecorder()
    for r in range(1, 6):
        rec.update_safe_price(F1, S1, L, r)
    for r in range(6, 11):
        rec.update_safe_price(F2, S2, L, r)

    view = SafePriceView(rec)
    out = view.get_safe_price(
        start_round=1,
        end_round=10,
        input_amount=E18,
        input_is_first=True,
        cur_first=F2,
        cur_second=S2,
        cur_lp=L,
        current_round=10,
    )
    w_first = (4 * F1 + 5 * F2) // 9
    w_second = (4 * S1 + 5 * S2) // 9
    assert out == E18 * w_second // w_first, f"{out} != {E18 * w_second // w_first}"

    old_spot = E18 * S1 // F1
    new_spot = E18 * S2 // F2
    lo, hi = sorted((old_spot, new_spot))
    assert lo < out < hi, f"TWAP {out} not between {lo} and {hi}"
    print("OK time_weighting_step_change")


def test_round_vs_timestamp_offset_equivalence():
    """G1: timestamp offset divides by SECONDS_PER_ROUND, then matches round offset."""
    F, S, L = 1500 * E18, 3000 * E18, 2000 * E18
    rec = SafePriceRecorder()
    for r in range(1, 21):
        rec.update_safe_price(F, S, L, r)

    view = SafePriceView(rec)
    round_offset = 15
    by_round = view.get_safe_price_by_round_offset(
        round_offset, E18, True, F, S, L, current_round=20
    )
    by_ts = view.get_safe_price_by_timestamp_offset(
        round_offset * SECONDS_PER_ROUND, E18, True, F, S, L, current_round=20
    )
    assert by_round == by_ts, f"{by_round} != {by_ts}"
    # constant reserves => equals spot
    assert by_round == E18 * S // F
    print("OK round_vs_timestamp_offset_equivalence")


def test_buffer_wrap_and_oldest_eviction():
    """With max_observations=4 and 6 saved observations, oldest two evict."""
    F, S, L = 3000 * E18, 1500 * E18, 2000 * E18
    rec = SafePriceRecorder(max_observations=4)
    for r in range(1, 7):  # rounds 1..6 into a 4-slot ring
        rec.update_safe_price(F, S, L, r)

    view = SafePriceView(rec)
    assert view._oldest().recording_round == 3, view._oldest().recording_round

    out = view.get_safe_price(
        start_round=3,
        end_round=6,
        input_amount=E18,
        input_is_first=True,
        cur_first=F,
        cur_second=S,
        cur_lp=L,
        current_round=6,
    )
    assert out == E18 * S // F, out

    try:
        view.get_safe_price(2, 6, E18, True, F, S, L, 6)
        raise AssertionError("expected SafePriceError for evicted start round")
    except SafePriceError:
        pass
    print("OK buffer_wrap_and_oldest_eviction")


def test_same_round_ops_skipped():
    """A second op in the same round does not create a new observation."""
    F, S, L = 2000 * E18, 1000 * E18, 1414 * E18
    rec = SafePriceRecorder()
    rec.update_safe_price(F, S, L, 1)
    rec.update_safe_price(F, S, L, 1)  # same round, skipped
    rec.update_safe_price(F, S, L, 2)
    assert rec.current_index == 2, rec.current_index  # only 2 observations
    print("OK same_round_ops_skipped")


def test_simulate_observation_beyond_last_recorded():
    """end_round > last recorded round => view simulates from current reserves."""
    F, S, L = 2000 * E18, 1000 * E18, 1414 * E18
    rec = SafePriceRecorder()
    for r in range(1, 6):  # last recorded observation at round 5
        rec.update_safe_price(F, S, L, r)

    view = SafePriceView(rec)
    out = view.get_safe_price(
        start_round=1,
        end_round=8,
        input_amount=E18,
        input_is_first=True,
        cur_first=F,
        cur_second=S,
        cur_lp=L,
        current_round=8,
    )
    assert out == E18 * S // F, out
    print("OK simulate_observation_beyond_last_recorded")


def test_lp_safe_price_constant_reserves():
    """LP valuation: liquidity worth = liquidity * weighted_reserve / weighted_lp."""
    F, S, L = 2000 * E18, 1000 * E18, 1414 * E18
    rec = SafePriceRecorder()
    for r in range(1, 11):
        rec.update_safe_price(F, S, L, r)

    view = SafePriceView(rec)
    liquidity = L // 10  # 10% of supply
    first_worth, second_worth = view.get_lp_tokens_safe_price(
        start_round=1,
        end_round=10,
        liquidity=liquidity,
        cur_first=F,
        cur_second=S,
        cur_lp=L,
        current_round=10,
    )
    assert first_worth == liquidity * F // L, first_worth
    assert second_worth == liquidity * S // L, second_worth
    print("OK lp_safe_price_constant_reserves")


if __name__ == "__main__":
    test_weighted_average()
    test_constant_reserves_equals_spot()
    test_time_weighting_step_change()
    test_round_vs_timestamp_offset_equivalence()
    test_buffer_wrap_and_oldest_eviction()
    test_same_round_ops_skipped()
    test_simulate_observation_beyond_last_recorded()
    test_lp_safe_price_constant_reserves()
    print("\nAll reference_oracle unit tests passed.")
