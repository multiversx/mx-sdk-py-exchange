import csv
import sys
import time
from argparse import ArgumentParser
from multiversx_sdk_core import Address
from typing import List
from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes, string_to_hex, dec_to_padded_hex


NUM_BLOCKS_OBSERVED = 15000
SAMPLE_INTERVAL = 3.0
LOG_FILENAME = "dump/safe_price_observations.csv"

MODEL_SAMPLES = 100


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--file-suffix", required=False, default="")
    parser.add_argument("--view-contract", required=False, default="")
    parser.add_argument("--model-samples", required=False, type=int, nargs='+',
                        help='Number of round samples to use for offline models')
    args = parser.parse_args(cli_args)

    global LOG_FILENAME
    LOG_FILENAME = f"dump/safe_price_observations_{args.file_suffix}.csv"

    context = Context()
    pair_contract = context.get_pair_v2_contract(0)
    proxy = context.network_provider.proxy
    contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address, "erd"), proxy.url)
    if args.view_contract:
        view_data_fetcher = PairContractDataFetcher(Address(args.view_contract, "erd"), proxy.url)

    esdt_token_payment_schema = {
        'token_identifier': 'string',
        'token_nonce': 'u64',
        'amount': 'biguint',
    }
    zero_esdt_token_result = {
        'token_identifier': 'string',
        'token_nonce': 0,
        'amount': 0,
    }

    # add offline models
    offline_models = []
    if args.model_samples:
        for samples in args.model_samples:
            offline_models.append(OfflineModel(samples))

    csv_header = ["block", "safe_price", "spot_price"]
    if args.view_contract:
        csv_header.extend(["10min_avg_rounds", "20min_avg_timestamp"])
    for offline_model in offline_models:
        csv_header.append(f"{offline_model.avg_samples}_rounds_avg_offline")

    with open(LOG_FILENAME, 'w') as f:
        file_writer = csv.writer(f)
        file_writer.writerow(csv_header)

    i = NUM_BLOCKS_OBSERVED
    while i:
        query_start_time = time.time()
        reference_amount = 1 * 10 ** 18
        view_payload = f"000000{dec_to_padded_hex(len(string_to_hex(pair_contract.firstToken))//2)}" \
                       f"{string_to_hex(pair_contract.firstToken)}" \
                       f"0000000000000000" \
                       f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount))//2)}" \
                       f"{dec_to_padded_hex(reference_amount)}"
        hex_val = contract_data_fetcher.get_data("updateAndGetSafePrice",
                                                 [bytes.fromhex(view_payload)])
        print(f"Queried payload for updateAndGetSafePrice: {view_payload}")
        print(f"Result: {hex_val}")
        decoded_attrs: dict = zero_esdt_token_result
        if hex_val:
            decoded_attrs = decode_merged_attributes(hex_val, esdt_token_payment_schema)

        # args_payload = f"{string_to_hex(pair_contract.firstToken)}" \
        #                f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount)) // 2)}" \
        #                f"{dec_to_padded_hex(reference_amount)}"
        spot_price = contract_data_fetcher.get_data("getEquivalent",
                                                    [pair_contract.firstToken, reference_amount])
        last_block = proxy.get_network_status(1).current_round

        if args.view_contract:
            hex_val = view_data_fetcher.get_data("getSafePriceByRoundOffset",
                                                 [Address(pair_contract.address, "erd").pubkey, 100,
                                                  bytes.fromhex(view_payload)])
            ten_min_avg: dict = zero_esdt_token_result
            if hex_val:
                ten_min_avg = decode_merged_attributes(hex_val, esdt_token_payment_schema)

            hex_val = view_data_fetcher.get_data("getSafePriceByTimestampOffset",
                                                 [Address(pair_contract.address, "erd").pubkey, 600,
                                                  bytes.fromhex(view_payload)])
            ten_min_avg_2: dict = zero_esdt_token_result
            if hex_val:
                ten_min_avg_2 = decode_merged_attributes(hex_val, esdt_token_payment_schema)

            hex_val = view_data_fetcher.get_data("getSafePriceByTimestampOffset",
                                                 [Address(pair_contract.address, "erd").pubkey, 1200,
                                                  bytes.fromhex(view_payload)])
            twenty_min_avg: dict = zero_esdt_token_result
            if hex_val:
                twenty_min_avg = decode_merged_attributes(hex_val, esdt_token_payment_schema)

        print(f"Token: {decoded_attrs['token_identifier']} SAFE PRICE: {decoded_attrs['amount']}")
        print(f"Token: {decoded_attrs['token_identifier']} SPOT PRICE: {spot_price}")
        if args.view_contract:
            print(f"Token: {decoded_attrs['token_identifier']} 10MIN AVG ROUNDS: {ten_min_avg['amount']}")
            print(f"Token: {decoded_attrs['token_identifier']} 10MIN AVG TIMESTAMP: {ten_min_avg_2['amount']}")
            print(f"Token: {decoded_attrs['token_identifier']} 20MIN AVG TIMESTAMP: {twenty_min_avg['amount']}")

        for model in offline_models:
            model.add_observation(spot_price, last_block)
            print(f"Token: {decoded_attrs['token_identifier']} {model.avg_samples} AVG: {model.last_computed_price.price} ")

        with open(LOG_FILENAME, 'a') as f:
            file_writer = csv.writer(f)
            row_data = [last_block, decoded_attrs['amount'] / 10 ** 18, spot_price / 10 ** 18]
            if args.view_contract:
                row_data.extend([ten_min_avg['amount'] / 10 ** 18,
                                 twenty_min_avg['amount'] / 10 ** 18])
            for model in offline_models:
                row_data.append(model.last_computed_price.price / 10 ** 18)
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


if __name__ == "__main__":
    main(sys.argv[1:])
