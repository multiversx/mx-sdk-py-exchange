"""
Shared helpers for the safe-price oracle integration tests
(test_safe_price.py and test_safe_price_gaps.py).

The safe-price VIEW endpoints (getSafePrice / getSafePriceBy*Offset /
getPriceObservation / getLpTokens*) live on the SEPARATE `pairs_view` contract
(the #[label("safe-price-view")] build target) and take the pair address as their
first argument — they are NOT on the pair contract (which only exposes
getSafePriceCurrentIndex and the legacy updateAndGetSafePrice). They must be
queried on the pairs_view address (which must be loaded onto the chain simulator,
e.g. `--contracts=...,pairs_view`), and the no-ABI data fetcher cannot serialize
mixed bytes+typed args, so every argument is passed as bytes.

Swaps that build observations MUST be same-shard as the pair, otherwise tx.round
(sender-shard inclusion) != the round update_safe_price executes in the pair's
shard, corrupting the replayed observation weights. The pair records PRE-swap
reserves (pair_actions/swap.rs), so build_recorded_observations replays the
reserves read just before each swap.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pytest
from multiversx_sdk import Address, AddressComputer, SmartContractController
from multiversx_sdk.abi import Abi, BigUIntValue, TokenIdentifierValue

import config
from contracts.pair_contract import SwapFixedInputEvent
from tests.helpers import TransactionAssertions
from tests.integration.pair.reference_oracle import SafePriceRecorder, SafePriceView
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.utils_chain import decode_merged_attributes, nominated_amount

logger = get_logger(__name__)

DEFAULT_INPUT_AMOUNT = 10**18  # 1 unit of an 18-decimal token (e.g. WEGLD)
TOLERANCE_PPM = 10**-6

ESDT_PAYMENT_SCHEMA = {"token_identifier": "string", "token_nonce": "u64", "amount": "biguint"}
# The deployed getPriceObservation returns 4 fields on the wire (no trailing
# lp_supply_accumulated); a 4-field schema decodes correctly regardless.
PRICE_OBSERVATION_SCHEMA = {
    "first_token_reserve_accumulated": "biguint",
    "second_token_reserve_accumulated": "biguint",
    "weight_accumulated": "u64",
    "recording_round": "u64",
}

_VENDORED_SAFE_PRICE_ABI = Path(__file__).parent / "abis" / "safe-price-view.abi.json"


# ---------------------------------------------------------------------------
# ABI + byte encoders
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_safe_price_abi():
    """Load the vendored safe-price-view ABI (for encoding EsdtTokenPayment).
    Override the path with MX_SAFE_PRICE_ABI. Returns None if missing."""
    override = os.environ.get("MX_SAFE_PRICE_ABI")
    abi_path = Path(override) if override else _VENDORED_SAFE_PRICE_ABI
    if not abi_path.exists():
        logger.warning(f"safe-price-view ABI not found at {abi_path}")
        return None
    return Abi.load(abi_path)


def u64_top(n: int) -> bytes:
    """Top-level u64 encoding: minimal big-endian, empty for 0."""
    return n.to_bytes(8, "big").lstrip(b"\x00")


def biguint_top(n: int) -> bytes:
    """Top-level biguint encoding: minimal big-endian, empty for 0."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def encode_payment(abi, token_id, amount) -> bytes:
    return bytes.fromhex(abi.encode_custom_type("EsdtTokenPayment", [token_id, 0, amount]))


# ---------------------------------------------------------------------------
# Reserves / spot
# ---------------------------------------------------------------------------


def reserves(fetcher) -> tuple[int, int, int]:
    """(first_reserve, second_reserve, lp_supply) from getReservesAndTotalSupply."""
    r = fetcher.get_data("getReservesAndTotalSupply")
    return int(r[0]), int(r[1]), int(r[2])


def spot_equivalent(fetcher, token_id, amount) -> int:
    """Pure reserve-ratio price (no fee) — what the safe price approximates."""
    return int(
        fetcher.get_data("getEquivalent", [TokenIdentifierValue(token_id), BigUIntValue(amount)])
    )


# ---------------------------------------------------------------------------
# pairs_view contract access + view queries (all-bytes args)
# ---------------------------------------------------------------------------


