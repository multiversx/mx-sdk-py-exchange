import os
from pathlib import Path
import subprocess
import sys
import time
import json
import yaml
import config
from argparse import ArgumentParser
from typing import Any, List
from context import Context
from contracts.contract_identities import DEXContractInterface
import requests
from utils.utils_chain import string_to_hex
from utils.utils_chain import WrapperAddress
from utils.logger import get_logger
from utils.utils_generic import log_step_fail, log_step_pass, log_warning
from tools.runners.account_state_runner import get_account_keys_online, get_account_data_online
from multiversx_sdk import ProxyNetworkProvider
from multiversx_sdk.core.address import Address
from utils.utils_tx import ESDTToken


logger = get_logger(__name__)


SIMULATOR_URL = "http://localhost:8085"
API_URL = "http://localhost:3001"
GENERATE_BLOCKS_URL = f"{SIMULATOR_URL}/simulator/generate-blocks/"
SET_STATE_URL = f"{SIMULATOR_URL}/simulator/set-state"
SEND_USER_FUNDS_URL = f"{SIMULATOR_URL}/transaction/send-user-funds"
STATES_FOLDER = "states"
BLOCKS_PER_EPOCH = 20


def is_valid_address(address: str) -> bool:
    try:
        Address.new_from_bech32(address)
        return True
    except Exception:
        return False
    

def is_smart_contract(address: str) -> bool:
    try:
        return Address.new_from_bech32(address).is_smart_contract()
    except Exception:
        return False
    

def get_sc_states_files_in_folder(state_folder: Path) -> str | None:
    state_files = list(state_folder.iterdir())
    all_keys_file = None

    for file in state_files:
        if "all_all_keys.json" in file.name:
            all_keys_file = file
            break

    return all_keys_file


def get_address_states_in_folder(state_folder: Path, addresses: list[str]) -> list[dict[str, Any]] | None:
    states = []
    
    for address in addresses:
        logger.debug(f"Loading state for {address}")
        user_path = f"0_{address}_0_chain_config_state.json"
        system_account_path = f"0_system_account_state_{address}.json"
        
        user_file = state_folder / user_path
        system_file = state_folder / system_account_path
        
        if user_file.exists():
            with open(user_file, "r") as file:
                user_state = json.load(file)
                if user_state:
                    logger.debug(f"Found {user_file.name}")
                    states.append(user_state)
                
        if system_file.exists():
            with open(system_file, "r") as file:
                system_state = json.load(file)
                if system_state:
                    logger.debug(f"Found {system_file.name}")
                    states.append(system_state)
            
    return states

def get_standalone_addresses_in_folder(state_folder: Path) -> tuple[list[str], list[str]]:
    state_files = list(state_folder.iterdir())
    users = []
    contracts = []
    for file in state_files:
        if "_chain_config_state.json" in file.name:
            # Smart contracts are already in all_all_keys.json, except the manually fetched ones + user addresses
            filename_no_ext = file.stem
            potential_address = filename_no_ext.split("_")[1]
            if is_valid_address(potential_address) and not is_smart_contract(potential_address): 
                users.append(potential_address)
            elif is_valid_address(potential_address) and is_smart_contract(potential_address): 
                contracts.append(potential_address)
    return users, contracts


def get_standalone_contracts_in_folder(state_folder: Path) -> list[str]:
    state_files = list(state_folder.iterdir())
    contracts = []
    for file in state_files:
        if "_chain_config_state.json" in file.name:
            filename_no_ext = file.stem
            potential_address = filename_no_ext.split("_")[1]
            if is_valid_address(potential_address) and is_smart_contract(potential_address): 
                contracts.append(potential_address)
    return contracts

def get_shard_chronology_in_folder(state_folder: Path) -> dict[str, int] | None:
    state_files = list(state_folder.iterdir())
    for file in state_files:
        if "shard_chronology.json" in file.name:
            with open(file, 'r', encoding="UTF-8") as f:
                return json.load(f)
    return None


