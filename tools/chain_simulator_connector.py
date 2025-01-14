import sys
import time
import json
import config
from argparse import ArgumentParser
from typing import Any, List
from context import Context
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_chain import decode_merged_attributes, get_current_tokens_for_address, string_to_hex, dec_to_padded_hex
from utils.utils_chain import WrapperAddress, Account
from utils.logger import get_logger
from utils.utils_generic import log_step_fail, log_step_pass, log_warning
from tools.runners.account_state_runner import get_account_keys_online, get_account_data_online
from multiversx_sdk import ProxyNetworkProvider

from utils.utils_tx import ESDTToken


logger = get_logger(__name__)


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


def get_current_shard_chronology(proxy: ProxyNetworkProvider, shard: int) -> dict:
    # returns current epoch, round, block 
    # TODO: not sure if timestamp is necessary as well
    response = proxy.get_network_status()
    response_dict = {
        "epoch": response.epoch_number,
        "round": response.current_round,
        "block": response.highest_final_nonce
    }

    return response_dict


def get_contract_retrieval_labels(contracts: str) -> List[str]:
    labels = []
    base_labels = [config.EGLD_WRAPS, config.LOCKED_ASSETS, config.SIMPLE_LOCKS_ENERGY, 
                  config.UNSTAKERS, config.FEES_COLLECTORS, config.ROUTER]
    if contracts == "base":
        return base_labels
    if contracts == "all":
        labels.extend(base_labels)
        labels.extend([config.PROXIES, config.PROXIES_V2, config.PAIRS_V2, config.FARMS_V2, 
                      config.STAKINGS_V2, config.METASTAKINGS_V2,
                      config.STAKINGS_BOOSTED, config.METASTAKINGS_BOOSTED,
                      config.ESCROWS, config.LK_WRAPS,
                      config.POSITION_CREATOR, config.GOVERNANCES, 
                      config.PRICE_DISCOVERIES, config.SIMPLE_LOCKS])
        return labels
    else:
        return contracts.split(",")
    

def get_context_used_tokens(context: Context) -> List[str]:
    contract_tokens = []
    for contract_label in context.deploy_structure.contracts:
        for contract in context.get_contracts(contract_label):
            contract_tokens.extend(contract.get_contract_tokens())
    return contract_tokens


def fetch_account_state(address: str, proxy: ProxyNetworkProvider, block_number: int,
                        file_label: str, file_index: int) -> dict[str, Any]:
    keys_file = f"{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_state.json"
    data_file = f"{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_data.json"
    chain_config_file = f"{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_chain_config_state.json"
    keys = get_account_keys_online(address, proxy.url, block_number, keys_file)
    data = get_account_data_online(address, proxy.url, block_number, data_file)

    account_state = {}
    account_state.update(data)
    account_state['keys'] = keys 

    # save account chain config state to file
    with open(chain_config_file, 'w', encoding="UTF-8") as state_writer:
        json.dump(account_state, state_writer, indent=4)
    logger.info(f"Chain config account state for {address} has been saved to {chain_config_file}.")

    return account_state


def get_token_key_hex(token: ESDTToken) -> str:
    return f"{string_to_hex('ELRONDesdt')}{string_to_hex(token.token_id)}{token.get_token_nonce_hex()}"


def fetch_token_system_account_attributes(proxy: ProxyNetworkProvider, token: ESDTToken, block_number: int = 0) -> dict[str, str]:
    block_param = f"?blockNonce={block_number}" if block_number else ""
    key = get_token_key_hex(token)
    resource_url = f"address/erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t/key/{key}{block_param}"
    response = proxy.do_get_generic(resource_url)
    return {key: response.get("value", "")}


