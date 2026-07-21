"""Deterministic long-running safe-price test for Supernova pair bytecode.

This test upgrades one loaded mainnet pair and the safe-price-view contract to
the WASM artifacts from ``wasm-supernova/``, resets that pair's safe-price oracle
state, then executes a seeded trade tape. Artifacts are resolved from the sibling
smart-contract checkout first, with ``wasm-supernova/`` as an optional fallback.
The same tape can be replayed later
against another pair WASM/refactor to compare outputs from the same starting
state and exact transaction inputs.

Outputs are written to ``tests/logs`` by default:

- ``safe_price_supernova_<seed...>.scenario.json``: deterministic trade tape
- ``safe_price_supernova_<seed...>.csv``: chartable samples
- ``safe_price_supernova_<seed...>.png``: best-effort plot, if pandas/matplotlib exist

Quick smoke:
    MX_RUN_SUPERNOVA_TESTS=1 MX_CHAIN_SIM_IGNORE_STATE_CHRONOLOGY=1 \
      SUPERNOVA_SAFE_PRICE_TRADES=24 \
      PYTHONPATH=. python -m pytest \
      tests/integration/pair/test_safe_price_supernova_long_running.py \
      --env=chainsim --skip-farm-staking-state -q -s
"""

from __future__ import annotations

import csv
import json
import os
import random
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest


if os.environ.get("MX_RUN_SUPERNOVA_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Destructive Supernova oracle scenarios require an isolated simulator and MX_RUN_SUPERNOVA_TESTS=1",
        allow_module_level=True,
    )
import requests
from multiversx_sdk import Address, AddressComputer

import config
from contracts.pair_contract import PairContract, PairContractVersion, SwapFixedInputEvent
from tests.helpers import TransactionAssertions
from tests.integration.pair.safe_price_helpers import (
    block_timestamp_milliseconds,
    deployed_safe_price_uses_milliseconds,
    deploy_safe_price_view,
    load_safe_price_abi,
    network_status_timestamp_milliseconds,
    pick_same_shard_account,
    query_safe_price_by_offset,
    reserves,
    spot_equivalent,
    timestamp_offset_for_round_window,
)
from tests.integration.pair.supernova_reference_oracle import (
    SupernovaSafePriceError,
    SupernovaSafePriceRecorder,
)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.utils_chain import decode_merged_attributes, nominated_amount


logger = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
WASM_DIR = Path(os.environ.get("SUPERNOVA_WASM_DIR", Path(config.DEFAULT_WORKSPACE) / "wasm-supernova"))