def get_all_sc_states_in_folder(state_folder: Path) -> list[str]:
    state_file = get_sc_states_files_in_folder(state_folder)
    if not state_file:
        return []
    with open(state_file, 'r', encoding="UTF-8") as f:
        return [json.load(f)]
    

class ChainSimulator:
    def __init__(self, docker_path: Path = None):
        self.docker_path = docker_path
        self.proxy_url = SIMULATOR_URL
        self.api_url = API_URL
        self.process = None

    def start(self, block: int = 0, round: int = 0, epoch: int = 0):
        p = subprocess.Popen(["docker", "compose", "down"], cwd = self.docker_path)
        p.wait()
        p.terminate()
        
        # alter docker-compose.yml to start with the correct block, round and epoch & add other necessary mods
        self._update_docker_compose(block, round, epoch)
        self.process = subprocess.Popen(["docker", "compose", "up", "-d"], cwd = self.docker_path)
        time.sleep(50)
        return self.process

    def stop(self):
        if self.process:
            self.process.terminate()
        # go nuclear on anything that might be running
        p = subprocess.Popen(["docker", "compose", "down"], cwd = self.docker_path)
        p.wait()

    def apply_states(self, states: list[list[dict[str, Any]]]):
        for state in states:
            response = requests.post(f"{self.proxy_url}/simulator/set-state", json=state)
            if response.status_code != 200:
                logger.error(f"Failed to apply states: {response.text}")
                return False
        return True

    def init_state_from_folder(self, state_folder: Path) -> list[str]:
        all_sc_states = get_all_sc_states_in_folder(state_folder)
        user_addresses, contract_addresses = get_standalone_addresses_in_folder(state_folder)
        all_user_states = get_address_states_in_folder(state_folder, user_addresses)
        all_standalone_contract_states = get_address_states_in_folder(state_folder, contract_addresses)

        if all_sc_states:
            self.apply_states(all_sc_states)
            logger.info("Smart contracts states applied.")

        if all_standalone_contract_states:
            self.apply_states(all_standalone_contract_states)
            logger.info("Standalone contract states applied.")

        if all_user_states:
            self.apply_states(all_user_states)
            logger.info("User states applied.") 

        # return found user addresses
        return user_addresses

    def advance_blocks(self, number_of_blocks: int):
        url = f"{self.proxy_url}/simulator/generate-blocks/{number_of_blocks}"
        response = requests.post(url)
        return response.json()
    
    def advance_epochs(self, number_of_epochs: int):
        blocks_to_advance = BLOCKS_PER_EPOCH * number_of_epochs
        return self.advance_blocks(blocks_to_advance)
    
    def advance_epochs_to_epoch(self, target_epoch: int):
        proxy = ProxyNetworkProvider(self.proxy_url)
        current_epoch = proxy.get_network_status().current_epoch
        if current_epoch >= target_epoch:
            return
        blocks_to_advance = (target_epoch - current_epoch) * BLOCKS_PER_EPOCH
        return self.advance_blocks(blocks_to_advance)

    def _update_docker_compose(self, block: int, round: int, epoch: int):
        # Load the docker-compose.yaml file
        with open(self.docker_path / "docker-compose.yaml", 'r') as file:
            docker_compose = yaml.safe_load(file)
        
        # Locate the chain-simulator service
        chain_simulator = docker_compose['services'].get('chain-simulator', {})
        
        # Update the entrypoint
        chain_simulator['entrypoint'] = (
            "/bin/bash -c \" sed -i 's|http://localhost:9200|http://elasticsearch:9200|g' ./config/node/config/external.toml "
            "&& sed -i '11i\\    { File = \\\"enableEpochs.toml\\\", Path = \\\"EnableEpochs.StakingV2EnableEpoch\\\", Value = 0},' ./config/nodeOverrideDefault.toml "
            f"&& ./start-with-services.sh -log-level *:INFO --initial-round={round} --initial-nonce={block} --initial-epoch={epoch}\""
        )
        
        # Save the modified docker-compose.yaml file
        with open(self.docker_path / "docker-compose.yaml", 'w') as file:
            yaml.dump(docker_compose, file, default_flow_style=False, sort_keys=False)
        
        logger.info(f"Updated {self.docker_path / 'docker-compose.yaml'} with block {block}, round {round}, epoch {epoch}.")

    

