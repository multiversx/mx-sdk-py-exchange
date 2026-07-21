"""
Long-running safe-price (TWAP) oracle simulation.

Where test_safe_price.py / test_safe_price_gaps.py verify the oracle over a
handful of swaps, this test drives the pair through THOUSANDS of rounds of
realistic activity and visualises how the safe price behaves over a long time
frame:

  * a steady cadence of small, alternating swaps keeps a stable baseline price
    and continuously feeds the observation buffer;
  * at pre-defined intervals a large "spike" swap is injected and then reverted
    a few blocks later, producing a sharp, transient spot-price excursion;
  * at a coarser sampling interval the test records, for several TWAP windows:
      - the raw spot price (getEquivalent)            — most manipulable
      - the legacy updateAndGetSafePrice              — on-chain default-offset TWAP
      - getSafePriceBy{Round,Timestamp}Offset(window) — on-chain windowed TWAP
      - the offline reference oracle over the window  — exact off-chain replica
    using the SAME CSV column conventions as tools/safeprice_monitor.py, so
    tools/safeprice_plot.py renders the chart unchanged.

At the end a PNG chart is produced under tests/logs/ comparing all of the above,
which makes the smoothing / manipulation-resistance of the TWAP visible: spot
spikes, the windowed safe prices barely move, and shorter windows track spot
more closely than longer ones.

Chain simulator is strongly preferred: blocks (and their ~6s timestamps) are
generated on demand, so a multi-thousand-round time frame plays out in minutes
and swaps can be issued back-to-back without waiting for real block time.

Everything is overridable via environment variables (defaults in LongRunConfig):
    SAFE_PRICE_LR_ROUNDS            target rounds to span                (10000)
    SAFE_PRICE_LR_CADENCE           blocks advanced between swaps        (3)
    SAFE_PRICE_LR_SAMPLE_EVERY      record a CSV row every N swaps       (5)
    SAFE_PRICE_LR_SPIKE_INTERVAL    rounds between spike events          (500)
    SAFE_PRICE_LR_WINDOWS           comma-separated round offsets        ("50,200,600")
    SAFE_PRICE_LR_REGULAR_FRACTION  regular swap = reserve // frac       (1000)
    SAFE_PRICE_LR_SPIKE_FRACTION    spike swap   = reserve // frac       (8)
    SAFE_PRICE_LR_REFUND_EVERY      top up swapper balance every N swaps (25)
    SAFE_PRICE_LR_OUTPUT_DIR        output dir for CSV + PNG             (tests/logs)

Run (full, slow):
    PYTHONPATH=. python -m pytest tests/integration/pair/test_safe_price_long_running.py -v -s

Quick smoke run:
    SAFE_PRICE_LR_ROUNDS=300 SAFE_PRICE_LR_SPIKE_INTERVAL=80 \
        PYTHONPATH=. python -m pytest tests/integration/pair/test_safe_price_long_running.py -v -s
"""

from __future__ import annotations

import csv
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import config
from multiversx_sdk import Address, AddressComputer

from contracts.pair_contract import PairContract, SwapFixedInputEvent
from tests.helpers import TransactionAssertions
from tests.integration.pair.reference_oracle import (
    SafePriceError,
    SafePriceRecorder,
    SafePriceView,
)
from tests.integration.pair.safe_price_helpers import (
    deployed_safe_price_uses_milliseconds,
    get_transaction_execution_round,
    load_safe_price_abi,
    pick_same_shard_account,
    query_safe_price_by_offset,
    reserves,
    spot_equivalent,
    timestamp_offset_for_round_window,
)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.utils_chain import decode_merged_attributes

logger = get_logger(__name__)

pytestmark = pytest.mark.usefixtures("safe_price_view_contract")

REPO_ROOT = Path(__file__).resolve().parents[3]
ESDT_PAYMENT_SCHEMA = {"token_identifier": "string", "token_nonce": "u64", "amount": "biguint"}
LEGACY_ROUND_DURATION_MS = 6_000


# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass
class LongRunConfig:
    rounds: int = field(default_factory=lambda: _env_int("SAFE_PRICE_LR_ROUNDS", 10000))
    cadence: int = field(default_factory=lambda: _env_int("SAFE_PRICE_LR_CADENCE", 3))
    sample_every: int = field(default_factory=lambda: _env_int("SAFE_PRICE_LR_SAMPLE_EVERY", 5))
    spike_interval: int = field(
        default_factory=lambda: _env_int("SAFE_PRICE_LR_SPIKE_INTERVAL", 500)
    )
    regular_fraction: int = field(
        default_factory=lambda: _env_int("SAFE_PRICE_LR_REGULAR_FRACTION", 1000)
    )
    spike_fraction: int = field(default_factory=lambda: _env_int("SAFE_PRICE_LR_SPIKE_FRACTION", 8))
    refund_every: int = field(default_factory=lambda: _env_int("SAFE_PRICE_LR_REFUND_EVERY", 25))

    @property
    def windows(self) -> list[int]:
        raw = os.environ.get("SAFE_PRICE_LR_WINDOWS", "50,200,600")
        return [int(w) for w in raw.split(",") if w.strip()]

    @property
    def output_dir(self) -> Path:
        raw = os.environ.get("SAFE_PRICE_LR_OUTPUT_DIR")
        return Path(raw) if raw else REPO_ROOT / "tests" / "logs"


