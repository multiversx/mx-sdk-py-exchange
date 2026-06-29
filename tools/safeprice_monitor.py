import csv
import os
import time
import sys
import config
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from argparse import ArgumentParser
from multiversx_sdk import Address, SmartContractController
from multiversx_sdk.abi import TokenIdentifierValue, BigUIntValue, Abi
from typing import List, Optional, Any
from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes
from utils.logger import get_logger
from pathlib import Path
from contracts.pair_contract import PairContract

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NUM_BLOCKS_OBSERVED = 20000
SAMPLE_INTERVAL = 0.5
PROGRESS_INTERVAL = 100

DEFAULT_ABI_PATH = os.environ.get(
    "MX_SAFE_PRICE_ABI",
    str(config.HOME / "Personal/mx-exchange-sc/dex/pair/output/safe-price-view.abi.json"),
)

esdt_token_payment_schema = {
    'token_identifier': 'string',
    'token_nonce': 'u64',
    'amount': 'biguint',
}

zero_esdt_token_result = {
    'token_identifier': '',
    'token_nonce': 0,
    'amount': 0,
}


# ---------------------------------------------------------------------------
# Timebase enum
# ---------------------------------------------------------------------------

class Timebase(Enum):
    ROUND = "Round"
    TIMESTAMP = "Timestamp"


# ---------------------------------------------------------------------------
# Price sample primitives
# ---------------------------------------------------------------------------

class PriceSample:
    price: Optional[int]
    block_round: int

    def __init__(self, price: Optional[int], block_round: int):
        self.price = price
        self.block_round = block_round


# ---------------------------------------------------------------------------
# Offline models
# ---------------------------------------------------------------------------

class OfflineModel:
    observations: deque
    last_computed_price: PriceSample
    avg_samples: int
    _seen_rounds: set

    def __init__(self, samples: int):
        self.last_computed_price = PriceSample(None, 0)
        self.avg_samples = samples
        self.observations: deque = deque(maxlen=samples)
        self._seen_rounds: set = set()

    def add_observation(self, price: int, block_round: int) -> PriceSample:
        if block_round in self._seen_rounds:
            return self.last_computed_price

        if len(self.observations) == self.avg_samples:
            evicted = self.observations[0]
            self._seen_rounds.discard(evicted.block_round)

        self.observations.append(PriceSample(price, block_round))
        self._seen_rounds.add(block_round)
        self._compute_averaged_price()
        return self.last_computed_price

    def _compute_averaged_price(self):
        if len(self.observations) < self.avg_samples:
            # warmup: do not emit a fake average
            self.last_computed_price = PriceSample(None, self.observations[-1].block_round)
            return

        elapsed_rounds = self.observations[-1].block_round - self.observations[0].block_round
        sum_price = sum(o.price for o in self.observations)
        avg = sum_price // self.avg_samples
        self.last_computed_price = PriceSample(avg, self.observations[-1].block_round)
        logger.debug(
            f"OfflineModel({self.avg_samples}): elapsed={elapsed_rounds} rounds  avg={avg}"
        )


class UniswapV2Model:
    def __init__(self, observation_interval: int, observation_samples: int):
        self.observation_interval = observation_interval
        self.cumulative_price = 0
        self.last_round = 0
        self.observations: deque = deque(maxlen=observation_samples)
        self.last_observation_round = 0
        self.observation_samples = observation_samples

    def add_observation(self, price: int, block_round: int):
        if block_round - self.last_round > 0:
            self.cumulative_price += price * (block_round - self.last_round)
        self.last_round = block_round

        if block_round - self.last_observation_round >= self.observation_interval:
            self.observations.append(PriceSample(self.cumulative_price, block_round))
            self.last_observation_round = block_round

    def compute_averaged_price(self, avg_rounds: int) -> Optional[int]:
        if not self.observations:
            return None

        earliest_observation = None
        for observation in self.observations:
            if observation.block_round <= self.last_round - avg_rounds:
                earliest_observation = observation
                break

        if earliest_observation is None:
            earliest_observation = self.observations[0]

        time_elapsed = self.last_round - earliest_observation.block_round
        if not time_elapsed:
            return self.cumulative_price
        return (self.cumulative_price - earliest_observation.price) // time_elapsed


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _retry(fn, retries: int = 3, base_delay: float = 1.0):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            wait = base_delay * (2 ** attempt)
            logger.warning(f"Query failed (attempt {attempt + 1}/{retries}): {exc}. Retrying in {wait:.1f}s...")
            time.sleep(wait)
    raise last_exc


# ---------------------------------------------------------------------------
# MonitorSession: pre-built clients, resolved once before the loop
# ---------------------------------------------------------------------------

