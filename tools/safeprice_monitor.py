import csv
import sys
import time
import config
from typing import List

from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from multiversx_sdk_cli.accounts import Address
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider
from utils.utils_chain import decode_merged_attributes, string_to_hex, dec_to_padded_hex


NUM_BLOCKS_OBSERVED = 5000
SAMPLE_INTERVAL = 3
LOG_FILENAME = "dump/safe_price_observations.csv"

MODEL_SAMPLES = 100


def main(cli_args: List[str]):
    context = Context()
    pair_contract = context.get_pair_v2_contract(0)
    proxy = context.network_provider.proxy
    contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), proxy.url)

    esdt_token_payment_schema = {
        'token_identifier': 'string',
        'token_nonce': 'u64',
        'amount': 'biguint',
    }

    csv_header = ["block", "safe_price", "spot_price"]
    with open(LOG_FILENAME, 'w') as f:
        file_writer = csv.writer(f)
        file_writer.writerow(csv_header)

    i = NUM_BLOCKS_OBSERVED
    while i:
        reference_amount = 1 * 10 ** 18
        view_payload = f"000000{dec_to_padded_hex(len(string_to_hex(pair_contract.firstToken))//2)}" \
                       f"{string_to_hex(pair_contract.firstToken)}" \
                       f"0000000000000000" \
                       f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount))//2)}" \
                       f"{dec_to_padded_hex(reference_amount)}"
        hex_val = contract_data_fetcher.get_data("updateAndGetSafePrice",
                                                 [bytes.fromhex(view_payload)])
        print(view_payload)
        print(hex_val)
        decoded_attrs = decode_merged_attributes(hex_val, esdt_token_payment_schema)
        args_payload = f"{string_to_hex(pair_contract.firstToken)}" \
                       f"000000{dec_to_padded_hex(len(dec_to_padded_hex(reference_amount)) // 2)}" \
                       f"{dec_to_padded_hex(reference_amount)}"
        spot_price = contract_data_fetcher.get_data("getEquivalent",
                                                    [bytes.fromhex(args_payload)])
        last_block = proxy.get_network_status(1).nonce

        print(f"Token: {decoded_attrs['token_identifier']} SAFE PRICE: {decoded_attrs['amount']}")
        print(f"Token: {decoded_attrs['token_identifier']} SPOT PRICE: {spot_price}")

        with open(LOG_FILENAME, 'a') as f:
            file_writer = csv.writer(f)
            file_writer.writerow([last_block, decoded_attrs['amount'], spot_price])

        time.sleep(SAMPLE_INTERVAL)
        i -= 1


class PriceSample:
    price: int
    block: int

    def __init__(self, price, block):
        self.price = price
        self.block = block


class OfflineModel:
    observations: List[PriceSample]
    current_index: int
    last_computed_price: PriceSample

    def __init__(self):
        self.current_index = 0
        self.last_computed_price = PriceSample(0, 0)

    def add_observation(self, price, block):
        observation = PriceSample(price, block)

        if self.current_index == MODEL_SAMPLES:
            self.observations.pop(0)
        else:
            self.current_index += 1

        self.observations.append(observation)

    def compute_averaged_price(self):
        for observation in self.observations:
            elapsed_blocks = observation.block - self.last_computed_price.block
            #TODO: finish math here


if __name__ == "__main__":
    main(sys.argv[1:])
