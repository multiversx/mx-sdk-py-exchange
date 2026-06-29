"""
Tests for the safe-price oracle:

- exact cross-check of the on-chain TWAP view against reference_oracle.py.
- round-offset vs timestamp-offset equivalence.
- boundary inputs (offset=0 / offset>=current_round / start<oldest) are rejected.

Run:
    PYTHONPATH=. python -m pytest tests/integration/pair/test_safe_price_gaps.py -v
"""

import pytest
from multiversx_sdk import Address, AddressComputer

from tests.integration.pair.reference_oracle import SafePriceError
from tests.integration.pair.safe_price_helpers import (
    DEFAULT_INPUT_AMOUNT,
    TOLERANCE_PPM,
    build_recorded_observations,
    encode_payment,
    load_safe_price_abi,
    pick_same_shard_account,
    query_safe_price_by_offset,
    reserves,
    run_raw_view_query,
    safe_price_vs_reference,
    u64_top,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Alternating 0.1% swaps keep the pool stable while building 6 observations.
STABLE_DIRECTIONS = ["first", "second"] * 3


@pytest.mark.integration
@pytest.mark.pair
@pytest.mark.chainsim
class TestSafePriceReferenceCrossCheck:
    """the on-chain safe-price view must match the reference oracle exactly."""

    def _build(
        self,
        dex_context,
        pair_contract,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
        directions=STABLE_DIRECTIONS,
    ):
        swapper = pick_same_shard_account(
            dex_context, pair_contract.address, test_environment, network_providers
        )
        return build_recorded_observations(
            pair_contract,
            swapper,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
            directions,
        )

    def test_get_safe_price_matches_reference_oracle(
        self,
        dex_context,
        pair_contract,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        GIVEN a controlled, same-shard sequence of swaps
        WHEN  getSafePrice(start, end) is queried over the own observation window
        THEN  it equals the reference oracle exactly, both swap directions.
        """
        recorder, captured, _ = self._build(
            dex_context,
            pair_contract,
            test_environment,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
        )
        for input_is_first in (True, False):
            onchain, reference, start, end = safe_price_vs_reference(
                dex_context,
                network_providers,
                pair_contract,
                recorder,
                captured,
                input_is_first,
                DEFAULT_INPUT_AMOUNT,
            )
            logger.info(
                f"input_is_first={input_is_first} window=[{start},{end}] "
                f"onchain={onchain} reference={reference} diff={onchain - reference}"
            )

    def test_round_offset_equals_timestamp_offset(
        self,
        dex_context,
        pair_contract,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        getSafePriceByTimestampOffset(k*6) == getSafePriceByRoundOffset(k)
        (the contract converts ts->rounds via // SECONDS_PER_ROUND), and both equal the
        reference oracle (this also exercises the end>last-observation simulate branch).
        """
        from tests.integration.pair.reference_oracle import SafePriceView

        recorder, captured, pair_fetcher = self._build(
            dex_context,
            pair_contract,
            test_environment,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
        )
        view = SafePriceView(recorder)
        start_round = min(rnd for rnd, _ in captured)
        pair_shard = AddressComputer().get_shard_of_address(
            Address.new_from_bech32(pair_contract.address)
        )
        cur_round = network_providers.proxy.get_network_status(pair_shard).current_round
        cur = reserves(pair_fetcher)

        full = cur_round - start_round
        assert full >= 2, f"window too small: cur={cur_round} start={start_round}"

        for round_offset in sorted({max(1, full // 2), full}):
            for input_is_first in (True, False):
                token_id = pair_contract.firstToken if input_is_first else pair_contract.secondToken
                by_round = query_safe_price_by_offset(
                    dex_context,
                    network_providers,
                    pair_contract.address,
                    "getSafePriceByRoundOffset",
                    round_offset,
                    token_id,
                    DEFAULT_INPUT_AMOUNT,
                )
                by_ts = query_safe_price_by_offset(
                    dex_context,
                    network_providers,
                    pair_contract.address,
                    "getSafePriceByTimestampOffset",
                    round_offset * 6,
                    token_id,
                    DEFAULT_INPUT_AMOUNT,
                )
                if by_round is None or by_ts is None:
                    pytest.skip("offset views returned empty — is pairs_view loaded?")

                logger.info(
                    f"offset={round_offset} input_is_first={input_is_first} "
                    f"by_round={by_round['amount']} by_ts={by_ts['amount']}"
                )
                assert by_round["amount"] == by_ts["amount"], (
                    f"round/timestamp offset mismatch (offset={round_offset})"
                )
                assert by_round["amount"] > 0

                reference = view.get_safe_price_by_round_offset(
                    round_offset, DEFAULT_INPUT_AMOUNT, input_is_first, *cur, cur_round
                )
                tol = max(1, int(reference * TOLERANCE_PPM))
                assert abs(by_round["amount"] - reference) <= tol, (
                    f"offset vs reference mismatch (offset={round_offset}, "
                    f"input_is_first={input_is_first}): onchain={by_round['amount']} "
                    f"reference={reference}"
                )

    def test_offset_boundary_conditions_rejected(
        self,
        dex_context,
        pair_contract,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        boundary inputs must be rejected (the explicit endpoints do not clamp):
          - round_offset == 0                  -> 'Bad parameters'
          - round_offset >= current_round      -> 'Bad parameters'
          - start_round  <  oldest observation -> 'The price observation does not exist'
        On-chain queries must revert (return_code != "ok") and the reference oracle
        must raise SafePriceError for the same inputs.
        """
        from tests.integration.pair.reference_oracle import SafePriceView

        recorder, _, pair_fetcher = self._build(
            dex_context,
            pair_contract,
            test_environment,
            network_providers,
            blockchain_controller,
            ensure_esdt_amounts,
        )
        view = SafePriceView(recorder)
        cur = reserves(pair_fetcher)
        pair_shard = AddressComputer().get_shard_of_address(
            Address.new_from_bech32(pair_contract.address)
        )
        cur_round = network_providers.proxy.get_network_status(pair_shard).current_round

        abi = load_safe_price_abi()
        assert abi is not None, "safe-price-view ABI not found"
        pair_bytes = Address.new_from_bech32(pair_contract.address).get_public_key()
        payment = encode_payment(abi, pair_contract.firstToken, DEFAULT_INPUT_AMOUNT)

        def assert_rejected(label, function, args, ref_call):
            resp = run_raw_view_query(dex_context, network_providers, function, args)
            logger.info(f"{label}: return_code={resp.return_code!r} msg={resp.return_message!r}")
            assert resp.return_code != "ok", f"{label}: expected revert, got ok"
            with pytest.raises(SafePriceError):
                ref_call()

        assert_rejected(
            "offset=0",
            "getSafePriceByRoundOffset",
            [pair_bytes, u64_top(0), payment],
            lambda: view.get_safe_price_by_round_offset(
                0, DEFAULT_INPUT_AMOUNT, True, *cur, cur_round
            ),
        )
        big_offset = 10**9
        assert_rejected(
            "offset>=current_round",
            "getSafePriceByRoundOffset",
            [pair_bytes, u64_top(big_offset), payment],
            lambda: view.get_safe_price_by_round_offset(
                big_offset, DEFAULT_INPUT_AMOUNT, True, *cur, cur_round
            ),
        )
        assert_rejected(
            "start<oldest",
            "getSafePrice",
            [pair_bytes, u64_top(1), u64_top(2), payment],
            lambda: view.get_safe_price(1, 2, DEFAULT_INPUT_AMOUNT, True, *cur, cur_round),
        )