@dataclass
class MonitorSession:
    pair_contract: PairContract
    pair_fetcher: PairContractDataFetcher
    view_controller: SmartContractController
    safe_price_view_address: Address
    abi: Abi
    proxy: Any
    ms_per_round: int
    reference_amount: int
    input_token: str
    error_count: int = field(default=0)


# ---------------------------------------------------------------------------
# Query functions — all accept MonitorSession, build nothing internally
# ---------------------------------------------------------------------------

def get_safe_price_by_offset(
    session: MonitorSession,
    timebase: Timebase,
    offset: int,
) -> tuple[Optional[int], str]:
    def _query():
        endpoint = f"getSafePriceBy{timebase.value}Offset"
        query = session.view_controller.create_query(
            session.safe_price_view_address,
            endpoint,
            [session.pair_contract.address, offset, [session.input_token, 0, session.reference_amount]],
        )
        response = session.view_controller.run_query(query)
        if response:
            parsed = session.view_controller.parse_query_response(response)[0]
            return parsed.amount, parsed.token_identifier
        return None, ""

    try:
        return _retry(_query)
    except Exception as exc:
        logger.error(f"getSafePriceBy{timebase.value}Offset failed: {exc}")
        session.error_count += 1
        return None, ""


def get_lp_safe_price_by_offset(
    session: MonitorSession,
    timebase: Timebase,
    offset: int,
    lp_reference_amount: int,
) -> list[Any]:
    def _query():
        endpoint = f"getLpTokensSafePriceBy{timebase.value}Offset"
        query = session.view_controller.create_query(
            session.safe_price_view_address,
            endpoint,
            [session.pair_contract.address, offset, lp_reference_amount],
        )
        response = session.view_controller.run_query(query)
        if response:
            return session.view_controller.parse_query_response(response)
        return []

    try:
        return _retry(_query)
    except Exception as exc:
        logger.error(f"getLpTokensSafePriceBy{timebase.value}Offset failed: {exc}")
        session.error_count += 1
        return []


def get_safe_price_legacy(session: MonitorSession) -> tuple[Optional[int], str]:
    def _query():
        view_payload = session.abi.encode_custom_type(
            "EsdtTokenPayment", [session.input_token, 0, session.reference_amount]
        )
        hex_val = session.pair_fetcher.get_data(
            "updateAndGetSafePrice", [bytes.fromhex(view_payload)]
        )
        if hex_val:
            decoded = decode_merged_attributes(hex_val, esdt_token_payment_schema)
        else:
            decoded = zero_esdt_token_result
        return decoded['amount'], decoded['token_identifier']

    try:
        return _retry(_query)
    except Exception as exc:
        logger.error(f"updateAndGetSafePrice failed: {exc}")
        session.error_count += 1
        return None, ""


def get_spot_price(session: MonitorSession) -> tuple[Optional[int], str]:
    def _query():
        spot = session.pair_fetcher.get_data(
            "getEquivalent",
            [TokenIdentifierValue(session.input_token), BigUIntValue(session.reference_amount)],
        )
        other = (
            session.pair_contract.firstToken
            if session.input_token == session.pair_contract.secondToken
            else session.pair_contract.secondToken
        )
        return spot, other

    try:
        return _retry(_query)
    except Exception as exc:
        logger.error(f"getEquivalent failed: {exc}")
        session.error_count += 1
        return None, ""


# ---------------------------------------------------------------------------
# Token decimal auto-detection
# ---------------------------------------------------------------------------

def _resolve_token_decimals(proxy, token_id: str) -> int:
    try:
        token_data = proxy.get_definition_of_fungible_token(token_id)
        logger.info(f"Detected {token_data.decimals} decimals for {token_id}")
        return token_data.decimals
    except Exception as exc:
        logger.warning(
            f"Could not fetch decimals for {token_id}: {exc}. "
            f"Falling back to DEFAULT_TOKEN_DECIMALS={config.DEFAULT_TOKEN_DECIMALS}"
        )
        return config.DEFAULT_TOKEN_DECIMALS


