import csv
from enum import Enum
import sys
import time
import config
from argparse import ArgumentParser
from multiversx_sdk import Address, SmartContractController
from multiversx_sdk.abi import AddressValue, U64Value, TokenIdentifierValue, BigUIntValue, Abi
from typing import List, Any
from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes, string_to_hex, dec_to_padded_hex
from pathlib import Path
from contracts.pair_contract import PairContract


NUM_BLOCKS_OBSERVED = 20000
SAMPLE_INTERVAL = 0.5
LOG_FILENAME = "dump/safe_price_observations.csv"
ABI_PATH = config.HOME / "Projects/dex/mx-exchange-sc/dex/pair/output/safe-price-view.abi.json"

MODEL_SAMPLES = 100

class Timebase(Enum):
    ROUND = "Round"
    TIMESTAMP = "Timestamp"

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


def get_safe_price_by_offset(timebase: Timebase, context: Context, abi: Abi, pair_contract: PairContract, offset: int, token: str, reference_amount: int) -> tuple[int, str, Any, Any]:
    """ Returns the amount and token identifier of the safe price of the given token at the given offset """
    safe_price_view_contract = context.get_contracts(config.PAIRS_VIEW)[0]
    view_controller = SmartContractController(context.network_provider.proxy.get_network_config().chain_id, context.network_provider.proxy, abi)
    
    endpoint = f"getSafePriceBy{timebase.value}Offset"
    query = view_controller.create_query(Address.new_from_bech32(safe_price_view_contract.address), endpoint, 
                                                 [pair_contract.address, offset, [token, 0, reference_amount]])
    response = view_controller.run_query(query)
    if response:
        payment, obs_start, obs_end = view_controller.parse_query_response(response)[0]
        return payment.amount, payment.token_identifier, obs_start, obs_end
    return 0, "", None, None


def get_lp_safe_price_by_offset(timebase: Timebase, context: Context, abi: Abi, pair_contract: PairContract, 
                                offset: int, reference_amount: int) -> list[Any]:
    """ Returns a list of namespaces containing the two tokens underlying the given lp reference amount.
        Each namespace contains:
        - token_identifier
        - nonce
        - amount"""
    safe_price_view_contract = context.get_contracts(config.PAIRS_VIEW)[0]
    view_controller = SmartContractController(context.network_provider.proxy.get_network_config().chain_id, context.network_provider.proxy, abi)
    
    endpoint = f"getLpTokensSafePriceBy{timebase.value}Offset"
    query = view_controller.create_query(Address.new_from_bech32(safe_price_view_contract.address), endpoint, 
                                                 [pair_contract.address, offset, reference_amount])
    response = view_controller.run_query(query)
    if response:
        return view_controller.parse_query_response(response)
    return []


def get_safe_price_legacy(context: Context, abi: Abi, pair_contract: PairContract, token: str, reference_amount: int) -> tuple[int, str]:
    contract_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), context.network_provider.proxy.url)

    # view_payload = f"000000{dec_to_padded_hex(len(string_to_hex(pair_contract.firstToken))//2)}" \
    #                f"{string_to_hex(pair_contract.firstToken)}" \
    #                f"0000000000000000" \
    #                f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount))//2)}" \
    #                f"{dec_to_padded_hex(reference_amount)}"
    view_payload_new = abi.encode_custom_type("EsdtTokenPayment", [token, 0, reference_amount])
    hex_val = contract_data_fetcher.get_data("updateAndGetSafePrice", [bytes.fromhex(view_payload_new)])

    decoded_attrs: dict = zero_esdt_token_result
    if hex_val:
        decoded_attrs = decode_merged_attributes(hex_val, esdt_token_payment_schema)

    return decoded_attrs['amount'], decoded_attrs['token_identifier']