def get_retrieve_block(proxy: ProxyNetworkProvider, shard: int, block: int) -> int:
    block_number = block
    if block_number == 0:
        # get last block number
        response = proxy.get_network_status(shard)
        block_number = response.highest_final_block_nonce
    
    return block_number


def get_current_shard_chronology(proxy: ProxyNetworkProvider, shard: int = None) -> dict:
    # returns current epoch, round, block 
    # TODO: not sure if timestamp is necessary as well
    response = proxy.get_network_status(shard)
    response_dict = {
        "epoch": response.current_epoch,
        "round": response.current_round,
        "block": response.highest_final_block_nonce
    }

    return response_dict


def get_contract_retrieval_labels(contracts: str) -> List[str]:
    labels = []
    base_labels = [config.EGLD_WRAPS, config.LOCKED_ASSETS, config.SIMPLE_LOCKS_ENERGY, 
                  config.UNSTAKERS, config.FEES_COLLECTORS, config.ROUTER_V2]
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
    data.pop("rootHash", None) # remove rootHash from data
    
    account_state = {}
    account_state.update(data)
    account_state['pairs'] = keys 

    # save account chain config state to file
    with open(chain_config_file, 'w', encoding="UTF-8") as state_writer:
        json.dump([account_state], state_writer, indent=4)
    logger.info(f"Chain config account state for {address} has been saved to {chain_config_file}.")

    return account_state


def get_token_key_hex(token: ESDTToken) -> str:
    return f"{string_to_hex('ELRONDesdt')}{string_to_hex(token.token_id)}"


def get_token_nonce_key_hex(token: ESDTToken) -> str:
    return f"{get_token_key_hex(token)}{token.get_token_nonce_hex()}"


def fetch_token_system_account_attributes(proxy: ProxyNetworkProvider, token: ESDTToken, block_number: int = 0) -> dict[str, str]:
    block_param = f"?blockNonce={block_number}" if block_number else ""
    key = get_token_key_hex(token)
    resource_url = f"address/erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t/key/{key}{block_param}"
    response = proxy.do_get_generic(resource_url)
    return {key: response.get("value", "")}


def fetch_token_nonce_system_account_attributes(proxy: ProxyNetworkProvider, token: ESDTToken, block_number: int = 0) -> dict[str, str]:
    block_param = f"?blockNonce={block_number}" if block_number else ""
    key = get_token_nonce_key_hex(token)
    resource_url = f"address/erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t/key/{key}{block_param}"
    response = proxy.do_get_generic(resource_url)
    return {key: response.get("value", "")}


def fetch_context_system_account_state_from_account(proxy: ProxyNetworkProvider, context: Context, address: str, block_number: int = 0) -> dict[str, Any]:
    """
    Fetch system account keys for all the context related meta esdts the account owns.
    """
    sys_account_keys = {}

    context_tokens = get_context_used_tokens(context)

    try:
        user_tokens = proxy.get_non_fungible_tokens_of_account(WrapperAddress(address))
    except Exception as e:
        logger.error(f"Error fetching non-fungible tokens of account {address}: {e}")
        logger.error("System account state for this account will not be retrieved.")
        return {}
    
    logger.debug(f"Starting retrieval of system account keys for context related meta esdts owned by {address}.")
    logger.debug(f"Number of meta esdt tokens found in account: {len(user_tokens)}")
    for token in user_tokens:
        print(f"\rProcessing token {user_tokens.index(token) + 1}/{len(user_tokens)}", end="", flush=True) # this can take a while depending on the number of tokens

        if not token.token.identifier in context_tokens:
            continue
        sys_account_token_attributes = fetch_token_nonce_system_account_attributes(proxy, ESDTToken.from_amount_on_network(token), block_number)
        sys_account_keys.update(sys_account_token_attributes)
    print() # new line after progress bar

    sys_account_state = {
        "address": "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t",
        "pairs": sys_account_keys
    }

    # save system account state to file
    sys_account_state_file = f"{STATES_FOLDER}/{block_number}_system_account_state_{address}.json"
    with open(sys_account_state_file, 'w', encoding="UTF-8") as state_writer:
        json.dump([sys_account_state], state_writer, indent=4)
    logger.info(f"System account state for tokens in {address} has been saved to {sys_account_state_file}.")

    return sys_account_state