def _resolve_router_wasm() -> Path:
    override = os.environ.get("SUPERNOVA_ROUTER_WASM")
    if override:
        return Path(override)

    candidates = [
        Path(config.DEFAULT_WORKSPACE).parent / "mx-exchange-sc" / "dex" / "router" / "output" / "router.wasm",
        WASM_DIR / "router.wasm",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_pair_artifact(name: str, env_name: str) -> Path:
    override = os.environ.get(env_name)
    if override:
        return Path(override)

    candidates = [
        Path(config.DEFAULT_WORKSPACE).parent / "mx-exchange-sc" / "dex" / "pair" / "output" / name,
        WASM_DIR / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


PAIR_WASM = _resolve_pair_artifact("pair-full.wasm", "SUPERNOVA_PAIR_WASM")
SAFE_PRICE_VIEW_WASM = _resolve_pair_artifact(
    "safe-price-view.wasm", "SUPERNOVA_SAFE_PRICE_VIEW_WASM"
)
ROUTER_WASM = _resolve_router_wasm()

ESDT_PAYMENT_SCHEMA = {"token_identifier": "string", "token_nonce": "u64", "amount": "biguint"}

PRICE_OBSERVATIONS_LEN_KEY = "70726963655f6f62736572766174696f6e732e6c656e"
SAFE_PRICE_CURRENT_INDEX_KEY = "736166655f70726963655f63757272656e745f696e646578"
CURRENT_PRICE_OBSERVATION_KEY = "63757272656e745f70726963655f6f62736572766174696f6e"
SAFE_PRICE_ROUND_SAVE_INTERVAL_KEY = "736166655f70726963655f726f756e645f736176655f696e74657276616c"
DEFAULT_SAFE_PRICE_ROUNDS_OFFSET_KEY = "64656661756c745f736166655f70726963655f726f756e64735f6f6666736574"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class SupernovaRunConfig:
    seed: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_SEED", 20260703))
    trades: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_TRADES", 512))
    round_save_interval: int = field(
        default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_ROUND_SAVE_INTERVAL", 5)
    )
    default_rounds_offset: int = field(
        default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_DEFAULT_OFFSET", 600)
    )
    spike_every: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_SPIKE_EVERY", 64))
    min_wait_blocks: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_MIN_WAIT", 1))
    max_wait_blocks: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_MAX_WAIT", 4))
    regular_min_bps: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_REGULAR_MIN_BPS", 2))
    regular_max_bps: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_REGULAR_MAX_BPS", 12))
    spike_min_bps: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_SPIKE_MIN_BPS", 650))
    spike_max_bps: int = field(default_factory=lambda: _env_int("SUPERNOVA_SAFE_PRICE_SPIKE_MAX_BPS", 950))

    @property
    def windows(self) -> list[int]:
        raw = os.environ.get("SUPERNOVA_SAFE_PRICE_WINDOWS", "20,80,200")
        return [int(w) for w in raw.split(",") if w.strip()]

    @property
    def output_dir(self) -> Path:
        raw = os.environ.get("SUPERNOVA_SAFE_PRICE_OUTPUT_DIR")
        return Path(raw) if raw else REPO_ROOT / "tests" / "logs"

    @property
    def basename(self) -> str:
        run_id = os.environ.get("SUPERNOVA_SAFE_PRICE_RUN_ID", "")
        suffix = f"_{run_id}" if run_id else ""
        return (
            f"safe_price_supernova_seed{self.seed}_trades{self.trades}"
            f"_interval{self.round_save_interval}{suffix}"
        )


@dataclass(frozen=True)
class TradeStep:
    index: int
    tag: str
    token_in: str
    token_out: str
    amount: int
    amount_bps_of_initial_reserve: int
    wait_blocks_after: int


def _round_duration_ms(network_providers) -> int:
    return network_providers.proxy.get_network_config().round_duration


def _router_safe_price_config_mode(router_bytes: bytes) -> str:
    if b"setSafePriceTimestampSaveInterval" in router_bytes:
        return "timestamp"
    if b"setSafePriceRoundSaveInterval" in router_bytes:
        return "round"

    raise AssertionError("Router WASM does not expose known safe-price config endpoints")


def _try_query_safe_price_by_offset(
    dex_context,
    network_providers,
    pair_address: str,
    endpoint: str,
    offset: int,
    token_id: str,
    amount: int,
):
    try:
        return query_safe_price_by_offset(
            dex_context,
            network_providers,
            pair_address,
            endpoint,
            offset,
            token_id,
            amount,
        )
    except Exception as exc:
        logger.debug(f"{endpoint}({offset}) unavailable at this sample: {exc}")
        return None


def _norm(value: int | None, decimals: int) -> float | None:
    return value / 10**decimals if value is not None else None


def _token_decimals(proxy, token_id: str, default: int = 18) -> int:
    try:
        return proxy.get_definition_of_fungible_token(token_id).decimals
    except Exception as exc:
        logger.warning(f"Could not resolve decimals for {token_id}: {exc}; using {default}")
        return default


def _send_and_assert(tx_hash: str, blockchain_controller, proxy, label: str) -> None:
    assert tx_hash, f"{label} did not produce a transaction hash"
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)


def _get_transaction_with_retry(proxy, tx_hash: str, attempts: int = 5, delay_seconds: int = 2):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return proxy.get_transaction(tx_hash)
        except TimeoutError as error:
            last_error = error
            logger.warning(
                f"Timed out fetching transaction details for {tx_hash}; "
                f"retry {attempt}/{attempts}"
            )
            time.sleep(delay_seconds)
    raise last_error


def _set_contract_owner(contract_address: str, owner_address: str, proxy_url: str) -> None:
    response = requests.post(
        f"{proxy_url}/simulator/set-state",
        json=[{"address": contract_address, "ownerAddress": owner_address}],
        timeout=30,
    )
    response.raise_for_status()
    response = requests.post(f"{proxy_url}/simulator/generate-blocks/1", timeout=30)
    response.raise_for_status()


def _ensure_account_has_chain_sim_egld(account, test_environment, network_providers, amount: int) -> None:
    from tests.environments import ChainsimEnvironment

    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim and account.address:
        test_environment.chain_sim.fund_users_w_egld([account.address.to_bech32()], amount)
    account.sync_nonce(network_providers.proxy)


def _advance_chain_sim_deploy_nonce(account, test_environment, network_providers) -> None:
    from tests.environments import ChainsimEnvironment

    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim and account.address:
        test_environment.chain_sim.advance_nonce_for_deploys(account.address.to_bech32())
    account.sync_nonce(network_providers.proxy)


def _reset_pair_safe_price_storage(pair_address: str, proxy_url: str) -> None:
    """Start the Supernova oracle from a deterministic empty observation buffer."""
    response = requests.post(
        f"{proxy_url}/simulator/set-state",
        json=[
            {
                "address": pair_address,
                "pairs": {
                    PRICE_OBSERVATIONS_LEN_KEY: "",
                    SAFE_PRICE_CURRENT_INDEX_KEY: "",
                    CURRENT_PRICE_OBSERVATION_KEY: "",
                },
            }
        ],
        timeout=30,
    )
    response.raise_for_status()
    response = requests.post(f"{proxy_url}/simulator/generate-blocks/1", timeout=30)
    response.raise_for_status()


def _u64_storage_value(value: int) -> str:
    return value.to_bytes(8, "big").lstrip(b"\x00").hex()


def _seed_legacy_round_safe_price_config(router_address: str, proxy_url: str, cfg: SupernovaRunConfig) -> None:
    """Seed old router storage for baseline pair artifacts that still read round config."""
    response = requests.post(
        f"{proxy_url}/simulator/set-state",
        json=[
            {
                "address": router_address,
                "pairs": {
                    SAFE_PRICE_ROUND_SAVE_INTERVAL_KEY: _u64_storage_value(cfg.round_save_interval),
                    DEFAULT_SAFE_PRICE_ROUNDS_OFFSET_KEY: _u64_storage_value(cfg.default_rounds_offset),
                },
            }
        ],
        timeout=30,
    )
    response.raise_for_status()
    response = requests.post(f"{proxy_url}/simulator/generate-blocks/1", timeout=30)
    response.raise_for_status()


def _deploy_supernova_safe_price_view(
    dex_context,
    deployer_account,
    network_providers,
    blockchain_controller,
) -> str:
    """Deploy a fresh safe-price view contract and make helper queries use it.

    The mainnet state dump can contain the configured pairs_view address without
    bytecode. Deploying a fresh view contract avoids depending on that dump and
    keeps replay runs deterministic.
    """
    return deploy_safe_price_view(
        dex_context,
        deployer_account,
        network_providers,
        blockchain_controller,
        SAFE_PRICE_VIEW_WASM,
    )


def _upgrade_supernova_safe_price_stack(
    dex_context,
    pair_contract: PairContract,
    router_contract,
    deployer_account,
    test_environment,
    network_providers,
    blockchain_controller,
    cfg: SupernovaRunConfig,
) -> None:
    assert ROUTER_WASM.exists(), f"Router WASM not found at {ROUTER_WASM}"
    router_bytes = ROUTER_WASM.read_bytes()
    router_config_mode = _router_safe_price_config_mode(router_bytes)
    assert PAIR_WASM.exists(), f"Pair WASM not found at {PAIR_WASM}"
    assert SAFE_PRICE_VIEW_WASM.exists(), f"safe-price-view WASM not found at {SAFE_PRICE_VIEW_WASM}"

    proxy = network_providers.proxy
    proxy_url = proxy.url
    deployer_bech32 = deployer_account.address.to_bech32()
    _ensure_account_has_chain_sim_egld(
        deployer_account, test_environment, network_providers, nominated_amount(20)
    )
    _advance_chain_sim_deploy_nonce(deployer_account, test_environment, network_providers)

    # Chain-simulator state comes from mainnet, so patch ownership locally for
    # deterministic upgrade/config calls.
    _set_contract_owner(router_contract.address, deployer_bech32, proxy_url)

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.contract_upgrade(deployer_account, proxy, str(ROUTER_WASM))
    _send_and_assert(tx_hash, blockchain_controller, proxy, "router upgrade")

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.resume(deployer_account, proxy)
    _send_and_assert(tx_hash, blockchain_controller, proxy, "router resume")

    view_address = _deploy_supernova_safe_price_view(
        dex_context, deployer_account, network_providers, blockchain_controller
    )

    template_address = router_contract.get_pair_template_address(proxy)
    _set_contract_owner(template_address, deployer_bech32, proxy_url)
    template_pair = PairContract("", "", PairContractVersion.V2, address=template_address)
    deployer_account.sync_nonce(proxy)
    tx_hash = template_pair.contract_upgrade(
        deployer_account, proxy, str(PAIR_WASM), [], no_init=True
    )
    _send_and_assert(tx_hash, blockchain_controller, proxy, "pair template upgrade")

    round_duration_ms = _round_duration_ms(network_providers)
    if router_config_mode == "timestamp":
        deployer_account.sync_nonce(proxy)
        tx_hash = router_contract.set_safe_price_timestamp_save_interval(
            deployer_account,
            proxy,
            cfg.round_save_interval * round_duration_ms,
        )
        _send_and_assert(tx_hash, blockchain_controller, proxy, "set safe-price timestamp interval")

        deployer_account.sync_nonce(proxy)
        tx_hash = router_contract.set_default_safe_price_timestamp_offset(
            deployer_account,
            proxy,
            cfg.default_rounds_offset * round_duration_ms,
        )
        _send_and_assert(tx_hash, blockchain_controller, proxy, "set safe-price timestamp offset")
    else:
        deployer_account.sync_nonce(proxy)
        tx_hash = router_contract.set_safe_price_round_save_interval(
            deployer_account, proxy, cfg.round_save_interval
        )
        _send_and_assert(tx_hash, blockchain_controller, proxy, "set safe-price round interval")

        deployer_account.sync_nonce(proxy)
        tx_hash = router_contract.set_default_safe_price_rounds_offset(
            deployer_account, proxy, cfg.default_rounds_offset
        )
        _send_and_assert(tx_hash, blockchain_controller, proxy, "set safe-price default offset")

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.pair_contract_upgrade(
        deployer_account,
        proxy,
        [pair_contract.firstToken, pair_contract.secondToken],
    )
    _send_and_assert(tx_hash, blockchain_controller, proxy, "target pair upgrade")

    _seed_legacy_round_safe_price_config(router_contract.address, proxy_url, cfg)
    _reset_pair_safe_price_storage(pair_contract.address, proxy_url)
    logger.info(
        "Supernova safe-price stack ready | pair=%s | view=%s | mode=%s | interval=%s | default_offset=%s",
        pair_contract.address,
        view_address,
        router_config_mode,
        cfg.round_save_interval,
        cfg.default_rounds_offset,
    )


def _generate_trade_tape(
    cfg: SupernovaRunConfig,
    pair_contract: PairContract,
    initial_reserves: tuple[int, int, int],
) -> list[TradeStep]:
    rng = random.Random(cfg.seed)
    tape: list[TradeStep] = []
    last_first_to_second = False

    while len(tape) < cfg.trades:
        index = len(tape)
        if cfg.spike_every > 0 and index > 0 and index % cfg.spike_every == 0 and index + 1 < cfg.trades:
            first_to_second = bool(rng.getrandbits(1))
            bps = rng.randint(cfg.spike_min_bps, cfg.spike_max_bps)
            tape.append(
                _make_trade_step(cfg, pair_contract, initial_reserves, index, "spike", first_to_second, bps, rng)
            )
            tape.append(
                _make_trade_step(
                    cfg,
                    pair_contract,
                    initial_reserves,
                    index + 1,
                    "spike_revert",
                    not first_to_second,
                    bps,
                    rng,
                )
            )
            last_first_to_second = not first_to_second
            continue

        if rng.random() < 0.7:
            first_to_second = not last_first_to_second
        else:
            first_to_second = bool(rng.getrandbits(1))
        bps = rng.randint(cfg.regular_min_bps, cfg.regular_max_bps)
        tape.append(
            _make_trade_step(cfg, pair_contract, initial_reserves, index, "regular", first_to_second, bps, rng)
        )
        last_first_to_second = first_to_second

    return tape


def _make_trade_step(
    cfg: SupernovaRunConfig,
    pair_contract: PairContract,
    initial_reserves: tuple[int, int, int],
    index: int,
    tag: str,
    first_to_second: bool,
    bps: int,
    rng: random.Random,
) -> TradeStep:
    reserve = initial_reserves[0] if first_to_second else initial_reserves[1]
    amount = max(reserve * bps // 10_000, 1)
    return TradeStep(
        index=index,
        tag=tag,
        token_in=pair_contract.firstToken if first_to_second else pair_contract.secondToken,
        token_out=pair_contract.secondToken if first_to_second else pair_contract.firstToken,
        amount=amount,
        amount_bps_of_initial_reserve=bps,
        wait_blocks_after=rng.randint(cfg.min_wait_blocks, cfg.max_wait_blocks),
    )


def _write_scenario(path: Path, cfg: SupernovaRunConfig, pair_contract: PairContract, tape: list[TradeStep]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": {
            **asdict(cfg),
            "windows": cfg.windows,
            "output_dir": str(cfg.output_dir),
            "wasm_dir": str(WASM_DIR),
        },
        "pair": {
            "address": pair_contract.address,
            "firstToken": pair_contract.firstToken,
            "secondToken": pair_contract.secondToken,
            "lpToken": pair_contract.lpToken,
        },
        "trade_tape": [asdict(step) for step in tape],
    }
    with Path.open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    logger.info(f"Wrote deterministic scenario to {path}")
    return path


class _SupernovaLongRun:
    def __init__(
        self,
        cfg: SupernovaRunConfig,
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
        self.fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), self.proxy.url)
        self.abi = load_safe_price_abi()
        self.round_duration_ms = _round_duration_ms(network_providers)
        view_contract = dex_context.get_contracts(config.PAIRS_VIEW)[0]
        uses_milliseconds = deployed_safe_price_uses_milliseconds(
            self.proxy, view_contract.address
        )
        assert uses_milliseconds, (
            "Supernova safe-price view must use millisecond timestamps"
        )
        self.timestamp_offsets = {
            window: timestamp_offset_for_round_window(
                window, self.round_duration_ms, uses_milliseconds
            )
            for window in self.cfg.windows
        }
        self.pair_shard = AddressComputer().get_shard_of_address(Address.new_from_bech32(pair_contract.address))
        self.input_decimals = _token_decimals(self.proxy, self.pair.firstToken)
        self.output_decimals = _token_decimals(self.proxy, self.pair.secondToken)
        self.reference_amount = 10**self.input_decimals
        self.recorder = SupernovaSafePriceRecorder(
            timestamp_save_interval=timestamp_offset_for_round_window(
                cfg.round_save_interval,
                self.round_duration_ms,
                uses_milliseconds,
            )
        )
        self.rows: list[dict] = []
        self.field_names = self._build_header()
        self.round_matches = 0
        self.timestamp_matches = 0

    def _build_header(self) -> list[str]:
        header = ["block", "updateAndGetSafePrice", "spot_price"]
        for window in self.cfg.windows:
            header.append(f"getSafePriceByRoundOffset({window})")
            header.append(f"getSafePriceByTimestampOffset({self.timestamp_offsets[window]})")
        for window in self.cfg.windows:
            header.append(f"{window}_rounds_avg_offline")
        return header

    def run(self, tape: list[TradeStep]) -> None:
        totals: dict[str, int] = {}
        for step in tape:
            totals[step.token_in] = totals.get(step.token_in, 0) + step.amount
        # Fund once to keep the trade loop deterministic and avoid repeated live API calls.
        self.ensure_esdt_amounts(self.swapper, {token: amount * 2 for token, amount in totals.items()})

        start_round = self._current_round()
        started = time.time()
        for step in tape:
            self._execute_step(step)
            self._sample()
            if step.wait_blocks_after > 0:
                self.bc.wait_blocks(step.wait_blocks_after)

            if (step.index + 1) % 25 == 0 or step.index == len(tape) - 1:
                current_round = self.rows[-1]["block"] if self.rows else self._current_round()
                observation_count = self.recorder.observation_count
                logger.info(
                    f"[supernova progress] trades={step.index + 1}/{len(tape)} "
                    f"round_delta={current_round - start_round} samples={len(self.rows)} "
                    f"observations={observation_count} elapsed={time.time() - started:.0f}s"
                )

    def write_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with Path.open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.field_names, restval="")
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)
        logger.info(f"Wrote {len(self.rows)} Supernova samples to {path}")
        return path

    def _execute_step(self, step: TradeStep) -> None:
        reserves_before = reserves(self.fetcher)
        self.swapper.sync_nonce(self.proxy)
        event = SwapFixedInputEvent(step.token_in, step.amount, step.token_out, 1)
        tx_hash = self.pair.swap_fixed_input(self.network_providers, self.swapper, event)
        self.bc.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, self.proxy)
        tx = _get_transaction_with_retry(self.proxy, tx_hash)
        tx_round = int(getattr(tx, "round", 0) or getattr(tx, "raw", {}).get("round", 0))
        tx_timestamp = self._transaction_block_timestamp(tx)
        self.recorder.update_safe_price(
            reserves_before[0],
            reserves_before[1],
            reserves_before[2],
            tx_round,
            tx_timestamp,
        )

    def _sample(self) -> None:
        cur_round, cur_timestamp = self._current_round_and_timestamp()
        cur_reserves = reserves(self.fetcher)
        spot = spot_equivalent(self.fetcher, self.pair.firstToken, self.reference_amount)
        legacy = self._legacy_safe_price()
        row = {
            "block": cur_round,
            "updateAndGetSafePrice": _norm(legacy, self.output_decimals),
            "spot_price": _norm(spot, self.output_decimals),
        }

        reference_by_window: dict[int, int | None] = {}
        for window in self.cfg.windows:
            reference_by_window[window] = self._reference_round_price(window, cur_reserves, cur_round, cur_timestamp)
            onchain_round = _try_query_safe_price_by_offset(
                self.dex_context,
                self.network_providers,
                self.pair.address,
                "getSafePriceByRoundOffset",
                window,
                self.pair.firstToken,
                self.reference_amount,
            )
            if onchain_round and reference_by_window[window] is not None:
                self._assert_close_amount(
                    onchain_round["amount"], reference_by_window[window], f"roundOffset({window})", cur_round
                )
                self.round_matches += 1
            row[f"getSafePriceByRoundOffset({window})"] = _norm(
                onchain_round["amount"] if onchain_round else None, self.output_decimals
            )

            timestamp_offset = self.timestamp_offsets[window]
            reference_ts = self._reference_timestamp_price(
                timestamp_offset, cur_reserves, cur_round, cur_timestamp
            )
            onchain_ts = _try_query_safe_price_by_offset(
                self.dex_context,
                self.network_providers,
                self.pair.address,
                "getSafePriceByTimestampOffset",
                timestamp_offset,
                self.pair.firstToken,
                self.reference_amount,
            )
            if onchain_ts and reference_ts is not None:
                self._assert_close_amount(
                    onchain_ts["amount"], reference_ts, f"timestampOffset({timestamp_offset})", cur_round
                )
                self.timestamp_matches += 1
            row[f"getSafePriceByTimestampOffset({timestamp_offset})"] = _norm(
                onchain_ts["amount"] if onchain_ts else None, self.output_decimals
            )

        for window in self.cfg.windows:
            row[f"{window}_rounds_avg_offline"] = _norm(reference_by_window[window], self.output_decimals)

        self.rows.append(row)

    def _legacy_safe_price(self) -> int | None:
        if self.abi is None:
            return None
        try:
            payload = self.abi.encode_custom_type(
                "EsdtTokenPayment", [self.pair.firstToken, 0, self.reference_amount]
            )
            hex_res = self.fetcher.get_data("updateAndGetSafePrice", [bytes.fromhex(payload)])
        except Exception as exc:
            logger.debug(f"updateAndGetSafePrice failed: {exc}")
            return None
        if not hex_res:
            return None
        return decode_merged_attributes(hex_res, ESDT_PAYMENT_SCHEMA)["amount"]

    def _reference_round_price(
        self, window: int, cur_reserves: tuple[int, int, int], cur_round: int, cur_timestamp: int
    ) -> int | None:
        try:
            return self.recorder.get_safe_price_by_round_offset(
                window,
                self.reference_amount,
                True,
                cur_reserves[0],
                cur_reserves[1],
                cur_reserves[2],
                cur_round,
                cur_timestamp,
            )
        except SupernovaSafePriceError:
            return None

    def _reference_timestamp_price(
        self, timestamp_offset: int, cur_reserves: tuple[int, int, int], cur_round: int, cur_timestamp: int
    ) -> int | None:
        try:
            return self.recorder.get_safe_price_by_timestamp_offset(
                timestamp_offset,
                self.reference_amount,
                True,
                cur_reserves[0],
                cur_reserves[1],
                cur_reserves[2],
                cur_round,
                cur_timestamp,
            )
        except SupernovaSafePriceError:
            return None

    def _current_round(self) -> int:
        return self.proxy.get_network_status(self.pair_shard).current_round

    def _current_round_and_timestamp(self) -> tuple[int, int]:
        status = self.proxy.get_network_status(self.pair_shard)
        return status.current_round, network_status_timestamp_milliseconds(status)

    def _transaction_block_timestamp(self, tx) -> int:
        block_hash = getattr(tx, "block_hash", b"") or bytes.fromhex(
            getattr(tx, "raw", {}).get("blockHash", "")
        )
        if block_hash:
            try:
                return block_timestamp_milliseconds(
                    self.proxy.get_block(self.pair_shard, block_hash=block_hash)
                )
            except Exception as exc:
                logger.debug(f"Could not fetch tx block timestamp; using shard status timestamp: {exc}")
        return network_status_timestamp_milliseconds(
            self.proxy.get_network_status(self.pair_shard)
        )

    def _assert_close_amount(self, onchain: int, reference: int, label: str, block: int) -> None:
        tolerance = max(reference // 10_000, 1)  # 1 bps for timestamp interpolation/rounding edges
        assert abs(onchain - reference) <= tolerance, (
            f"{label} mismatch at block {block}: on-chain={onchain}, reference={reference}, "
            f"tolerance={tolerance}"
        )


def _generate_plot(csv_path: Path, png_path: Path, title: str) -> Path | None:
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


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
@pytest.mark.slow
class TestSupernovaSafePriceLongRunning:
    def test_supernova_safe_price_deterministic_trade_tape(
        self,
        dex_context,
        pair_contract: PairContract,
        router_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        if not test_environment.supports_time_control():
            pytest.skip("Supernova deterministic safe-price run requires chain simulator")

        cfg = SupernovaRunConfig()
        _upgrade_supernova_safe_price_stack(
            dex_context,
            pair_contract,
            router_contract,
            deployer_account,
            test_environment,
            network_providers,
            blockchain_controller,
            cfg,
        )

        swapper = pick_same_shard_account(
            dex_context, pair_contract.address, test_environment, network_providers
        )
        fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
        initial_reserves = reserves(fetcher)
        assert initial_reserves[0] > 0 and initial_reserves[1] > 0 and initial_reserves[2] > 0

        tape = _generate_trade_tape(cfg, pair_contract, initial_reserves)
        scenario_path = cfg.output_dir / f"{cfg.basename}.scenario.json"
        csv_path = cfg.output_dir / f"{cfg.basename}.csv"
        png_path = cfg.output_dir / f"{cfg.basename}.png"
        _write_scenario(scenario_path, cfg, pair_contract, tape)

        runner = _SupernovaLongRun(
            cfg,
            dex_context,
            pair_contract,
            swapper,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
        )
        runner.run(tape)
        runner.write_csv(csv_path)
        chart = _generate_plot(
            csv_path,
            png_path,
            f"Safe Price — Supernova deterministic run ({len(runner.rows)} samples, seed {cfg.seed})",
        )

        assert scenario_path.exists(), "scenario JSON should be written"
        assert csv_path.exists(), "CSV output should be written"
        assert len(runner.rows) == len(tape), "sample count should match deterministic trade tape"
        assert runner.recorder.observation_count >= 3, "Supernova oracle should finalize observations"
        assert runner.round_matches > 0, "expected round-offset comparisons against the reference"
        assert runner.timestamp_matches > 0, "expected timestamp-offset comparisons against the reference"
        if chart is not None:
            assert png_path.exists(), "PNG chart should be written when plotting is available"

        spot_values = [r["spot_price"] for r in runner.rows if isinstance(r["spot_price"], float)]
        longest_window = max(cfg.windows)
        twap_values = [
            r[f"{longest_window}_rounds_avg_offline"]
            for r in runner.rows
            if isinstance(r.get(f"{longest_window}_rounds_avg_offline"), float)
        ]
        if len(spot_values) > 5 and len(twap_values) > 5:
            assert statistics.pstdev(twap_values) < statistics.pstdev(spot_values), (
                "long-window Supernova TWAP should be smoother than spot price"
            )

        logger.info(
            "Supernova deterministic safe-price run complete | scenario=%s | csv=%s | png=%s | "
            "round_matches=%s | timestamp_matches=%s",
            scenario_path,
            csv_path,
            png_path if chart is not None else "skipped",
            runner.round_matches,
            runner.timestamp_matches,
        )