def resolve_reference_amount(proxy, token_id: str) -> int:
    decimals = _resolve_token_decimals(proxy, token_id)
    logger.info(f"reference_amount = 10^{decimals} for {token_id}")
    return 10 ** decimals


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(cli_args: List[str]):
    parser = ArgumentParser(description="Safe price oracle monitoring tool")
    parser.add_argument("--file-suffix", required=False, default="")
    parser.add_argument("--view-contract", action="store_true", required=False, default=False,
                        help="Also query the on-chain SafePriceView contract (round + timestamp offset)")
    parser.add_argument("--model-samples", required=True, type=int, nargs='+',
                        help="One or more window sizes in rounds for offline and online models")
    parser.add_argument("--offline-models", action="store_true", required=False, default=False,
                        help="Enable OfflineModel columns")
    parser.add_argument("--uniswap-model", action="store_true", required=False, default=False,
                        help="Enable UniswapV2Model columns")
    parser.add_argument("--uniswap-interval", type=int, default=6,
                        help="Observation interval in rounds for UniswapV2Model (default: 6)")
    parser.add_argument("--uniswap-samples", type=int, default=60000,
                        help="Max stored snapshots for UniswapV2Model (default: 60000)")
    parser.add_argument("--lp-monitoring", action="store_true", required=False, default=False,
                        help="Enable LP token safe price columns (requires --view-contract)")
    parser.add_argument("--pair-index", type=int, default=1,
                        help="Index into the PAIRS_V2 contract list (default: 1)")
    parser.add_argument("--pair-address", type=str, default=None,
                        help="Bech32 pair address; overrides --pair-index when provided")
    parser.add_argument("--num-blocks", type=int, default=NUM_BLOCKS_OBSERVED,
                        help="Number of rounds to observe. 0 = run indefinitely (daemon mode)")
    parser.add_argument("--token", choices=["first", "second"], default="first",
                        help="Which token to use as the price input (default: first)")
    parser.add_argument("--reference-amount", type=int, default=None,
                        help="Raw integer reference amount. If omitted, auto-detected from token decimals")
    parser.add_argument("--abi-path", type=str, default=DEFAULT_ABI_PATH,
                        help="Path to the safe-price-view ABI JSON file")
    args = parser.parse_args(cli_args)

    log_filename = f"dump/safe_price_observations_{args.file_suffix}.csv" if args.file_suffix else "dump/safe_price_observations.csv"
    Path(log_filename).parent.mkdir(parents=True, exist_ok=True)

    context = Context()
    proxy = context.network_provider.proxy
    net_config = proxy.get_network_config()
    ms_per_round = net_config.round_duration
    chain_id = net_config.chain_id

    # Resolve pair contract
    if args.pair_address:
        pair_contract = PairContract.load_contract_by_address(args.pair_address)
    else:
        pair_contract = context.get_pair_v2_contract(args.pair_index)

    input_token = pair_contract.firstToken if args.token == "first" else pair_contract.secondToken

    # Resolve reference amount
    reference_amount = (
        args.reference_amount
        if args.reference_amount is not None
        else resolve_reference_amount(proxy, input_token)
    )

    # LP reference amount: LP tokens always 18 decimals on xExchange
    lp_reference_amount = 10 ** 18

    # Resolve output token decimals for correct CSV normalization
    output_token = pair_contract.secondToken if args.token == "first" else pair_contract.firstToken
    output_decimals = _resolve_token_decimals(proxy, output_token)

    # Build long-lived clients once
    abi = Abi.load(args.abi_path)
    safe_price_view_contract = context.get_contracts(config.PAIRS_VIEW)[0]
    view_controller = SmartContractController(chain_id, proxy, abi)
    pair_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), proxy.url)
    safe_price_view_address = Address.new_from_bech32(safe_price_view_contract.address)

    session = MonitorSession(
        pair_contract=pair_contract,
        pair_fetcher=pair_fetcher,
        view_controller=view_controller,
        safe_price_view_address=safe_price_view_address,
        abi=abi,
        proxy=proxy,
        ms_per_round=ms_per_round,
        reference_amount=reference_amount,
        input_token=input_token,
    )

    # Build models
    offline_models: List[OfflineModel] = []
    uniswap_models: List[UniswapV2Model] = []
    if args.offline_models:
        for samples in args.model_samples:
            offline_models.append(OfflineModel(samples))
    if args.uniswap_model:
        for samples in args.model_samples:
            uniswap_models.append(UniswapV2Model(args.uniswap_interval, args.uniswap_samples))

    # Build CSV header
    csv_header = ["block", "updateAndGetSafePrice", "spot_price"]
    if args.view_contract:
        for samples in args.model_samples:
            samples_to_timestamp = samples * ms_per_round // 1000
            csv_header.append(f"getSafePriceByRoundOffset({samples})")
            csv_header.append(f"getSafePriceByTimestampOffset({samples_to_timestamp})")
        if args.lp_monitoring:
            for samples in args.model_samples:
                samples_to_timestamp = samples * ms_per_round // 1000
                csv_header.append(f"getLpSafePriceByRoundOffset({samples})_token0")
                csv_header.append(f"getLpSafePriceByRoundOffset({samples})_token1")
                csv_header.append(f"getLpSafePriceByTimestampOffset({samples_to_timestamp})_token0")
                csv_header.append(f"getLpSafePriceByTimestampOffset({samples_to_timestamp})_token1")
    for offline_model in offline_models:
        csv_header.append(f"{offline_model.avg_samples}_rounds_avg_offline")
    for i, _ in enumerate(uniswap_models):
        csv_header.append(f"{args.model_samples[i]}_rounds_avg_uniswap")

    daemon_mode = args.num_blocks == 0
    total_samples = 0
    start_time = time.time()
    _norm = lambda v: v / 10 ** output_decimals if v is not None else None
    _norm_lp = lambda v: v / 10 ** 18 if v is not None else None

    logger.info(
        f"Starting safeprice monitor | pair={pair_contract.address} | "
        f"token={input_token} | ref_amount={reference_amount} | "
        f"output_token={output_token} | output_decimals={output_decimals} | "
        f"{'daemon mode' if daemon_mode else f'{args.num_blocks} blocks'}"
    )

    # Open CSV once for full run
    with open(log_filename, 'w', newline='') as csv_file:
        file_writer = csv.writer(csv_file)
        file_writer.writerow(csv_header)
        csv_file.flush()

        remaining = args.num_blocks
        try:
            while daemon_mode or remaining > 0:
                iteration_start = time.time()

                # B5: block number first — snapshot the round before any price queries
                last_block = proxy.get_network_status(1).current_round

                safe_price, other_token = get_safe_price_legacy(session)
                spot_price, _ = get_spot_price(session)

                logger.info(f"block={last_block}  spot={_norm(spot_price)}  legacy_safe={_norm(safe_price)}  {other_token}")

                online_averages = []
                lp_averages = []
                if args.view_contract:
                    for samples in args.model_samples:
                        samples_to_timestamp = samples * ms_per_round // 1000

                        round_price, _ = get_safe_price_by_offset(session, Timebase.ROUND, samples)
                        ts_price, _ = get_safe_price_by_offset(session, Timebase.TIMESTAMP, samples_to_timestamp)
                        online_averages.extend([round_price, ts_price])

                        logger.info(f"  roundOffset({samples})={_norm(round_price)}  tsOffset({samples_to_timestamp}s)={_norm(ts_price)}")

                        if args.lp_monitoring:
                            lp_round = get_lp_safe_price_by_offset(session, Timebase.ROUND, samples, lp_reference_amount)
                            lp_ts = get_lp_safe_price_by_offset(session, Timebase.TIMESTAMP, samples_to_timestamp, lp_reference_amount)
                            lp_averages.extend(_extract_lp_pair(lp_round) + _extract_lp_pair(lp_ts))

                for model in offline_models:
                    if spot_price is not None:
                        model.add_observation(spot_price, last_block)
                    logger.info(f"  offline({model.avg_samples})={_norm(model.last_computed_price.price)}")

                for model in uniswap_models:
                    if spot_price is not None:
                        model.add_observation(spot_price, last_block)

                # Write CSV row — None → empty cell
                row_data = [last_block, _norm(safe_price), _norm(spot_price)]
                if args.view_contract:
                    row_data.extend([_norm(v) for v in online_averages])
                    if args.lp_monitoring:
                        row_data.extend([_norm_lp(v) for v in lp_averages])
                for model in offline_models:
                    row_data.append(_norm(model.last_computed_price.price))
                for i, model in enumerate(uniswap_models):
                    avg = model.compute_averaged_price(args.model_samples[i])
                    row_data.append(_norm(avg) if avg is not None else None)

                file_writer.writerow(row_data)
                csv_file.flush()

                total_samples += 1
                if not daemon_mode:
                    remaining -= 1

                # Progress log every PROGRESS_INTERVAL iterations
                if total_samples % PROGRESS_INTERVAL == 0:
                    elapsed = time.time() - start_time
                    elapsed_str = _fmt_elapsed(elapsed)
                    if daemon_mode:
                        logger.info(
                            f"[progress] samples={total_samples}  elapsed={elapsed_str}  "
                            f"errors={session.error_count}  last_block={last_block}"
                        )
                    else:
                        done = args.num_blocks - remaining
                        logger.info(
                            f"[progress] {done}/{args.num_blocks}  elapsed={elapsed_str}  "
                            f"errors={session.error_count}  last_block={last_block}"
                        )

                elapsed_iter = time.time() - iteration_start
                time.sleep(max(0.0, SAMPLE_INTERVAL - elapsed_iter))

        except KeyboardInterrupt:
            logger.info("Interrupted by user.")
        finally:
            elapsed = time.time() - start_time
            logger.info(
                f"Monitor stopped. total_samples={total_samples}  errors={session.error_count}  "
                f"elapsed={_fmt_elapsed(elapsed)}  csv={log_filename}"
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_lp_pair(lp_results: list) -> list:
    if len(lp_results) >= 2:
        return [lp_results[0].amount, lp_results[1].amount]
    return [None, None]


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


if __name__ == "__main__":
    main(sys.argv[1:])