def pairs_view_address(dex_context):
    views = dex_context.get_contracts(config.PAIRS_VIEW)
    return views[0].address if views else None


def pairs_view_fetcher(dex_context, network_providers):
    addr = pairs_view_address(dex_context)
    if not addr:
        return None
    return PairContractDataFetcher(Address.new_from_bech32(addr), network_providers.proxy.url)


def _pair_bytes(pair_address) -> bytes:
    return Address.new_from_bech32(pair_address).get_public_key()


def query_safe_price(
    dex_context, network_providers, pair_address, start_round, end_round, token_id, amount
):
    """getSafePrice(pair, start, end, payment). Returns decoded dict or None."""
    view_fetcher = pairs_view_fetcher(dex_context, network_providers)
    abi = load_safe_price_abi()
    if view_fetcher is None or abi is None:
        return None
    hex_res = view_fetcher.get_data(
        "getSafePrice",
        [
            _pair_bytes(pair_address),
            u64_top(start_round),
            u64_top(end_round),
            encode_payment(abi, token_id, amount),
        ],
    )
    return decode_merged_attributes(hex_res, ESDT_PAYMENT_SCHEMA) if hex_res else None


def query_safe_price_by_offset(
    dex_context, network_providers, pair_address, endpoint, offset, token_id, amount
):
    """getSafePriceBy{Round,Timestamp}Offset(pair, offset, payment). Decoded dict or None."""
    view_fetcher = pairs_view_fetcher(dex_context, network_providers)
    abi = load_safe_price_abi()
    if view_fetcher is None or abi is None:
        return None
    hex_res = view_fetcher.get_data(
        endpoint,
        [_pair_bytes(pair_address), u64_top(offset), encode_payment(abi, token_id, amount)],
    )
    return decode_merged_attributes(hex_res, ESDT_PAYMENT_SCHEMA) if hex_res else None


def query_price_observation(dex_context, network_providers, pair_address, search_round):
    """getPriceObservation(pair, round). Decoded observation dict or None."""
    view_fetcher = pairs_view_fetcher(dex_context, network_providers)
    if view_fetcher is None:
        return None
    parts = view_fetcher.get_data(
        "getPriceObservation", [_pair_bytes(pair_address), u64_top(search_round)]
    )
    if not parts or not parts[0]:
        return None
    return decode_merged_attributes(parts[0], PRICE_OBSERVATION_SCHEMA)


def query_lp_safe_price_by_round_offset(
    dex_context, network_providers, pair_address, offset, lp_amount
):
    """getLpTokensSafePriceByRoundOffset(pair, offset, liquidity).
    Returns (first, second) decoded dicts or None."""
    view_fetcher = pairs_view_fetcher(dex_context, network_providers)
    if view_fetcher is None:
        return None
    parts = view_fetcher.get_data(
        "getLpTokensSafePriceByRoundOffset",
        [_pair_bytes(pair_address), u64_top(offset), biguint_top(lp_amount)],
    )
    if not parts or len(parts) < 2:
        return None
    return (
        decode_merged_attributes(parts[0], ESDT_PAYMENT_SCHEMA),
        decode_merged_attributes(parts[1], ESDT_PAYMENT_SCHEMA),
    )


def run_raw_view_query(dex_context, network_providers, function, args):
    """Run a pairs_view query and return the raw response (.return_code/.return_message),
    WITHOUT swallowing reverts — for asserting boundary conditions are rejected."""
    proxy = network_providers.proxy
    ctrl = SmartContractController(proxy.get_network_config().chain_id, proxy)
    query = ctrl.create_query(
        Address.new_from_bech32(pairs_view_address(dex_context)), function, args
    )
    return ctrl.run_query(query)


# ---------------------------------------------------------------------------
# Same-shard account + observation builder + reference cross-check
# ---------------------------------------------------------------------------


