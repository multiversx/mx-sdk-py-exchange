import sys
import time
import json
import config
from argparse import ArgumentParser
from typing import List
from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes, string_to_hex, dec_to_padded_hex
from utils.utils_chain import WrapperAddress, Account
from utils.utils_generic import log_step_fail, log_step_pass, log_warning
from tools.runners.account_state_runner import get_account_keys_online
from multiversx_sdk import ProxyNetworkProvider


SIMULATOR_URL = "http://localhost:8085"
GENERATE_BLOCKS_URL = f"{SIMULATOR_URL}/simulator/generate-blocks/"
SET_STATE_URL = f"{SIMULATOR_URL}/simulator/set-state"
SEND_USER_FUNDS_URL = f"{SIMULATOR_URL}/transaction/send-user-funds"
STATES_FOLDER = "states"


def get_retrieve_block(proxy: ProxyNetworkProvider, shard: int, block: int) -> int:
    block_number = block
    if block_number == 0:
        # get last block number
        response = proxy.get_network_status(shard)
        block_number = response.highest_final_nonce
    
    return block_number


def get_contract_retrieval_labels(contracts: str) -> List[str]:
    labels = []
    base_labels = [config.EGLD_WRAPS, config.LOCKED_ASSETS, config.SIMPLE_LOCKS_ENERGY, 
                  config.UNSTAKERS, config.FEES_COLLECTORS, config.ROUTER]
    if contracts == "base":
        return base_labels
    if contracts == "all":
        labels.extend(base_labels)
        labels.append(config.PROXIES, config.PROXIES_V2, config.PAIRS_V2, config.FARMS_V2, 
                      config.STAKINGS_V2, config.METASTAKINGS_V2,
                      config.STAKINGS_BOOSTED, config.METASTAKINGS_BOOSTED,
                      config.ESCROWS, config.LK_WRAPS,
                      config.POSITION_CREATOR, config.GOVERNANCES, 
                      config.PRICE_DISCOVERIES, config.SIMPLE_LOCKS)
        return labels
    else:
        return contracts.split(",")


def fetch_states(context: Context, args) -> json:
    proxy = ProxyNetworkProvider(args.gateway)
    contracts_shard = WrapperAddress(context.get_contracts(config.ROUTER)[0].address).get_shard()
    all_keys = list[dict]

    # if block is not empty, use it to retrieve all state from that specific block
    block_number = get_retrieve_block(proxy, contracts_shard, int(args.block)) if args.block else 0
    
    # get contracts state
    contract_labels = get_contract_retrieval_labels(args.contracts)
    for label in contract_labels:
        contracts = context.get_contracts(label)

        # if contract index is provided, retrieve only that contract state
        if args.contract_index:
            index = int(args.contract_index)
            if index >= len(contracts):
                log_step_fail(f"Contract index {index} is out of bounds for {label} contracts.")
                return
            contracts = [contracts[index]]

        # retrieve state for each contract
        for i, contract in enumerate(contracts):
            file = f"{STATES_FOLDER}/{block_number}_{label}_{i}_state.json"
            keys = get_account_keys_online(contract.address, proxy.url, block_number, file)
            all_keys.append(keys)

    # get system account state - done later since it's gigantic
    file = f"{STATES_FOLDER}/{block_number}_system_account_state.json"
    if args.system_account == "offline":
        with open(file, 'r', encoding="UTF-8") as state_reader:
            keys = json.load(state_reader)
    else:
        system_account_address = "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t"
        keys = get_account_keys_online(system_account_address, proxy.url, block_number,
                                        file)
        
    all_keys.append(keys)


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--gateway", required=False, default="")
    parser.add_argument("--block", required=False, default="") # 0 - frozen to last block, x - frozen to specific block number, empty - unfrozen
    parser.add_argument("--system-account", required=False, default="offline") # offline | online
    parser.add_argument("--contracts", required=False, default="") # all | base | comma separated labels of contracts 
    parser.add_argument("--contract-index", required=False, default="") # index of contract to retrieve state from; should only be used in conjunction with one specific type of --contracts
    args = parser.parse_args(cli_args)

    if not args.gateway:
        log_step_fail("Gateway is required. Please provide a gateway address.")
        return
    
    if args.contract_index:
        if not args.contracts:
            log_step_fail("Contract index provided but no contracts to retrieve from. Please provide a specific type of contracts.")
            return
        if args.contracts == "base" or args.contracts == "all":
            log_step_fail("Contract index provided but contracts to retrieve from are not specific. Please provide a specific type of contracts.")
            return
        if "," in args.contracts:
            log_step_fail("Contract index provided but multiple contracts to retrieve from. Please provide a single contract label.")
            return
    
    context = Context()

    fetch_states(context, args)
        

if __name__ == "__main__":
    main(sys.argv[1:])