def fetch_context_system_account_keys_from_account(proxy: ProxyNetworkProvider, context: Context, address: str, block_number: int = 0) -> dict[str, Any]:
    sys_account_keys = {}

    context_tokens = get_context_used_tokens(context)
    user_tokens = proxy.get_nonfungible_tokens_of_account(WrapperAddress(address))
    for token in user_tokens:
        if not token.collection in context_tokens:
            continue
        sys_account_token_attributes = fetch_token_system_account_attributes(proxy, ESDTToken.from_non_fungible_on_network(token), block_number)
        sys_account_keys.update(sys_account_token_attributes)

    sys_account_state = {
        "address": "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t",
        "keys": sys_account_keys
    }

    # save system account state to file
    sys_account_state_file = f"{STATES_FOLDER}/{block_number}_system_account_state_{address}.json"
    with open(sys_account_state_file, 'w', encoding="UTF-8") as state_writer:
        json.dump(sys_account_state, state_writer, indent=4)
    logger.info(f"System account state for tokens in {address} has been saved to {sys_account_state_file}.")

    return sys_account_state


def fetch_contract_states(context: Context, args) -> dict[str, Any]:
    proxy = ProxyNetworkProvider(args.gateway)
    contracts_shard = WrapperAddress(context.get_contracts(config.ROUTER_V2)[0].address).get_shard()
    all_keys: list[dict] = []

    # if block is not empty, use it to retrieve all state from that specific block
    block_number = get_retrieve_block(proxy, contracts_shard, int(args.block)) if args.block else 0
    
    # get contracts state
    contract_labels = get_contract_retrieval_labels(args.contracts)
    for label in contract_labels:
        logger.info(f"Retrieving {label} contracts state.")
        contracts = context.get_contracts(label)

        # if contract index is provided, retrieve only that contract state
        if args.contract_index:
            index = int(args.contract_index)
            if index >= len(contracts):
                log_step_fail(f"Contract index {index} is out of bounds for {label} contracts.")
                return []
            contracts = [contracts[index]]

        # retrieve keys and data for each contract
        for i, contract in enumerate(contracts):
            logger.info(f"Retrieving state for {label} contract {i + 1}/{len(contracts)}.")
            account_state = fetch_account_state(contract.address, proxy, block_number, label, i)
            all_keys.append(account_state)

    # dump all keys to a file
    all_keys_file = f"{STATES_FOLDER}/{block_number}_{args.contracts}_all_keys.json"
    with open(all_keys_file, 'w', encoding="UTF-8") as state_writer:
        json.dump(all_keys, state_writer, indent=4)
    logger.info(f"State for {args.contracts} contracts has been retrieved and saved to {all_keys_file}.")

    chronology = get_current_shard_chronology(proxy, contracts_shard)
    logger.info(f"Current shard chronology: {chronology}")
    # save chronology to file
    chronology_file = f"{STATES_FOLDER}/{block_number}_shard_chronology.json"
    with open(chronology_file, 'w', encoding="UTF-8") as chronology_writer:
        json.dump(chronology, chronology_writer, indent=4)
    logger.info(f"Shard chronology has been saved to {chronology_file}.")

    return all_keys
    
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


def fetch_user_state_with_tokens(user_address: str, context: Context, args) -> dict[str, Any]:
    proxy = ProxyNetworkProvider(args.gateway)
    address = WrapperAddress(user_address)
    account_shard = address.get_shard()
    # if block is not empty, use it to retrieve all state from that specific block
    block_number = get_retrieve_block(proxy, account_shard, int(args.block)) if args.block else 0

    # get user account state
    _ = fetch_account_state(address.bech32(), proxy, block_number, user_address, 0)

    # compose system account token attributes
    _ = fetch_context_system_account_keys_from_account(proxy, context, address.bech32(), block_number)


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--gateway", required=False, default="")
    parser.add_argument("--block", required=False, default="") # 0 - frozen to last block, x - frozen to specific block number, empty - unfrozen
    parser.add_argument("--system-account", required=False, default="offline") # offline | online
    parser.add_argument("--contracts", required=False, default="") # all | base | comma separated labels of contracts 
    parser.add_argument("--contract-index", required=False, default="") # index of contract to retrieve state from; should only be used in conjunction with one specific type of --contracts
    parser.add_argument("--account", required=False, default="") # explicit account address to retrieve state from 
    args = parser.parse_args(cli_args)

    if not args.gateway:
        log_step_fail("Gateway is required. Please provide a gateway address.")
        return
    
    context = Context()
    
    if args.contracts:
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
            
        fetch_contract_states(context, args)
    
    if args.account:
        fetch_user_state_with_tokens(args.account, context, args)
        

if __name__ == "__main__":
    main(sys.argv[1:])