def fetch_system_account_state_from_token(token: str, proxy: ProxyNetworkProvider, block_number: int = 0) -> dict[str, Any]:
    sys_account_keys = fetch_token_nonce_system_account_attributes(proxy, ESDTToken.from_full_token_name(token), block_number)

    # TODO: need a fix below to uncomment the fetch_token_system_account_attributes function; 
    # TODO: transfer roles on chain simulator don't work correctly if this is active, but without it, some roles can't be correctly assigned
    # sys_account_keys.update(fetch_token_system_account_attributes(proxy, ESDTToken.from_full_token_name(token), block_number))

    sys_account_state = {
        "address": "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t",
        "pairs": sys_account_keys
    }

    # save system account state to file
    sys_account_state_file = f"{STATES_FOLDER}/{block_number}_system_account_state_{token}.json"
    with open(sys_account_state_file, 'w', encoding="UTF-8") as state_writer:
        json.dump([sys_account_state], state_writer, indent=4)
    logger.info(f"System account state for {token} has been saved to {sys_account_state_file}.")

    return sys_account_state


def compose_system_account_state_from_contract_state(contract: DEXContractInterface, contract_state: dict[str, Any], proxy: ProxyNetworkProvider, block_number: int = 0) -> dict[str, Any]:
    """
    Compose system account state from contract state by searching for meta esdts for which the contract is the creator (not owner). 
    It looks for the existence of the last nonce of each token and fetches the system account state for that nonce.
    """
    system_account_state = {}
    tokens = contract.get_contract_tokens()
    
    for token in tokens:
        # Convert 'ELRONDnonce' and token name to hex
        elrond_nonce_hex = string_to_hex('ELRONDnonce')
        token_hex = string_to_hex(token)
        search_key = f"{elrond_nonce_hex}{token_hex}"

        # Search through contract state keys
        if search_key in contract_state['pairs'].keys():
            # Found matching key, get nonce value and fetch system account state
            nonce = contract_state['pairs'][search_key]

            token_with_nonce = f"{token}-{nonce}"
            token_system_account_state = fetch_system_account_state_from_token(token_with_nonce, proxy, block_number)
            # Merge the pairs from token_system_account_state into system_account_state
            if not system_account_state:
                system_account_state = token_system_account_state
            else:
                system_account_state["pairs"].update(token_system_account_state["pairs"])

    return system_account_state

def fetch_contract_states(context: Context, args, proxy: ProxyNetworkProvider, block_number: int = 0) -> dict[str, Any]:
    contracts_shard = WrapperAddress(context.get_contracts(config.ROUTER_V2)[0].address).get_shard()
    all_keys: list[dict] = []
    
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

            # search for meta esdts created by the contract and fetch the system account state for their last nonce
            system_account_state = compose_system_account_state_from_contract_state(contract, account_state, proxy, block_number)
            if system_account_state:
                all_keys.append(system_account_state)

            # get system account state for all the context related meta esdts the contract owns
            system_account_state = fetch_context_system_account_state_from_account(proxy, context, contract.address, block_number)
            if system_account_state:
                all_keys.append(system_account_state)

    # get ESDT issue account state
    logger.info(f"Retrieving state for ESDT issue account.")
    account_state = fetch_account_state(config.TOKENS_CONTRACT_ADDRESS, proxy, block_number, "esdt_issue", 0)
    if account_state:
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


def fetch_user_state_with_tokens(user_address: str, context: Context, proxy: ProxyNetworkProvider, block_number: int = 0) -> dict[str, Any]:
    address = WrapperAddress(user_address)

    # get user account state
    _ = fetch_account_state(address.bech32(), proxy, block_number, user_address, 0)

    # compose system account token attributes
    _ = fetch_context_system_account_state_from_account(proxy, context, address.bech32(), block_number)


