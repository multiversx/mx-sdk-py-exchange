import csv
import sys
import time
from typing import List

from utils.contract_data_fetchers import PairContractDataFetcher
from multiversx_sdk_cli.accounts import Address
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider
from utils.utils_chain import decode_merged_attributes

PROXY = "https://gateway.elrond.com"
PAIR_ADDRESS = "erd1qqqqqqqqqqqqqpgqav09xenkuqsdyeyy5evqyhuusvu4gl3t2jpss57g8x"
TOKEN_IN = "RIDE-7d18e9"
TOKEN_IN_REF_AMOUNT = "0de0b6b3a7640000"
NUM_BLOCKS_OBSERVED = 5000
SAMPLE_INTERVAL = 3
LOG_FILENAME = "arrows/stress/dex/results/safe_price_observations.csv"

MODEL_SAMPLES = 100


def main(cli_args: List[str]):
    contract_data_fetcher = PairContractDataFetcher(Address(PAIR_ADDRESS), PROXY)
    proxy = ProxyNetworkProvider(PROXY)

    esdt_token_payment_schema = {
        'token_type': 'u8',
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
        hex_val = contract_data_fetcher.get_data("updateAndGetSafePrice",
                                                 ["0x000000000b524944452d3764313865390000000000000000000000080de0b6b3a7640000"])
        decoded_attrs = decode_merged_attributes(hex_val, esdt_token_payment_schema)
        spot_price = contract_data_fetcher.get_data("getEquivalent",
                                                    ["0x" + TOKEN_IN.encode('utf-8').hex(), "0x" + TOKEN_IN_REF_AMOUNT])
        last_block = proxy.get_last_block_nonce(1)

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