# ---------------------------------------------------------------------------
# Small query helpers
# ---------------------------------------------------------------------------


def _token_decimals(proxy, token_id: str, default: int = 18) -> int:
    try:
        return proxy.get_definition_of_fungible_token(token_id).decimals
    except Exception as exc:
        logger.warning(f"Could not resolve decimals for {token_id}: {exc}; using {default}")
        return default


def _norm(value, decimals: int):
    return value / 10**decimals if value is not None else None


def _legacy_safe_price(fetcher, abi, token_id: str, amount: int):
    """updateAndGetSafePrice on the pair contract. Returns output amount or None."""
    if abi is None:
        return None
    try:
        payload = abi.encode_custom_type("EsdtTokenPayment", [token_id, 0, amount])
        hex_res = fetcher.get_data("updateAndGetSafePrice", [bytes.fromhex(payload)])
    except Exception as exc:
        logger.debug(f"updateAndGetSafePrice failed: {exc}")
        return None
    if not hex_res:
        return None
    return decode_merged_attributes(hex_res, ESDT_PAYMENT_SCHEMA)["amount"]


# ---------------------------------------------------------------------------
# Simulation driver
# ---------------------------------------------------------------------------


class _Simulation:
    """Drives the long-running swap workload and accumulates sampled rows."""

    def __init__(
        self,
        cfg: LongRunConfig,
        dex_context,
        pair_contract: PairContract,
        swapper,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        self.cfg = cfg
        self.dex_context = dex_context
        self.pair = pair_contract
        self.swapper = swapper
        self.network_providers = network_providers
        self.proxy = network_providers.proxy
        self.bc = blockchain_controller
        self.ensure_esdt_amounts = ensure_esdt_amounts

        self.fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address), self.proxy.url
        )
        self.abi = load_safe_price_abi()
        self.pair_shard = AddressComputer().get_shard_of_address(
            Address.new_from_bech32(pair_contract.address)
        )

        self.first = pair_contract.firstToken
        self.second = pair_contract.secondToken
        self.in_decimals = _token_decimals(self.proxy, self.first)
        self.out_decimals = _token_decimals(self.proxy, self.second)
        self.ref_amount = 10**self.in_decimals
        pair_uses_milliseconds = deployed_safe_price_uses_milliseconds(
            self.proxy, pair_contract.address
        )
        self.round_duration_ms = (
            self.proxy.get_network_config().round_duration
            if pair_uses_milliseconds
            else LEGACY_ROUND_DURATION_MS
        )
        view_contract = dex_context.get_contracts(config.PAIRS_VIEW)[0]
        uses_milliseconds = deployed_safe_price_uses_milliseconds(
            self.proxy, view_contract.address
        )
        self.timestamp_offsets = {
            window: timestamp_offset_for_round_window(
                window, self.round_duration_ms, uses_milliseconds
            )
            for window in self.cfg.windows
        }

        # offline reference oracle, replays every swap from an empty buffer
        self.recorder = SafePriceRecorder()
        self.ref_view = SafePriceView(self.recorder)
        self.first_recorded_round: int | None = None

        self.rows: list[dict] = []
        self.field_names = self._build_header()

    # -- header matching tools/safeprice_monitor.py conventions --
    def _build_header(self) -> list[str]:
        header = ["block", "updateAndGetSafePrice", "spot_price"]
        for w in self.cfg.windows:
            header.append(f"getSafePriceByRoundOffset({w})")
            header.append(f"getSafePriceByTimestampOffset({self.timestamp_offsets[w]})")
        for w in self.cfg.windows:
            header.append(f"{w}_rounds_avg_offline")
        return header

    def _current_round(self) -> int:
        return self.proxy.get_network_status(self.pair_shard).current_round

    # -- one recorded swap; returns the execution round --
    def _swap(self, token_in: str, token_out: str, in_reserve: int, fraction: int) -> int:
        swap_amount = max(in_reserve // fraction, 1)
        res_before = reserves(self.fetcher)  # pair records PRE-swap reserves
        self.swapper.sync_nonce(self.proxy)
        event = SwapFixedInputEvent(token_in, swap_amount, token_out, 1)
        tx = self.pair.swap_fixed_input(self.network_providers, self.swapper, event)
        self.bc.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, self.proxy)
        rnd = get_transaction_execution_round(self.proxy, tx)
        self.recorder.update_safe_price(res_before[0], res_before[1], res_before[2], rnd)
        if self.first_recorded_round is None:
            self.first_recorded_round = rnd
        return rnd

    def _refund(self) -> None:
        res = reserves(self.fetcher)
        self.ensure_esdt_amounts(self.swapper, {self.first: res[0], self.second: res[1]})

    # -- offline reference TWAP over a round window (None if not enough history) --
    def _ref_offset(self, window: int, cur: tuple[int, int, int], cur_round: int):
        if self.first_recorded_round is None or cur_round - window < self.first_recorded_round:
            return None
        try:
            return self.ref_view.get_safe_price_by_round_offset(
                window, self.ref_amount, True, cur[0], cur[1], cur[2], cur_round
            )
        except SafePriceError:
            return None

    def _sample(self) -> None:
        cur_round = self._current_round()
        cur = reserves(self.fetcher)
        spot = spot_equivalent(self.fetcher, self.first, self.ref_amount)
        legacy = _legacy_safe_price(self.fetcher, self.abi, self.first, self.ref_amount)

        row = {
            "block": cur_round,
            "updateAndGetSafePrice": _norm(legacy, self.out_decimals),
            "spot_price": _norm(spot, self.out_decimals),
        }
        for w in self.cfg.windows:
            onchain_round = query_safe_price_by_offset(
                self.dex_context,
                self.network_providers,
                self.pair.address,
                "getSafePriceByRoundOffset",
                w,
                self.first,
                self.ref_amount,
            )
            onchain_ts = query_safe_price_by_offset(
                self.dex_context,
                self.network_providers,
                self.pair.address,
                "getSafePriceByTimestampOffset",
                self.timestamp_offsets[w],
                self.first,
                self.ref_amount,
            )
            row[f"getSafePriceByRoundOffset({w})"] = _norm(
                onchain_round["amount"] if onchain_round else None, self.out_decimals
            )
            row[f"getSafePriceByTimestampOffset({self.timestamp_offsets[w]})"] = _norm(
                onchain_ts["amount"] if onchain_ts else None, self.out_decimals
            )
        for w in self.cfg.windows:
            row[f"{w}_rounds_avg_offline"] = _norm(
                self._ref_offset(w, cur, cur_round), self.out_decimals
            )
        self.rows.append(row)

    def run(self) -> None:
        cfg = self.cfg
        r0 = reserves(self.fetcher)
        assert r0[0] > 0 and r0[1] > 0, "pool must have liquidity to run the simulation"
        self._refund()

        start_round = self._current_round()
        last_round = start_round
        last_spike_round = start_round
        spike_count = 0
        step = 0
        started = time.time()

        logger.info(
            f"Long-running safe-price sim: ~{cfg.rounds} rounds, cadence={cfg.cadence}, "
            f"spike every {cfg.spike_interval} rounds, windows={cfg.windows}, "
            f"start_round={start_round}"
        )

        while last_round - start_round < cfg.rounds:
            res = reserves(self.fetcher)

            if last_round - last_spike_round >= cfg.spike_interval:
                # Transient spike: push hard one way, sample at the peak, then revert.
                up = spike_count % 2 == 0
                if up:
                    self._swap(self.first, self.second, res[0], cfg.spike_fraction)
                else:
                    self._swap(self.second, self.first, res[1], cfg.spike_fraction)
                self._sample()  # capture the spot excursion while it is live
                self.bc.wait_blocks(cfg.cadence)

                res = reserves(self.fetcher)
                if up:
                    last_round = self._swap(self.second, self.first, res[1], cfg.spike_fraction)
                else:
                    last_round = self._swap(self.first, self.second, res[0], cfg.spike_fraction)
                last_spike_round = last_round
                spike_count += 1
                logger.info(f"[spike #{spike_count}] {'up' if up else 'down'} @round={last_round}")
            else:
                # Regular alternating small swap keeps a stable baseline.
                if step % 2 == 0:
                    last_round = self._swap(self.first, self.second, res[0], cfg.regular_fraction)
                else:
                    last_round = self._swap(self.second, self.first, res[1], cfg.regular_fraction)

            step += 1
            self.bc.wait_blocks(cfg.cadence)

            if step % cfg.refund_every == 0:
                self._refund()
            if step % cfg.sample_every == 0:
                self._sample()
                last_round = self.rows[-1]["block"]
                elapsed = time.time() - started
                logger.info(
                    f"[progress] step={step} round={last_round} "
                    f"({last_round - start_round}/{cfg.rounds}) samples={len(self.rows)} "
                    f"elapsed={elapsed:.0f}s spikes={spike_count}"
                )

        logger.info(
            f"Simulation finished: steps={step} samples={len(self.rows)} spikes={spike_count} "
            f"rounds_spanned={last_round - start_round} elapsed={time.time() - started:.0f}s"
        )

    # -- output --
    def write_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path.open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.field_names, restval="")
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)
        logger.info(f"Wrote {len(self.rows)} samples to {path}")
        return path


