"""Manual real-chronology Safe Price transition smoke.

Starts chain-sim from the refreshed SF chronology, does swaps before upgrade,
upgrades router/template/pair to local Supernova artifacts without resetting the
loaded Safe Price ring, does more swaps, advances to Supernova, then checks state
and swaps again.

Managed chain-simulator startup:
    MX_RUN_SUPERNOVA_TESTS=1 \
      MX_CHAIN_SIM_NODE_OVERRIDE_FILE=nodeOverride.supernova2169.toml \
      MX_CHAIN_SIM_ROUNDS_PER_EPOCH=14400 \
      MX_CHAIN_SIM_SUPERNOVA_ROUNDS_PER_EPOCH=144000 \
      MX_CHAIN_SIM_ROUND_DURATION=6000 \
      MX_CHAIN_SIM_SUPERNOVA_ROUND_DURATION=600 \
      PYTHONPATH=. python -m pytest \
      tests/integration/pair/test_safe_price_supernova_real_chronology.py \
      --env=chainsim --skip-farm-staking-state -q -s

For a manually built native simulator, start it with the equivalent chronology,
duration, and node-override arguments before running the same pytest command.
Do not add ``--reuse-chain-sim-state`` until that native process has already had
the state dump loaded once.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


if os.environ.get("MX_RUN_SUPERNOVA_TESTS", "").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Real Supernova chronology requires an isolated simulator and MX_RUN_SUPERNOVA_TESTS=1",
        allow_module_level=True,
    )
import requests
from multiversx_sdk import Address, AddressComputer
from multiversx_sdk.abi import BigUIntValue, TokenIdentifierValue

EXCHANGE_SC = Path(
    os.environ.get(
        "MX_EXCHANGE_SC_DIR",
        Path(__file__).resolve().parents[4] / "mx-exchange-sc",
    )
)
os.environ.setdefault("SUPERNOVA_WASM_DIR", str(EXCHANGE_SC / "dex/pair/output"))
os.environ.setdefault("SUPERNOVA_ROUTER_WASM", str(EXCHANGE_SC / "dex/router/output/router.wasm"))
os.environ.setdefault("MX_SAFE_PRICE_ABI", str(EXCHANGE_SC / "dex/pair/output/safe-price-view.abi.json"))

from contracts.pair_contract import AddLiquidityEvent, RemoveLiquidityEvent, SwapFixedInputEvent, SwapFixedOutputEvent
from tests.helpers import TransactionAssertions
from tests.integration.pair import test_safe_price_supernova_long_running as lr
from tests.integration.pair.safe_price_helpers import (
    ESDT_PAYMENT_SCHEMA,
    _pair_bytes,
    biguint_top,
    encode_payment,
    load_safe_price_abi,
    pick_same_shard_account,
    reserves,
    run_raw_view_query,
    u64_top,
)
from tests.integration.pair.test_safe_price_supernova_sf_migration import (
    PAIR_TEMPLATE_ADDRESS_KEY,
    _ensure_template_has_code,
    _storage_address,
    _supernova_enable_round,
)
from tests.integration.pair.test_safe_price_supernova_transition import _current_observation, _decode_observation
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes


OUTPUT_DIR = Path("tests/logs/safe_price_real_chronology_transition")
def _status(proxy, pair_address: str) -> dict:
    shard = AddressComputer().get_shard_of_address(Address.new_from_bech32(pair_address))
    status = proxy.get_network_status(shard)
    raw_status = {}
    try:
        response = requests.get(f"{proxy.url}/network/status/{shard}", timeout=30)
        response.raise_for_status()
        raw_status = response.json().get("data", {}).get("status", {})
    except Exception:
        raw_status = {}

    return {
        "shard": shard,
        "epoch": getattr(status, "epoch_number", status.current_epoch),
        "round": status.current_round,
        "nonce": getattr(status, "nonce", status.block_nonce),
        "timestamp": status.block_timestamp,
        "timestamp_ms": raw_status.get("erd_block_timestamp_ms"),
        "rounds_per_epoch": raw_status.get("erd_rounds_per_epoch"),
    }


def _storage_u64(proxy_url: str, address: str, key: str) -> int:
    response = requests.get(f"{proxy_url}/address/{address}/key/{key}", timeout=30)
    response.raise_for_status()
    value = response.json().get("data", {}).get("value", "")
    return int(value, 16) if value else 0


def _storage_value(proxy_url: str, address: str, key: str) -> str:
    response = requests.get(f"{proxy_url}/address/{address}/key/{key}", timeout=30)
    response.raise_for_status()
    return response.json().get("data", {}).get("value", "")


def _biguint_hex(value: int) -> str:
    return value.to_bytes((value.bit_length() + 7) // 8, "big").hex()


def _reserve_key(token_id: str) -> str:
    token_bytes = token_id.encode()
    return b"reserve".hex() + len(token_bytes).to_bytes(4, "big").hex() + token_bytes.hex()


def _token_balance(proxy_url: str, address: str, token_id: str) -> int:
    response = requests.get(f"{proxy_url}/address/{address}/esdt/{token_id}", timeout=30)
    response.raise_for_status()
    return int(response.json().get("data", {}).get("tokenData", {}).get("balance", "0"))


def _raw_pair_reserves(proxy_url: str, pair_contract) -> tuple[int, int, int]:
    first = _storage_value(proxy_url, pair_contract.address, _reserve_key(pair_contract.firstToken))
    second = _storage_value(proxy_url, pair_contract.address, _reserve_key(pair_contract.secondToken))
    lp_supply = _storage_value(proxy_url, pair_contract.address, "6c705f746f6b656e5f737570706c79")
    first_reserve = int(first, 16) if first else _token_balance(proxy_url, pair_contract.address, pair_contract.firstToken)
    second_reserve = int(second, 16) if second else _token_balance(
        proxy_url, pair_contract.address, pair_contract.secondToken
    )
    return first_reserve, second_reserve, int(lp_supply, 16) if lp_supply else 0


def _repair_missing_pair_reserve_storage(proxy_url: str, pair_contract, report: dict) -> None:
    repairs = []
    for token_id in (pair_contract.firstToken, pair_contract.secondToken):
        key = _reserve_key(token_id)
        if _storage_value(proxy_url, pair_contract.address, key):
            continue

        balance = _token_balance(proxy_url, pair_contract.address, token_id)
        assert balance > 0, f"cannot repair missing reserve({token_id}) without an ESDT balance"
        repairs.append({"token": token_id, "key": key, "value": balance})

    if not repairs:
        return

    response = requests.post(
        f"{proxy_url}/simulator/set-state",
        json=[
            {
                "address": pair_contract.address,
                "pairs": {repair["key"]: _biguint_hex(repair["value"]) for repair in repairs},
            }
        ],
        timeout=30,
    )
    response.raise_for_status()
    response = requests.post(f"{proxy_url}/simulator/generate-blocks/1", timeout=30)
    response.raise_for_status()
    report["reserve_storage_repairs"] = repairs


def _write_report(report: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))


def _current_observation_safe(pair_contract, network_providers) -> dict:
    try:
        return _current_observation(pair_contract, network_providers)
    except Exception:
        raw = _storage_value(
            network_providers.proxy.url,
            pair_contract.address,
            lr.CURRENT_PRICE_OBSERVATION_KEY,
        )
        return _decode_observation(raw)


def _run_basic_swaps(
    label: str,
    count: int,
    pair_contract,
    swapper,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
) -> list[dict]:
    proxy = network_providers.proxy
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy.url)
    try:
        initial_reserves = reserves(fetcher)
    except Exception:
        initial_reserves = _raw_pair_reserves(proxy.url, pair_contract)
    if len(initial_reserves) < 3:
        initial_reserves = _raw_pair_reserves(proxy.url, pair_contract)
    assert initial_reserves[0] > 0 and initial_reserves[1] > 0 and initial_reserves[2] > 0

    ensure_esdt_amounts(
        swapper,
        {
            pair_contract.firstToken: max(initial_reserves[0] // 500, 1),
            pair_contract.secondToken: max(initial_reserves[1] // 500, 1),
        },
    )

    rows = []
    for index in range(count):
        try:
            before = reserves(fetcher)
        except Exception:
            before = _raw_pair_reserves(proxy.url, pair_contract)
        if len(before) < 3:
            before = _raw_pair_reserves(proxy.url, pair_contract)
        first_to_second = index % 2 == 0
        if first_to_second:
            token_in = pair_contract.firstToken
            token_out = pair_contract.secondToken
            amount = max(before[0] // 10_000, 1)
        else:
            token_in = pair_contract.secondToken
            token_out = pair_contract.firstToken
            amount = max(before[1] // 10_000, 1)

        swapper.sync_nonce(proxy)
        tx_hash = pair_contract.swap_fixed_input(
            network_providers,
            swapper,
            SwapFixedInputEvent(token_in, amount, token_out, 1),
        )
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, proxy)
        blockchain_controller.wait_blocks(1)

        rows.append(
            {
                "label": label,
                "index": index,
                "tx": tx_hash,
                "token_in": token_in,
                "amount": amount,
                "status": _status(proxy, pair_contract.address),
                "safe_price_index": _storage_u64(
                    proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY
                ),
            }
        )
    return rows


def _decode_payment(hex_value: str) -> dict:
    assert hex_value, "empty ESDT payment response"
    return decode_merged_attributes(hex_value, ESDT_PAYMENT_SCHEMA)


def _view_parts(
    dex_context,
    network_providers,
    function: str,
    args: list[bytes],
    expected_parts: int = 1,
) -> list[str]:
    response = run_raw_view_query(dex_context, network_providers, function, args)
    code = str(getattr(response, "return_code", "ok")).lower()
    message = str(getattr(response, "return_message", ""))
    assert "ok" in code or "success" in code, f"{function} failed: {code} {message}"

    parts = [part.hex() for part in response.return_data_parts]
    assert len(parts) >= expected_parts, f"{function} returned {len(parts)} parts, expected {expected_parts}"
    assert all(part for part in parts[:expected_parts]), f"{function} returned an empty part"
    return parts


def _assert_view_rejects(
    dex_context,
    network_providers,
    function: str,
    args: list[bytes],
) -> str:
    try:
        response = run_raw_view_query(dex_context, network_providers, function, args)
    except Exception as exc:
        return str(exc)

    code = str(getattr(response, "return_code", "ok")).lower()
    message = str(getattr(response, "return_message", ""))
    assert not ("ok" in code or "success" in code), f"{function} unexpectedly succeeded"
    return message or code


def _assert_payment(payment: dict, expected_token: str) -> None:
    assert payment["token_identifier"] == expected_token
    assert payment["amount"] > 0


def _assert_lp_payments(parts: list[str], pair_contract) -> tuple[dict, dict]:
    first = _decode_payment(parts[0])
    second = _decode_payment(parts[1])
    _assert_payment(first, pair_contract.firstToken)
    _assert_payment(second, pair_contract.secondToken)
    return first, second


def _exercise_router_safe_price_config(
    router_contract,
    deployer_account,
    non_owner,
    network_providers,
    blockchain_controller,
    round_duration_ms: int,
) -> dict:
    proxy = network_providers.proxy
    original_interval = router_contract.get_safe_price_timestamp_save_interval(proxy)
    original_offset = router_contract.get_default_safe_price_timestamp_offset(proxy)
    assert original_interval > 0
    assert original_offset > 0

    updated_interval = original_interval + round_duration_ms
    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.set_safe_price_timestamp_save_interval(
        deployer_account, proxy, updated_interval
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    assert router_contract.get_safe_price_timestamp_save_interval(proxy) == updated_interval

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.set_safe_price_timestamp_save_interval(
        deployer_account, proxy, original_interval
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    assert router_contract.get_safe_price_timestamp_save_interval(proxy) == original_interval

    non_owner.sync_nonce(proxy)
    tx_hash = router_contract.set_default_safe_price_timestamp_offset(
        non_owner, proxy, original_offset + round_duration_ms
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_failed(tx_hash, proxy)
    assert router_contract.get_default_safe_price_timestamp_offset(proxy) == original_offset

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.set_safe_price_timestamp_save_interval(deployer_account, proxy, 0)
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_failed(tx_hash, proxy, "greater than 0")

    deployer_account.sync_nonce(proxy)
    tx_hash = router_contract.set_default_safe_price_timestamp_offset(deployer_account, proxy, 0)
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_failed(tx_hash, proxy, "greater than 0")

    return {
        "timestamp_save_interval_ms": original_interval,
        "default_timestamp_offset_ms": original_offset,
        "owner_update_checked": True,
        "non_owner_rejected": True,
        "zero_values_rejected": True,
    }


def _exercise_post_supernova_pair_mutations(
    pair_contract,
    swapper,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    supernova_enable_round: int,
) -> dict:
    proxy = network_providers.proxy
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy.url)

    first_reserve, second_reserve, _lp_supply = _raw_pair_reserves(proxy.url, pair_contract)
    add_first = max(first_reserve // 20_000, 1)
    add_second = max(second_reserve // 20_000, 1)
    ensure_esdt_amounts(
        swapper,
        {
            pair_contract.firstToken: add_first * 3,
            pair_contract.secondToken: add_second * 3,
        },
    )

    index_before = _storage_u64(proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)

    swapper.sync_nonce(proxy)
    tx_hash = pair_contract.add_liquidity(
        network_providers,
        swapper,
        AddLiquidityEvent(pair_contract.firstToken, add_first, 1, pair_contract.secondToken, add_second, 1),
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    blockchain_controller.wait_blocks(1)

    lp_balance = _token_balance(proxy.url, swapper.address.to_bech32(), pair_contract.lpToken)
    remove_amount = max(lp_balance // 4, 1)
    swapper.sync_nonce(proxy)
    tx_hash = pair_contract.remove_liquidity(
        network_providers,
        swapper,
        RemoveLiquidityEvent(remove_amount, pair_contract.firstToken, 1, pair_contract.secondToken, 1),
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    blockchain_controller.wait_blocks(1)

    _first_reserve, second_reserve, _lp_supply = _raw_pair_reserves(proxy.url, pair_contract)
    wanted_out = max(second_reserve // 100_000, 1)
    amount_in = fetcher.get_data(
        "getAmountIn",
        [TokenIdentifierValue(pair_contract.secondToken), BigUIntValue(wanted_out)],
    )
    max_in = max(amount_in * 2, 1)
    ensure_esdt_amounts(swapper, {pair_contract.firstToken: max_in})
    swapper.sync_nonce(proxy)
    tx_hash = pair_contract.swap_fixed_output(
        network_providers,
        swapper,
        SwapFixedOutputEvent(pair_contract.firstToken, max_in, pair_contract.secondToken, wanted_out),
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    blockchain_controller.wait_blocks(1)

    response = requests.post(f"{proxy.url}/simulator/generate-blocks/25", timeout=120)
    response.raise_for_status()
    first_reserve, _second_reserve, _lp_supply = _raw_pair_reserves(proxy.url, pair_contract)
    saved_swap_amount = max(first_reserve // 20_000, 1)
    ensure_esdt_amounts(swapper, {pair_contract.firstToken: saved_swap_amount})
    swapper.sync_nonce(proxy)
    tx_hash = pair_contract.swap_fixed_input(
        network_providers,
        swapper,
        SwapFixedInputEvent(pair_contract.firstToken, saved_swap_amount, pair_contract.secondToken, 1),
    )
    blockchain_controller.wait_for_tx(tx_hash)
    TransactionAssertions.assert_transaction_success(tx_hash, proxy)
    blockchain_controller.wait_blocks(1)

    index_after = _storage_u64(proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
    assert index_after != index_before
    current = _current_observation_safe(pair_contract, network_providers)
    assert current["recording_round"] >= supernova_enable_round
    assert current["recording_timestamp"] > 0

    return {
        "index_before": index_before,
        "index_after": index_after,
        "add_liquidity_checked": True,
        "remove_liquidity_checked": True,
        "swap_fixed_output_checked": True,
        "forced_saved_observation_checked": True,
        "current_observation_after_mutations": current,
    }


def _exercise_safe_price_surface(
    dex_context,
    pair_contract,
    network_providers,
    round_duration_ms: int,
) -> dict:
    abi = load_safe_price_abi()
    assert abi is not None, "safe-price-view ABI is required for surface coverage"

    proxy = network_providers.proxy
    status = _status(proxy, pair_contract.address)
    pair_arg = _pair_bytes(pair_contract.address)
    first_reserve, second_reserve, lp_supply = _raw_pair_reserves(proxy.url, pair_contract)
    assert first_reserve > 0 and second_reserve > 0 and lp_supply > 0

    first_amount = max(first_reserve // 100_000, 1)
    second_amount = max(second_reserve // 100_000, 1)
    lp_amount = max(lp_supply // 10_000, 1)
    round_offset = 2
    timestamp_offset = max(round_offset * round_duration_ms, 1)
    start_round = status["round"] - round_offset
    end_round = status["round"]

    first_payment = encode_payment(abi, pair_contract.firstToken, first_amount)
    second_payment = encode_payment(abi, pair_contract.secondToken, second_amount)

    safe_default = _decode_payment(
        _view_parts(
            dex_context,
            network_providers,
            "getSafePriceByDefaultOffset",
            [pair_arg, first_payment],
        )[0]
    )
    _assert_payment(safe_default, pair_contract.secondToken)

    safe_round = _decode_payment(
        _view_parts(
            dex_context,
            network_providers,
            "getSafePriceByRoundOffset",
            [pair_arg, u64_top(round_offset), first_payment],
        )[0]
    )
    _assert_payment(safe_round, pair_contract.secondToken)

    safe_round_reverse = _decode_payment(
        _view_parts(
            dex_context,
            network_providers,
            "getSafePriceByRoundOffset",
            [pair_arg, u64_top(round_offset), second_payment],
        )[0]
    )
    _assert_payment(safe_round_reverse, pair_contract.firstToken)

    safe_timestamp = _decode_payment(
        _view_parts(
            dex_context,
            network_providers,
            "getSafePriceByTimestampOffset",
            [pair_arg, u64_top(timestamp_offset), first_payment],
        )[0]
    )
    _assert_payment(safe_timestamp, pair_contract.secondToken)

    safe_range = _decode_payment(
        _view_parts(
            dex_context,
            network_providers,
            "getSafePrice",
            [pair_arg, u64_top(start_round), u64_top(end_round), first_payment],
        )[0]
    )
    _assert_payment(safe_range, pair_contract.secondToken)

    lp_default = _assert_lp_payments(
        _view_parts(
            dex_context,
            network_providers,
            "getLpTokensSafePriceByDefaultOffset",
            [pair_arg, biguint_top(lp_amount)],
            expected_parts=2,
        ),
        pair_contract,
    )
    lp_round = _assert_lp_payments(
        _view_parts(
            dex_context,
            network_providers,
            "getLpTokensSafePriceByRoundOffset",
            [pair_arg, u64_top(round_offset), biguint_top(lp_amount)],
            expected_parts=2,
        ),
        pair_contract,
    )
    lp_timestamp = _assert_lp_payments(
        _view_parts(
            dex_context,
            network_providers,
            "getLpTokensSafePriceByTimestampOffset",
            [pair_arg, u64_top(timestamp_offset), biguint_top(lp_amount)],
            expected_parts=2,
        ),
        pair_contract,
    )
    lp_range = _assert_lp_payments(
        _view_parts(
            dex_context,
            network_providers,
            "getLpTokensSafePrice",
            [pair_arg, u64_top(start_round), u64_top(end_round), biguint_top(lp_amount)],
            expected_parts=2,
        ),
        pair_contract,
    )

    pair_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy.url)
    current_index = pair_fetcher.get_data("getSafePriceCurrentIndex")
    current_observation = _current_observation(pair_contract, network_providers)
    assert current_index > 0
    assert current_observation["recording_timestamp"] > 0

    observation_parts = _view_parts(
        dex_context,
        network_providers,
        "getPriceObservation",
        [pair_arg, u64_top(current_observation["recording_round"])],
    )
    queried_observation = _decode_observation(observation_parts[0])
    assert queried_observation["recording_timestamp"] > 0

    legacy_safe = _decode_payment(pair_fetcher.get_data("updateAndGetSafePrice", [first_payment]))
    _assert_payment(legacy_safe, pair_contract.secondToken)
    legacy_lp = _assert_lp_payments(
        pair_fetcher.get_data(
            "updateAndGetTokensForGivenPositionWithSafePrice",
            [BigUIntValue(lp_amount)],
        ),
        pair_contract,
    )

    wrong_token = next(
        token
        for token in ("MEX-455c57", "USDC-c76f1f", "RIDE-7d18e9", "FOO-123456")
        if token not in (pair_contract.firstToken, pair_contract.secondToken)
    )
    rejected = {
        "same_round": _assert_view_rejects(
            dex_context,
            network_providers,
            "getSafePrice",
            [pair_arg, u64_top(end_round), u64_top(end_round), first_payment],
        ),
        "zero_round_offset": _assert_view_rejects(
            dex_context,
            network_providers,
            "getSafePriceByRoundOffset",
            [pair_arg, b"", first_payment],
        ),
        "zero_timestamp_offset": _assert_view_rejects(
            dex_context,
            network_providers,
            "getSafePriceByTimestampOffset",
            [pair_arg, b"", first_payment],
        ),
        "bad_input_token": _assert_view_rejects(
            dex_context,
            network_providers,
            "getSafePriceByRoundOffset",
            [pair_arg, u64_top(round_offset), encode_payment(abi, wrong_token, first_amount)],
        ),
    }

    return {
        "status": status,
        "round_offset": round_offset,
        "timestamp_offset_ms": timestamp_offset,
        "start_round": start_round,
        "end_round": end_round,
        "current_index": current_index,
        "current_observation": current_observation,
        "queried_observation": queried_observation,
        "safe_price_views_checked": {
            "getSafePriceByDefaultOffset": safe_default,
            "getSafePriceByRoundOffset": safe_round,
            "getSafePriceByTimestampOffset": safe_timestamp,
            "getSafePrice": safe_range,
            "reverse_direction": safe_round_reverse,
        },
        "lp_views_checked": {
            "getLpTokensSafePriceByDefaultOffset": lp_default,
            "getLpTokensSafePriceByRoundOffset": lp_round,
            "getLpTokensSafePriceByTimestampOffset": lp_timestamp,
            "getLpTokensSafePrice": lp_range,
        },
        "legacy_pair_endpoints_checked": {
            "updateAndGetSafePrice": legacy_safe,
            "updateAndGetTokensForGivenPositionWithSafePrice": legacy_lp,
        },
        "boundary_rejections": rejected,
    }


def _advance_to_supernova(
    proxy, pair_address: str, report: dict, supernova_enable_round: int
) -> None:
    shard = AddressComputer().get_shard_of_address(Address.new_from_bech32(pair_address))
    target_round = supernova_enable_round + 3
    while True:
        current_round = proxy.get_network_status(shard).current_round
        if current_round >= target_round:
            break

        blocks = min(target_round - current_round, 250)
        response = requests.post(f"{proxy.url}/simulator/generate-blocks/{blocks}", timeout=300)
        if response.status_code >= 400:
            report["advance_error"] = {
                "status_code": response.status_code,
                "text": response.text,
                "current_status": _status(proxy, pair_address),
                "target_round": target_round,
            }
            _write_report(report)
            response.raise_for_status()


def _assert_runtime_transition(
    start_status: dict,
    after_status: dict,
    activation_round: int,
    expected_pre_supernova_rounds_per_epoch: int,
    expected_post_supernova_rounds_per_epoch: int,
) -> None:
    assert start_status["round"] < activation_round
    assert start_status["rounds_per_epoch"] == expected_pre_supernova_rounds_per_epoch
    assert after_status["round"] >= activation_round
    assert after_status["epoch"] >= start_status["epoch"]
    assert after_status["rounds_per_epoch"] == expected_post_supernova_rounds_per_epoch


def _assert_post_supernova_measurements(
    measurements: list[dict],
    transition_epoch: int,
    rounds_per_epoch: int,
    expected_round_duration_ms: int,
) -> None:
    for row in measurements:
        assert row["epoch"] >= transition_epoch
        assert row["rounds_per_epoch"] == rounds_per_epoch
        assert row["delta_ms"] == expected_round_duration_ms


def _measure_post_supernova_round_duration(
    proxy,
    pair_address: str,
    transition_epoch: int,
    rounds_per_epoch: int,
    expected_round_duration_ms: int,
    samples: int = 6,
) -> list[dict]:
    rows = []
    for index in range(samples):
        before = _status(proxy, pair_address)
        response = requests.post(f"{proxy.url}/simulator/generate-blocks/1", timeout=120)
        response.raise_for_status()
        after = _status(proxy, pair_address)
        rows.append(
            {
                "index": index,
                "before_round": before["round"],
                "after_round": after["round"],
                "before_timestamp_ms": before["timestamp_ms"],
                "after_timestamp_ms": after["timestamp_ms"],
                "delta_ms": after["timestamp_ms"] - before["timestamp_ms"],
                "epoch": after["epoch"],
                "rounds_per_epoch": after["rounds_per_epoch"],
            }
        )

    _assert_post_supernova_measurements(
        rows,
        transition_epoch,
        rounds_per_epoch,
        expected_round_duration_ms,
    )

    return rows


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
@pytest.mark.slow
def test_real_chronology_upgrade_and_supernova_transition(
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
        pytest.skip("real chronology transition check requires chain simulator")

    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_TRADES", "4")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_ROUND_SAVE_INTERVAL", "2")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_DEFAULT_OFFSET", "20")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_WINDOWS", "2,4,8")
    monkeypatch.setenv("SUPERNOVA_SAFE_PRICE_RUN_ID", "real_chronology_transition")

    cfg = lr.SupernovaRunConfig()
    proxy = network_providers.proxy
    supernova_enable_round = _supernova_enable_round(proxy, proxy.url)
    start_status = _status(proxy, pair_contract.address)
    expected_pre_supernova_rounds_per_epoch = int(
        os.environ.get(
            "MX_CHAIN_SIM_ROUNDS_PER_EPOCH",
            start_status["rounds_per_epoch"],
        )
    )
    configured_post_supernova_rounds_per_epoch = os.environ.get(
        "MX_CHAIN_SIM_SUPERNOVA_ROUNDS_PER_EPOCH"
    )
    report = {
        "pair": pair_contract.address,
        "router": router_contract.address,
        "supernova_enable_round": supernova_enable_round,
        "start_status": start_status,
        "configured_rounds_per_epoch": {
            "pre_supernova": expected_pre_supernova_rounds_per_epoch,
            "post_supernova": (
                int(configured_post_supernova_rounds_per_epoch)
                if configured_post_supernova_rounds_per_epoch is not None
                else None
            ),
        },
        "events": [],
    }

    try:
        assert report["start_status"]["round"] < supernova_enable_round
        assert report["start_status"]["rounds_per_epoch"] > 0

        observations_len = _storage_u64(proxy.url, pair_contract.address, lr.PRICE_OBSERVATIONS_LEN_KEY)
        index_initial = _storage_u64(proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
        report["initial_storage"] = {
            "price_observations_len": observations_len,
            "safe_price_current_index": index_initial,
        }
        assert observations_len == 65_536
        assert index_initial > 0

        _repair_missing_pair_reserve_storage(proxy.url, pair_contract, report)

        swapper = pick_same_shard_account(dex_context, pair_contract.address, test_environment, network_providers)
        report["events"].extend(
            _run_basic_swaps(
                "pre_upgrade_legacy",
                2,
                pair_contract,
                swapper,
                network_providers,
                blockchain_controller,
                ensure_esdt_amounts,
            )
        )
        report["after_pre_upgrade_swaps"] = _status(proxy, pair_contract.address)
        index_before_upgrade = _storage_u64(
            proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY
        )
        report["before_upgrade_safe_price_current_index"] = index_before_upgrade

        # Preserve the loaded full ring. The test is about transition/migration, not reset behavior.
        monkeypatch.setattr(lr, "_reset_pair_safe_price_storage", lambda *args, **kwargs: None)

        template_address = _storage_address(proxy.url, router_contract.address, PAIR_TEMPLATE_ADDRESS_KEY)
        _ensure_template_has_code(proxy.url, template_address, pair_contract.address)
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

        index_after_upgrade = _storage_u64(proxy.url, pair_contract.address, lr.SAFE_PRICE_CURRENT_INDEX_KEY)
        report["after_upgrade"] = {
            "status": _status(proxy, pair_contract.address),
            "safe_price_current_index": index_after_upgrade,
        }
        assert index_after_upgrade == index_before_upgrade, (
            "Pair upgrade must preserve the safe-price ring-buffer index"
        )

        report["events"].extend(
            _run_basic_swaps(
                "post_upgrade_pre_supernova",
                2,
                pair_contract,
                swapper,
                network_providers,
                blockchain_controller,
                ensure_esdt_amounts,
            )
        )
        report["pre_supernova_current_observation"] = _current_observation_safe(pair_contract, network_providers)

        _advance_to_supernova(
            proxy,
            pair_contract.address,
            report,
            supernova_enable_round,
        )
        report["after_supernova_advance"] = _status(proxy, pair_contract.address)
        expected_post_supernova_rounds_per_epoch = (
            int(configured_post_supernova_rounds_per_epoch)
            if configured_post_supernova_rounds_per_epoch is not None
            else report["after_supernova_advance"]["rounds_per_epoch"]
        )
        _assert_runtime_transition(
            report["start_status"],
            report["after_supernova_advance"],
            supernova_enable_round,
            expected_pre_supernova_rounds_per_epoch,
            expected_post_supernova_rounds_per_epoch,
        )

        runtime_post_supernova_round_duration_ms = lr._round_duration_ms(network_providers)
        post_supernova_round_duration_ms = int(
            os.environ.get(
                "MX_CHAIN_SIM_SUPERNOVA_ROUND_DURATION",
                runtime_post_supernova_round_duration_ms,
            )
        )
        assert runtime_post_supernova_round_duration_ms == post_supernova_round_duration_ms

        report["post_supernova_round_duration_measurements"] = _measure_post_supernova_round_duration(
            proxy,
            pair_contract.address,
            transition_epoch=report["after_supernova_advance"]["epoch"],
            rounds_per_epoch=report["after_supernova_advance"]["rounds_per_epoch"],
            expected_round_duration_ms=post_supernova_round_duration_ms,
        )

        report["post_supernova_current_observation_before_swaps"] = _current_observation_safe(
            pair_contract, network_providers
        )
        assert report["post_supernova_current_observation_before_swaps"]["recording_timestamp"] > 0

        report["events"].extend(
            _run_basic_swaps(
                "post_supernova",
                2,
                pair_contract,
                swapper,
                network_providers,
                blockchain_controller,
                ensure_esdt_amounts,
            )
        )
        report["post_supernova_current_observation_after_swaps"] = _current_observation_safe(
            pair_contract, network_providers
        )
        assert (
            report["post_supernova_current_observation_after_swaps"]["recording_round"]
            >= supernova_enable_round
        )
        assert report["post_supernova_current_observation_after_swaps"]["recording_timestamp"] > 0

        report["router_safe_price_config"] = _exercise_router_safe_price_config(
            router_contract,
            deployer_account,
            swapper,
            network_providers,
            blockchain_controller,
            post_supernova_round_duration_ms,
        )
        report["post_supernova_pair_mutations"] = _exercise_post_supernova_pair_mutations(
            pair_contract,
            swapper,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
            supernova_enable_round,
        )
        report["safe_price_surface"] = _exercise_safe_price_surface(
            dex_context,
            pair_contract,
            network_providers,
            post_supernova_round_duration_ms,
        )
    finally:
        report["final_status"] = _status(proxy, pair_contract.address)
        _write_report(report)
