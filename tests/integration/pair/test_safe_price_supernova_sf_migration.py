"""Real shadowfork-state Safe Price migration check for Supernova.

This test intentionally preserves the Safe Price oracle storage loaded from the
shadowfork state. It upgrades the router/template/pair to the local Supernova
artifacts, advances chain simulator through the configured Supernova enable
round, then runs a deterministic 50-trade tape and writes scenario/CSV/PNG
outputs for inspection.

Use the same chain-simulator chronology and Supernova environment documented in
``test_safe_price_supernova_real_chronology.py``. This scenario requires the full
loaded safe-price ring, so do not set ``MX_CHAIN_SIM_IGNORE_STATE_CHRONOLOGY``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


if os.environ.get("MX_RUN_SUPERNOVA_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Supernova migration requires an isolated simulator and MX_RUN_SUPERNOVA_TESTS=1",
        allow_module_level=True,
    )
import requests
from multiversx_sdk import Address, AddressComputer

EXCHANGE_SC = Path(
    os.environ.get(
        "MX_EXCHANGE_SC_DIR",
        Path(__file__).resolve().parents[4] / "mx-exchange-sc",
    )
)
os.environ.setdefault("SUPERNOVA_WASM_DIR", str(EXCHANGE_SC / "dex/pair/output"))
os.environ.setdefault("SUPERNOVA_ROUTER_WASM", str(EXCHANGE_SC / "dex/router/output/router.wasm"))
os.environ.setdefault("MX_SAFE_PRICE_ABI", str(EXCHANGE_SC / "dex/pair/output/safe-price-view.abi.json"))

from tests.integration.pair import test_safe_price_supernova_long_running as lr
from tests.integration.pair.safe_price_helpers import pick_same_shard_account, reserves
from tests.integration.pair.test_safe_price_supernova_transition import (
    _current_observation,
    _price_observation_at_round,
)
from utils.contract_data_fetchers import PairContractDataFetcher

PAIR_TEMPLATE_ADDRESS_KEY = "706169725f74656d706c6174655f61646472657373"


def _configure_real_sf_run(monkeypatch) -> lr.SupernovaRunConfig:
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_TRADES", os.environ.get("SF_MIGRATION_SAFE_PRICE_TRADES", "50"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_ROUND_SAVE_INTERVAL", os.environ.get("SF_MIGRATION_SAVE_INTERVAL", "2"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_DEFAULT_OFFSET", os.environ.get("SF_MIGRATION_DEFAULT_OFFSET", "20"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_WINDOWS", os.environ.get("SF_MIGRATION_WINDOWS", "2,4,8"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_MIN_WAIT", os.environ.get("SF_MIGRATION_MIN_WAIT", "1"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_MAX_WAIT", os.environ.get("SF_MIGRATION_MAX_WAIT", "2"))
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_SPIKE_EVERY", os.environ.get("SF_MIGRATION_SPIKE_EVERY", "10"))
    if "SUPERNOVA_SAFE_PRICE_RUN_ID" not in os.environ:
        monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_RUN_ID", "sf_migration_no_reset")
    return lr.SupernovaRunConfig()



def _storage_value(proxy_url: str, address: str, key: str) -> str:
    response = requests.get(f"{proxy_url}/address/{address}/key/{key}", timeout=30)
    response.raise_for_status()
    value = response.json().get("data", {}).get("value", "")
    assert value != "", f"missing storage key {key} for {address}"
    return value


def _storage_u64(proxy_url: str, address: str, key: str) -> int:
    value = _storage_value(proxy_url, address, key)
    return int(value, 16) if value else 0


def _storage_address(proxy_url: str, address: str, key: str) -> str:
    return Address.from_hex(_storage_value(proxy_url, address, key), "erd").bech32()


def _ensure_template_has_code(proxy_url: str, template_address: str, source_pair_address: str) -> None:
    response = requests.get(f"{proxy_url}/address/{template_address}", timeout=30)
    if response.status_code == 200:
        account = response.json().get("data", {}).get("account", {})
        if account.get("code"):
            return

    source_response = requests.get(f"{proxy_url}/address/{source_pair_address}", timeout=30)
    source_response.raise_for_status()
    source_account = source_response.json().get("data", {}).get("account", {})
    assert source_account.get("code"), f"source pair {source_pair_address} has no bytecode in chainsim"

    payload = [
        {
            "address": template_address,
            "nonce": int(source_account.get("nonce") or 0),
            "balance": "0",
            "code": source_account["code"],
            "codeHash": source_account.get("codeHash", ""),
            "codeMetadata": source_account.get("codeMetadata", ""),
            "ownerAddress": source_account.get("ownerAddress", ""),
            "developerReward": "0",
        }
    ]
    response = requests.post(f"{proxy_url}/simulator/set-state", json=payload, timeout=30)
    response.raise_for_status()
    response = requests.post(f"{proxy_url}/simulator/generate-blocks/1", timeout=30)
    response.raise_for_status()


def _recursive_find_int(obj: Any, key_name: str) -> int | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == key_name:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
            nested = _recursive_find_int(value, key_name)
            if nested is not None:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _recursive_find_int(item, key_name)
            if nested is not None:
                return nested
    return None


def _supernova_enable_round(proxy, proxy_url: str) -> int:
    response = requests.get(f"{proxy_url}/network/enable-rounds", timeout=30)
    if response.status_code == 200:
        enable_round = _recursive_find_int(response.json(), "SupernovaEnableRound")
        if enable_round is not None:
            return enable_round

    configured_enable_round = os.environ.get("SF_SUPERNOVA_ENABLE_ROUND")
    if configured_enable_round is not None:
        return int(configured_enable_round)

    raw_config = proxy.get_network_config().raw
    rounds_per_epoch = int(raw_config.get("erd_rounds_per_epoch", 14400))
    enable_epoch = int(os.environ.get("SF_SUPERNOVA_ENABLE_EPOCH", "11"))
    return enable_epoch * rounds_per_epoch + 5


def _advance_past_supernova_enable(proxy, pair_address: str, proxy_url: str) -> int:
    enable_round = _supernova_enable_round(proxy, proxy_url)
    pair_shard = AddressComputer().get_shard_of_address(Address.new_from_bech32(pair_address))
    target_round = enable_round + 3
    while True:
        current_round = proxy.get_network_status(pair_shard).current_round
        if current_round >= target_round:
            break

        blocks = min(target_round - current_round, 250)
        response = requests.post(f"{proxy_url}/simulator/generate-blocks/{blocks}", timeout=240)
        response.raise_for_status()

    final_round = proxy.get_network_status(pair_shard).current_round
    assert final_round >= enable_round, (
        f"chain did not reach Supernova enable round: current={final_round}, enable={enable_round}"
    )
    return enable_round


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
@pytest.mark.slow
def test_loaded_shadowfork_safe_price_ring_migrates_through_supernova_without_reset(
    monkeypatch,
    dex_context,
    pair_contract,
    router_contract,
    deployer_account,
    test_environment,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
):
    if not test_environment.supports_time_control():
        pytest.skip("real SF migration check requires chain simulator")

    cfg = _configure_real_sf_run(monkeypatch)
    proxy = network_providers.proxy
    proxy_url = proxy.url
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy_url)

    observations_len = _storage_u64(proxy_url, pair_contract.address, lr.PRICE_OBSERVATIONS_LEN_KEY)
    index_before = _storage_u64(proxy_url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
    assert observations_len == 65_536, "refreshed SF state should contain a full Safe Price ring"
    assert index_before > 0, "refreshed SF state should contain existing Safe Price observations"

    # This is the important bit: preserve the full loaded price_observations ring.
    monkeypatch.setattr(lr, "_reset_pair_safe_price_storage", lambda *args, **kwargs: None)

    # The raw SF state contains the router template address, but the legacy/mainnet
    # bootstrap can make the post-upgrade helper view fail with "key not found".
    # Use the actual raw storage value and make sure the source template has code.
    template_address = _storage_address(proxy_url, router_contract.address, PAIR_TEMPLATE_ADDRESS_KEY)
    _ensure_template_has_code(proxy_url, template_address, pair_contract.address)
    monkeypatch.setattr(router_contract, "get_pair_template_address", lambda _proxy: template_address)

    lr._upgrade_supernova_safe_price_stack(
        dex_context,
        pair_contract,
        router_contract,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        cfg,
    )

    index_after_upgrade = _storage_u64(proxy_url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
    assert index_after_upgrade == index_before, "upgrade must not reset Safe Price current index"

    enable_round = _advance_past_supernova_enable(proxy, pair_contract.address, proxy_url)

    # The upgraded view must tolerate legacy/full-ring observations from SF state.
    legacy_observation = None
    current_round = proxy.get_network_status(
        AddressComputer().get_shard_of_address(Address.new_from_bech32(pair_contract.address))
    ).current_round
    for offset in (8, 20, 50, 100, 200, 600, 1200):
        if current_round <= offset:
            continue
        try:
            legacy_observation = _price_observation_at_round(
                dex_context, network_providers, pair_contract, current_round - offset
            )
            break
        except Exception:
            continue
    assert legacy_observation is not None, "upgraded view should read an existing loaded observation"

    swapper = pick_same_shard_account(dex_context, pair_contract.address, test_environment, network_providers)
    initial_reserves = reserves(fetcher)
    assert initial_reserves[0] > 0 and initial_reserves[1] > 0 and initial_reserves[2] > 0
    tape = lr._generate_trade_tape(cfg, pair_contract, initial_reserves)

    scenario_path = cfg.output_dir / f"{cfg.basename}.scenario.json"
    csv_path = cfg.output_dir / f"{cfg.basename}.csv"
    png_path = cfg.output_dir / f"{cfg.basename}.png"
    lr._write_scenario(scenario_path, cfg, pair_contract, tape)

    runner = lr._SupernovaLongRun(
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
    lr._generate_plot(
        csv_path,
        png_path,
        f"Safe Price — SF migration no reset ({len(runner.rows)} samples, Supernova round {enable_round})",
    )

    index_after_trades = _storage_u64(proxy_url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
    assert index_after_trades != index_before, "new observations should advance through the full loaded ring"

    current_observation = _current_observation(pair_contract, network_providers)
    assert current_observation["recording_round"] >= enable_round
    assert current_observation["recording_timestamp"] > 0
    assert current_observation["weight_accumulated"] > 0

    queried_current = _price_observation_at_round(
        dex_context,
        network_providers,
        pair_contract,
        current_observation["recording_round"],
    )
    assert queried_current["recording_timestamp"] == current_observation["recording_timestamp"]
    assert runner.timestamp_matches > 0
    assert scenario_path.exists()
    assert csv_path.exists()
    if png_path.exists():
        assert png_path.stat().st_size > 0