def _generate_plot(csv_path: Path, png_path: Path, title: str):
    try:
        from tools.safeprice_plot import main as plot_main
    except Exception as exc:
        logger.warning(f"Plotting unavailable ({exc}); skipping chart generation")
        return None
    try:
        plot_main(["--file", str(csv_path), "--output", str(png_path), "--title", title])
    except Exception as exc:
        logger.warning(f"Plot generation failed: {exc}")
        return None
    return png_path


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
@pytest.mark.slow
class TestSafePriceLongRunning:
    """Long time-frame TWAP behaviour visualisation + smoothing assertions."""

    def test_safe_price_long_running_simulation(
        self,
        dex_context,
        pair_contract: PairContract,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        SCENARIO: Span thousands of rounds of steady swaps with periodic spikes,
                  sampling every TWAP window, and chart the result.

        GIVEN: A pool driven by same-shard swaps (so observation rounds are exact)
        WHEN:  Small alternating swaps run at a fixed cadence with large transient
               spike swaps injected at fixed round intervals, sampled into a CSV
        THEN:
            - A non-trivial number of samples is collected
            - The on-chain windowed safe price matches the offline reference oracle
              wherever both are available
            - Across spikes the windowed TWAP deviates LESS than raw spot (smoothing)
            - A CSV + PNG chart are produced under the output directory

        SECURITY: Demonstrates manipulation resistance over time — transient spot
                  spikes are dampened by the time-weighted oracle, more so for
                  longer windows.
        """
        if not test_environment.supports_time_control():
            pytest.skip("Long-running simulation requires chain simulator block control")

        cfg = LongRunConfig()
        swapper = pick_same_shard_account(
            dex_context, pair_contract.address, test_environment, network_providers
        )

        sim = _Simulation(
            cfg,
            dex_context,
            pair_contract,
            swapper,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
        )
        sim.run()

        # --- persist + chart ---
        suffix = time.strftime("%Y%m%d_%H%M%S")
        csv_path = cfg.output_dir / f"safe_price_long_running_{suffix}.csv"
        png_path = cfg.output_dir / f"safe_price_long_running_{suffix}.png"
        sim.write_csv(csv_path)
        chart = _generate_plot(
            csv_path,
            png_path,
            f"Safe Price — long run ({len(sim.rows)} samples, {len(cfg.windows)} windows)",
        )

        # --- assertions ---
        assert len(sim.rows) >= 5, f"expected several samples, got {len(sim.rows)}"
        assert csv_path.exists(), "CSV output should be written"
        if chart is not None:
            assert png_path.exists(), "PNG chart should be written when plotting is available"

        # On-chain windowed TWAP must equal the offline reference where both exist.
        matched = 0
        for row in sim.rows:
            for w in cfg.windows:
                onchain = row[f"getSafePriceByRoundOffset({w})"]
                offline = row[f"{w}_rounds_avg_offline"]
                if onchain in (None, "") or offline in (None, ""):
                    continue
                tol = max(abs(offline) * 1e-4, 1e-9)
                assert abs(onchain - offline) <= tol, (
                    f"on-chain offset({w}) {onchain} != reference {offline} @block={row['block']}"
                )
                matched += 1
        logger.info(f"on-chain vs reference cross-checks matched: {matched}")

        # Smoothing: across the run the windowed TWAP deviates less than spot.
        spot_vals = [r["spot_price"] for r in sim.rows if isinstance(r["spot_price"], float)]
        if len(spot_vals) >= 5:
            baseline = statistics.median(spot_vals)
            spot_dev = max(abs(v - baseline) for v in spot_vals) / baseline

            # Use the largest window that produced enough offline samples.
            best = None
            for w in cfg.windows:
                key = f"{w}_rounds_avg_offline"
                vals = [r[key] for r in sim.rows if isinstance(r[key], float)]
                if len(vals) >= 5:
                    best = (w, vals)
            if best is not None and spot_dev > 0:
                w, vals = best
                twap_dev = max(abs(v - baseline) for v in vals) / baseline
                logger.info(
                    f"deviation from baseline {baseline:.6f}: spot={spot_dev:.4f} "
                    f"twap(window={w})={twap_dev:.4f}"
                )
                assert twap_dev <= spot_dev, (
                    f"windowed TWAP (window={w}) should smooth spot: "
                    f"twap_dev={twap_dev:.4f} > spot_dev={spot_dev:.4f}"
                )

        logger.info(f"Long-running safe-price test complete. Chart: {chart or 'not generated'}")