def retrieve_handler(args: Any):
    if not args.gateway:
        log_step_fail("Gateway is required. Please provide a gateway address.")
        return
    
    context = Context()
    proxy = ProxyNetworkProvider(args.gateway)
    # if block is not empty, use it to retrieve all state from that specific block
    contracts_shard = WrapperAddress(context.get_contracts(config.ROUTER_V2)[0].address).get_shard()
    block_number = get_retrieve_block(proxy, contracts_shard, int(args.block)) if args.block else 0

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
            
        fetch_contract_states(context, args, proxy, block_number)
    
    if args.account:
        fetch_user_state_with_tokens(args.account, context, proxy, block_number)

    if args.token:
        fetch_system_account_state_from_token(args.token, proxy, block_number)


def start_handler(args: Any) -> tuple[ChainSimulator, list[str]]:
    """
    Starts the chain simulator and loads all the contract and account states found in the default folder.
    """

    if not args.docker_path or not Path(args.docker_path).exists():
        log_step_fail("Docker path is not provided or does not exist. Please provide a valid docker path.")
        return
    if not args.state_path or not Path(args.state_path).exists():
        log_warning(f"State path is not provided or does not exist. Using default folder: {STATES_FOLDER}")
        args.state_path = STATES_FOLDER
    
    chronology = get_shard_chronology_in_folder(Path(args.state_path))
    if not chronology:
        log_step_fail("Shard chronology file not found. Please provide a valid state path.")
        return
    
    chain_sim = ChainSimulator(Path(args.docker_path))
    chain_sim.start(block=chronology["block"], round=chronology["round"], epoch=chronology["epoch"])
    found_accounts = chain_sim.init_state_from_folder(Path(args.state_path))

    return chain_sim, found_accounts

def main(cli_args: List[str]):
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    retrieve_parser = subparsers.add_parser('retrieve', help='retrive chain simulator states')
    retrieve_parser.add_argument("--gateway", required=False, default="")
    retrieve_parser.add_argument("--block", required=False, default="") # 0 - frozen to last block, x - frozen to specific block number, empty - unfrozen
    retrieve_parser.add_argument("--system-account", required=False, default="offline") # offline | online
    retrieve_parser.add_argument("--contracts", required=False, default="") # all | base | comma separated labels of contracts 
    retrieve_parser.add_argument("--contract-index", required=False, default="") # index of contract to retrieve state from; should only be used in conjunction with one specific type of --contracts
    retrieve_parser.add_argument("--account", required=False, default="") # explicit account address to retrieve state from 
    retrieve_parser.add_argument("--token", required=False, default="") # explicit token to retrieve sys account state for
    retrieve_parser.set_defaults(func=retrieve_handler)
    
    start_parser = subparsers.add_parser('start', help='start chain simulator')
    start_parser.add_argument("--docker-path", required=False, default="", help="path to full stack chain simulator docker compose folder")
    start_parser.add_argument("--state-path", required=False, default="", help="path to folder where chain simulator states are saved")
    start_parser.set_defaults(func=start_handler)
    
    args = parser.parse_args(cli_args)
    if not hasattr(args, 'func'):
        parser.print_help()
        return

    args.func(args)

if __name__ == "__main__":
    main(sys.argv[1:])


"""
Example usage:
$ python3 tools/chain_simulator_connector.py retrieve --gateway=https://proxy-shadowfork-four.elrond.ro --contracts=all
$ python3 tools/chain_simulator_connector.py retrieve --gateway=https://proxy-shadowfork-four.elrond.ro --account=erd1ss6u80ruas2phpmr82r42xnkd6rxy40g9jl69frppl4qez9w2jpsqj8x97
$ python3 tools/chain_simulator_connector.py retrieve --gateway=https://proxy-shadowfork-four.elrond.ro --token=METAUTKLK-112f52-0196c6

$ python3 tools/chain_simulator_connector.py start --docker-path=./docker --state-path=./states
"""