import os
from pathlib import Path

import pytest


if os.environ.get("MX_RUN_SUPERNOVA_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Supernova transition requires an isolated simulator and MX_RUN_SUPERNOVA_TESTS=1",
        allow_module_level=True,
    )
import requests
from multiversx_sdk import Address

EXCHANGE_SC = Path(
    os.environ.get(
        "MX_EXCHANGE_SC_DIR",
        Path(__file__).resolve().parents[4] / "mx-exchange-sc",
    )
)
os.environ.setdefault("SUPERNOVA_WASM_DIR", str(EXCHANGE_SC / "dex/pair/output"))
os.environ.setdefault("SUPERNOVA_ROUTER_WASM", str(EXCHANGE_SC / "dex/router/output/router.wasm"))
os.environ.setdefault("MX_SAFE_PRICE_ABI", str(EXCHANGE_SC / "dex/pair/output/safe-price-view.abi.json"))

import config
from contracts.pair_contract import AddLiquidityEvent, SwapFixedInputEvent
from tests.integration.pair import test_safe_price_supernova_long_running as lr
from tests.integration.pair.safe_price_helpers import (
    _pair_bytes,
    pairs_view_fetcher,
    pick_same_shard_account,
    reserves,
    u64_top,
)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes, nominated_amount
from utils.utils_tx import ESDTToken, multi_esdt_transfer


PRICE_OBSERVATION_SCHEMA = {
    "first_token_reserve_accumulated": "biguint",
    "second_token_reserve_accumulated": "biguint",
    "weight_accumulated": "u64",
    "recording_round": "u64",
    "recording_timestamp": "u64",
    "lp_supply_accumulated": "biguint",
}
PRICE_OBSERVATIONS_ITEM_KEY = b"price_observations.item"
MAX_SAFE_PRICE_OBSERVATIONS = 65_536


def _configure_short_run(monkeypatch):
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_TRADES", "12")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_ROUND_SAVE_INTERVAL", "2")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_DEFAULT_OFFSET", "20")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_WINDOWS", "2,4,8")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_MIN_WAIT", "1")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_MAX_WAIT", "2")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_SPIKE_EVERY", "6")
    return lr.SupernovaRunConfig()


def _decode_observation(hex_value):
    if isinstance(hex_value, list):
        assert hex_value and hex_value[0], "empty observation response"
        hex_value = hex_value[0]
    assert hex_value, "empty observation response"
    return decode_merged_attributes(hex_value, PRICE_OBSERVATION_SCHEMA)


def _current_observation(pair_contract, network_providers):
    proxy_url = network_providers.proxy.url
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy_url)
    pending = fetcher.get_data("getCurrentPriceObservation")
    if pending and (not isinstance(pending, list) or pending[0]):
        return _decode_observation(pending)

    current_index = int(fetcher.get_data("getSafePriceCurrentIndex"))
    assert 1 <= current_index <= MAX_SAFE_PRICE_OBSERVATIONS, (
        f"invalid finalized safe-price index {current_index}"
    )
    storage_key = (PRICE_OBSERVATIONS_ITEM_KEY + current_index.to_bytes(4, "big")).hex()
    response = requests.get(
        f"{proxy_url}/address/{pair_contract.address}/key/{storage_key}",
        timeout=30,
    )
    response.raise_for_status()
    finalized = response.json().get("data", {}).get("value", "")
    assert finalized, f"missing finalized safe-price observation at index {current_index}"
    return _decode_observation(finalized)


def _price_observation_at_round(dex_context, network_providers, pair_contract, round_number):
    fetcher = pairs_view_fetcher(dex_context, network_providers)
    parts = fetcher.get_data(
        "getPriceObservation",
        [_pair_bytes(pair_contract.address), u64_top(round_number)],
    )
    return _decode_observation(parts)


def _find_existing_observation(dex_context, network_providers, pair_contract):
    current_round = network_providers.proxy.get_network_status().current_round
    for offset in (8, 20, 50, 100, 200, 600, 1200):
        if current_round <= offset:
            continue
        try:
            return _price_observation_at_round(dex_context, network_providers, pair_contract, current_round - offset)
        except Exception:
            continue
    raise AssertionError("could not query any existing safe-price observation from loaded state")


def _run_short_tape(
    cfg,
    dex_context,
    pair_contract,
    swapper,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    local_token_funder=None,
):
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
    initial_reserves = reserves(fetcher)
    assert initial_reserves[0] > 0 and initial_reserves[1] > 0 and initial_reserves[2] > 0
    tape = lr._generate_trade_tape(cfg, pair_contract, initial_reserves)
    runner = lr._SupernovaLongRun(
        cfg,
        dex_context,
        pair_contract,
        swapper,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    )
    if local_token_funder is not None:
        totals = {}
        for step in tape:
            totals[step.token_in] = totals.get(step.token_in, 0) + step.amount
        local_token_funder.sync_nonce(network_providers.proxy)
        tx_hash = multi_esdt_transfer(
            network_providers.proxy,
            10_000_000,
            local_token_funder,
            swapper.address,
            [
                ESDTToken(token_identifier, 0, amount * 2)
                for token_identifier, amount in totals.items()
            ],
        )
        lr._send_and_assert(
            tx_hash,
            blockchain_controller,
            network_providers.proxy,
            "fund isolated-pair trader",
        )
    runner.run(tape)
    assert len(runner.rows) == len(tape)
    assert runner.timestamp_matches > 0
    return runner