def get_spot_price(context: Context, pair_contract: PairContract, token: str, reference_amount: int) -> tuple[int, str]:
    contract_data_fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), context.network_provider.proxy.url)
    # args_payload = f"{string_to_hex(pair_contract.firstToken)}" \
    #                f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount)) // 2)}" \
    #                f"{dec_to_padded_hex(reference_amount)}"
    spot_price = contract_data_fetcher.get_data("getEquivalent",
                                                    [TokenIdentifierValue(token),
                                                     BigUIntValue(reference_amount)])
    return spot_price, pair_contract.firstToken if token == pair_contract.secondToken else pair_contract.secondToken


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--file-suffix", required=False, default="")
    parser.add_argument("--view-contract", action="store_true", required=False, default=False)
    parser.add_argument("--model-samples", required=True, type=int, nargs='+',
                        help='Number of round samples to use for both online and offline models')
    parser.add_argument("--offline-models", action="store_true", required=False, default=False)
    parser.add_argument("--log-timing", action="store_true", required=False, default=False)
    args = parser.parse_args(cli_args)

    global LOG_FILENAME
    global LOG_FILENAME_TIMING
    LOG_FILENAME = f"dump/safe_price_observations_{args.file_suffix}.csv"
    LOG_FILENAME_TIMING = f"dump/safe_price_observations_timing_{args.file_suffix}.csv"

    if Path(LOG_FILENAME).parent.exists() is False:
        Path(LOG_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    if args.log_timing and Path(LOG_FILENAME_TIMING).parent.exists() is False:
        Path(LOG_FILENAME_TIMING).parent.mkdir(parents=True, exist_ok=True)

    context = Context()
    pair_contract = context.get_pair_v2_contract(0)
    proxy = context.network_provider.proxy
    ms_per_round = proxy.get_network_config().round_duration

    # add offline models
    offline_models: List[OfflineModel] = []
    uniswap_models: List[UniswapV2Model] = []
    if args.offline_models:
        for samples in args.model_samples:
            offline_models.append(OfflineModel(samples))

    # uniswap_models.append(UniswapV2Model(6, 60000))

    csv_header = ["block", "updateAndGetSafePrice", "spot_price"]
    csv_header_timing = ["block"]
    if args.view_contract:
        for samples in args.model_samples:
            samples_to_timestamp = samples * ms_per_round // 1000
            csv_header.append(f"getSafePriceByRoundOffset({samples})")
            csv_header.append(f"getSafePriceByTimestampOffset({samples_to_timestamp})")

            csv_header_timing.append(f"rnd_obs_start_rnd")
            csv_header_timing.append(f"rnd_obs_end_rnd")
            csv_header_timing.append(f"rnd_obs_start_ts")
            csv_header_timing.append(f"rnd_obs_end_ts")
            csv_header_timing.append(f"ts_obs_start_rnd")
            csv_header_timing.append(f"ts_obs_end_rnd")
            csv_header_timing.append(f"ts_obs_start_ts")
            csv_header_timing.append(f"ts_obs_end_ts")
    for offline_model in offline_models:
        csv_header.append(f"{offline_model.avg_samples}_rounds_avg_offline")
        if len(uniswap_models):
            csv_header.append(f"{offline_model.avg_samples}_rounds_avg_uniswap")

    with open(LOG_FILENAME, 'w') as f:
        file_writer = csv.writer(f)
        file_writer.writerow(csv_header)

    if args.log_timing:
        with open(LOG_FILENAME_TIMING, 'w') as f:
            file_writer = csv.writer(f)
            file_writer.writerow(csv_header_timing)

    abi = Abi.load(ABI_PATH)

    i = NUM_BLOCKS_OBSERVED
    while i:
        query_start_time = time.time()
        reference_amount = 1 * 10 ** 18
        
        safe_price, other_token = get_safe_price_legacy(context, abi, pair_contract, pair_contract.firstToken, reference_amount)
        spot_price, _ = get_spot_price(context, pair_contract, pair_contract.firstToken, reference_amount)
        last_block = proxy.get_network_status(1).current_round

        print(f"SPOT PRICE: {spot_price} {other_token}")
        print(f"Online legacy safe price: {safe_price} {other_token}")

        online_averages = []
        timing_data = []
        if args.view_contract:
            for samples in args.model_samples:
                samples_to_timestamp = samples * ms_per_round // 1000
                
                round_safe_price, _, rnd_obs_start, rnd_obs_end = get_safe_price_by_offset(Timebase.ROUND, context, abi, pair_contract, samples, pair_contract.firstToken, reference_amount)
                timestamp_safe_price, _, ts_obs_start, ts_obs_end = get_safe_price_by_offset(Timebase.TIMESTAMP, context, abi, pair_contract, samples_to_timestamp, pair_contract.firstToken, reference_amount)
                
                online_averages.extend([round_safe_price, timestamp_safe_price])
                timing_data.extend([rnd_obs_start.recording_round, rnd_obs_end.recording_round, 
                                    rnd_obs_start.recording_timestamp, rnd_obs_end.recording_timestamp, 
                                    ts_obs_start.recording_round, ts_obs_end.recording_round, 
                                    ts_obs_start.recording_timestamp, ts_obs_end.recording_timestamp])
                
                print(f"{samples} online round safe price: {round_safe_price} {other_token}")
                print(f"{samples_to_timestamp}s online timestamp safe price: {timestamp_safe_price} {other_token}")

        for model in offline_models:
            model.add_observation(spot_price, last_block)
            print(f"{model.avg_samples} offline round average: {model.last_computed_price.price} {other_token}")

        for model in uniswap_models:
            model.add_observation(spot_price, last_block)

        with open(LOG_FILENAME, 'a') as f:
            file_writer = csv.writer(f)
            row_data = [last_block, safe_price / 10 ** 18, spot_price / 10 ** 18]
            if args.view_contract:
                row_data.extend([average / 10 ** 18 for average in online_averages])
            for model in offline_models:
                row_data.append(model.last_computed_price.price / 10 ** 18)
                # also log the same averaging in case we use uniswap models
                for uniswap_model in uniswap_models:
                    row_data.append(uniswap_model.compute_averaged_price(model.avg_samples))
            file_writer.writerow(row_data)

        if args.log_timing:
            with open(LOG_FILENAME_TIMING, 'a') as f:
                file_writer = csv.writer(f)
                row_data = [last_block]
                if args.view_contract:
                    row_data.extend(timing_data)
                file_writer.writerow(row_data)

        query_time = time.time() - query_start_time
        time.sleep(max(0, SAMPLE_INTERVAL - query_time))
        i -= 1


class PriceSample:
    price: int
    round: int

    def __init__(self, price, round):
        self.price = price
        self.round = round


class OfflineModel:
    observations: List[PriceSample]
    last_computed_price: PriceSample
    avg_samples: int

    def __init__(self, samples: int):
        self.current_index = 0
        self.last_computed_price = PriceSample(0, 0)
        self.avg_samples = samples
        self.observations = []

    def add_observation(self, price, round) -> PriceSample:
        observation = PriceSample(price, round)

        if self.round_exists(observation.round):
            return self.last_computed_price

        if len(self.observations) == self.avg_samples:
            self.observations.pop(0)

        self.observations.append(observation)
        self.compute_averaged_price()

        return self.last_computed_price

    def round_exists(self, round: int):
        for observation in self.observations:
            if observation.round == round:
                return True
        return False

    def compute_averaged_price(self):
        if len(self.observations) != self.avg_samples:
            self.last_computed_price = self.observations[-1]
            return

        elapsed_rounds = self.observations[-1].round - self.observations[0].round
        sum_price = sum([observation.price for observation in self.observations])
        self.last_computed_price = PriceSample(sum_price // self.avg_samples, self.observations[-1].round)
        print(f"Elapsed rounds: {elapsed_rounds} Sum price: {sum_price} Avg price: {self.last_computed_price.price}"
              f"First round {self.observations[0].round} Last round {self.observations[-1].round}")
        

class UniswapV2Model:
    def __init__(self, observation_interval: int, observation_samples: int):
        self.observation_interval = observation_interval
        self.cumulative_price = 0
        self.last_round = 0
        self.observations: List[PriceSample] = []
        self.last_observation_round = 0
        self.observation_samples = observation_samples

    def add_observation(self, price: int, round: int):
        if round - self.last_round > 0:
            self.cumulative_price += price * (round - self.last_round)
        self.last_round = round

        if round - self.last_observation_round >= self.observation_interval:
            self.observations.append(PriceSample(self.cumulative_price, round))
            self.last_observation_round = round
            if len(self.observations) == self.observation_samples:
                self.observations.pop(0)

    def compute_averaged_price(self, avg_rounds: int):
        earliest_observation = 0
        for observation in self.observations:
            if observation.round <= self.last_round - avg_rounds:
                earliest_observation = observation
                break
        
        if not earliest_observation:
            earliest_observation = self.observations[0]

        time_elapsed = (self.last_round - earliest_observation.round)
        if not time_elapsed:
            return self.cumulative_price
        return (self.cumulative_price - earliest_observation.price) // time_elapsed

if __name__ == "__main__":
    main(sys.argv[1:])