def pick_same_shard_account(dex_context, pair_address, test_environment, network_providers):
    """A test account in the pair's shard, funded with EGLD (chainsim). Same-shard is
    REQUIRED so tx.round == the round update_safe_price executes."""
    ac = AddressComputer()
    pair_shard = ac.get_shard_of_address(Address.new_from_bech32(pair_address))
    account = next(
        (
            a
            for a in dex_context.accounts.get_all()
            if ac.get_shard_of_address(a.address) == pair_shard
        ),
        None,
    )
    if account is None:
        pytest.skip(f"no test account available in the pair's shard ({pair_shard})")
    from tests.environments import ChainsimEnvironment

    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        test_environment.chain_sim.fund_users_w_egld(
            [account.address.to_bech32()], nominated_amount(100)
        )
    account.sync_nonce(network_providers.proxy)
    logger.info(f"swapper {account.address.to_bech32()} (shard {pair_shard})")
    return account


def build_recorded_observations(
    pair_contract,
    account,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts,
    directions,
    blocks_between=3,
    fraction=1000,
):
    """Perform same-shard swaps following `directions` (each 'first'|'second'), recording the
    PRE-swap reserves at each execution round into a SafePriceRecorder. `fraction` sets the
    swap size as 1/fraction of the input reserve. Returns (recorder, captured, fetcher) with
    captured = [(round, (f, s, lp))]."""
    proxy = network_providers.proxy
    fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy.url)
    r0 = reserves(fetcher)
    assert r0[0] > 0 and r0[1] > 0, "pool must have liquidity"
    ensure_esdt_amounts(
        account,
        {
            pair_contract.firstToken: r0[0] // 10,
            pair_contract.secondToken: r0[1] // 10,
        },
    )
    recorder = SafePriceRecorder()
    captured = []
    for i, direction in enumerate(directions):
        reserves_before = reserves(fetcher)
        if direction == "first":
            token_in, token_out, in_reserve = (
                pair_contract.firstToken,
                pair_contract.secondToken,
                reserves_before[0],
            )
        else:
            token_in, token_out, in_reserve = (
                pair_contract.secondToken,
                pair_contract.firstToken,
                reserves_before[1],
            )
        swap_amount = max(in_reserve // fraction, 1)
        account.sync_nonce(proxy)
        event = SwapFixedInputEvent(token_in, swap_amount, token_out, 1)
        tx = pair_contract.swap_fixed_input(network_providers, account, event)
        blockchain_controller.wait_for_tx(tx)
        TransactionAssertions.assert_transaction_success(tx, proxy)
        round = proxy.get_transaction(tx).round
        recorder.update_safe_price(
            reserves_before[0], reserves_before[1], reserves_before[2], round
        )
        captured.append((round, reserves_before))
        logger.info(
            f"swap {i + 1}/{len(directions)}: round={round} pre_reserves={reserves_before[0]},{reserves_before[1]}"
        )
        if blocks_between:
            blockchain_controller.wait_blocks(blocks_between)
    return recorder, captured, fetcher


def safe_price_vs_reference(
    dex_context,
    network_providers,
    pair_contract,
    recorder,
    captured,
    input_is_first,
    amount,
    window=None,
):
    """Query on-chain getSafePrice over an observation window (default: full own window) and
    assert it EQUALS the reference oracle (within rounding). Returns (onchain, reference, start, end)."""
    view = SafePriceView(recorder)
    rounds = sorted({rnd for rnd, _ in captured})
    assert len(rounds) >= 2, f"need >=2 distinct observation rounds, got {rounds}"
    start_round, end_round = window or (rounds[0], rounds[-1])
    token_id = pair_contract.firstToken if input_is_first else pair_contract.secondToken
    onchain = query_safe_price(
        dex_context,
        network_providers,
        pair_contract.address,
        start_round,
        end_round,
        token_id,
        amount,
    )
    if onchain is None:
        pytest.skip(
            "getSafePrice on pairs_view returned empty — is the pairs_view contract loaded?"
        )
    fetcher = PairContractDataFetcher(
        Address.new_from_bech32(pair_contract.address), network_providers.proxy.url
    )
    cur = reserves(fetcher)
    reference = view.get_safe_price(
        start_round, end_round, amount, input_is_first, *cur, current_round=rounds[-1]
    )
    tol = max(1, int(reference * TOLERANCE_PPM))
    assert abs(onchain["amount"] - reference) <= tol, (
        f"on-chain safe price {onchain['amount']} != reference {reference} (tol {tol})"
    )
    return onchain["amount"], reference, start_round, end_round