def _generate_legacy_observations_before_upgrade(
    pair_contract,
    swapper,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    trades=10,
):
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
    initial_reserves = reserves(fetcher)
    assert initial_reserves[0] > 0 and initial_reserves[1] > 0 and initial_reserves[2] > 0

    token_totals = {
        pair_contract.firstToken: initial_reserves[0] // 20,
        pair_contract.secondToken: initial_reserves[1] // 20,
    }
    ensure_esdt_amounts(swapper, token_totals)

    for index in range(trades):
        current_reserves = reserves(fetcher)
        first_to_second = index % 2 == 0
        if first_to_second:
            token_in = pair_contract.firstToken
            token_out = pair_contract.secondToken
            amount = max(current_reserves[0] // 2_000, 1)
        else:
            token_in = pair_contract.secondToken
            token_out = pair_contract.firstToken
            amount = max(current_reserves[1] // 2_000, 1)

        swapper.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(
            network_providers,
            swapper,
            SwapFixedInputEvent(token_in, amount, token_out, 1),
        )
        lr._send_and_assert(tx_hash, blockchain_controller, network_providers.proxy, "legacy pre-upgrade swap")
        blockchain_controller.wait_blocks(2)

    index = fetcher.get_data("getSafePriceCurrentIndex")
    assert index > 0, "pre-upgrade swaps should create legacy safe-price observations"
    return index


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
def test_loaded_legacy_observations_continue_after_supernova_upgrade(
    monkeypatch,
    dex_context,
    pair_contract,
    router_contract,
    deployer_account,
    test_environment,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    isolated_pair_factory,
):
    cfg = _configure_short_run(monkeypatch)
    lr._reset_pair_safe_price_storage(pair_contract.address, network_providers.proxy.url)
    legacy_swapper = pick_same_shard_account(
        dex_context, pair_contract.address, test_environment, network_providers
    )
    index_before = _generate_legacy_observations_before_upgrade(
        pair_contract,
        legacy_swapper,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    )

    monkeypatch.setattr(lr, "_reset_pair_safe_price_storage", lambda *args, **kwargs: None)

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

    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
    assert fetcher.get_data("getSafePriceCurrentIndex") == index_before

    old_observation = _find_existing_observation(dex_context, network_providers, pair_contract)
    assert old_observation["recording_timestamp"] > 0

    swapper = pick_same_shard_account(dex_context, pair_contract.address, test_environment, network_providers)
    _run_short_tape(
        cfg,
        dex_context,
        pair_contract,
        swapper,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    )

    index_after = fetcher.get_data("getSafePriceCurrentIndex")
    assert index_after != index_before
    current = _current_observation(pair_contract, network_providers)
    assert current["recording_timestamp"] >= old_observation["recording_timestamp"]
    assert current["weight_accumulated"] > old_observation["weight_accumulated"]

    queried_current = _price_observation_at_round(
        dex_context,
        network_providers,
        pair_contract,
        current["recording_round"],
    )
    assert queried_current["recording_timestamp"] == current["recording_timestamp"]

    liquidity = nominated_amount(1_000)
    new_pair, token_a, token_b = isolated_pair_factory(
        deployer_account,
        liquidity_amount=liquidity * 10,
    )
    deployer_account.sync_nonce(network_providers.proxy)
    tx_hash = new_pair.add_initial_liquidity(
        network_providers,
        deployer_account,
        AddLiquidityEvent(token_a, liquidity, 1, token_b, liquidity, 1),
    )
    lr._send_and_assert(
        tx_hash,
        blockchain_controller,
        network_providers.proxy,
        "new pair initial liquidity",
    )
    deployer_account.sync_nonce(network_providers.proxy)
    tx_hash = new_pair.resume(deployer_account, network_providers.proxy)
    lr._send_and_assert(
        tx_hash,
        blockchain_controller,
        network_providers.proxy,
        "new pair resume",
    )
    new_fetcher = PairContractDataFetcher(
        Address.new_from_bech32(new_pair.address), network_providers.proxy.url
    )
    assert new_fetcher.get_data("getSafePriceCurrentIndex") == 0

    new_swapper = pick_same_shard_account(
        dex_context, new_pair.address, test_environment, network_providers
    )
    new_runner = _run_short_tape(
        cfg,
        dex_context,
        new_pair,
        new_swapper,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        local_token_funder=deployer_account,
    )
    assert new_fetcher.get_data("getSafePriceCurrentIndex") > 0
    new_current = _current_observation(new_pair, network_providers)
    assert new_current["recording_timestamp"] > 0
    assert new_current["weight_accumulated"] > 0
    assert new_runner.timestamp_matches > 0
