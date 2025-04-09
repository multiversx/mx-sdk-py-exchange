import json
import os
import subprocess
import sys
from pathlib import Path
from time import sleep
from typing import Any

import pytest
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider
sys.path.append(str(Path.cwd().parent.parent.absolute()))

import config
from contracts.farm_contract import FarmContract
from tools.automated_scenarios.config_data import DOCKER_URL, GENERATE_BLOCKS_UNTIL_EPOCH_REACHED_URL, GENERATE_BLOCKS_URL, PROJECT_ROOT, SIMULATOR_URL, proxy, api, USERS, context

from utils.utils_chain import Account, WrapperAddress
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES
from utils.utils_chain import decode_merged_attributes, base64_to_hex, WrapperAddress, get_all_token_nonces_details_for_account
from utils.utils_scenarios import collect_farm_contract_users

@pytest.fixture
def data_load():
    abc = 1
    return abc
def pytest_report_header(config):
    return "project deps: mylib-1.1"

@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    # execute all other hooks to obtain the report object
    rep = yield

    if rep.when == "call" and rep.failed:
        mode = "a" if os.path.exists("failures") else "w"
        with open("failures", mode, encoding="utf-8") as f:
            if "tmp_path" in item.fixturenames:
                extra = " ({})".format(item.funcargs["tmp_path"])
            else:
                extra = ""

            f.write(rep.nodeid + extra + "\n")

    return rep

def fetch_farm_users(farm_contract: FarmContract):
    mainnet_api = ApiNetworkProvider("https://api.multiversx.com")
    fetched_users = collect_farm_contract_users(10000, farm_contract.address, farm_contract.farmingToken, farm_contract.farmToken,
                                                mainnet_api, context.network_provider.proxy)
    return fetched_users

def load_accounts_state(project_root: Path, addresses: list[str]) -> list[dict[str, Any]]:
    states = []
    
    for address in addresses:
        print(f"Loading state for {address}")
        user_path = f"0_{address}_0_chain_config_state.json"
        system_account_path = f"0_system_account_state_{address}.json"
        
        user_file = project_root / "states" / user_path
        system_file = project_root / "states" / system_account_path
        
        if user_file.exists():
            with open(user_file, "r") as file:
                user_state = json.load(file)
                if user_state:
                    print(f"Found {user_file.name}")
                    states.append(user_state)
                
        if system_file.exists():
            with open(system_file, "r") as file:
                system_state = json.load(file)
                if system_state:
                    print(f"Found {system_file.name}")
                    states.append(system_state)
            
    return states
    
def apply_states(proxy: ProxyNetworkProvider, states: list[dict[str, Any]]):
    for state in states:
        proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", state)

# @pytest.fixture
def load_and_apply_state(proxy: ProxyNetworkProvider, project_root: Path, owner: str, users: list[str]):
    # Load and set state for all keys
    with open(project_root / "states" / "0_all_all_keys.json", "r") as file:
        retrieved_state = json.load(file)
        apply_states(proxy, [retrieved_state])

    # Load owner and users state
    accounts = [owner]
    accounts.extend(users)
    states = load_accounts_state(project_root, accounts)
    apply_states(proxy, states)
        
def setup_chain_sim():
    # generate blocks to pass an epoch and the smart contract deploys to be enabled
    proxy.do_post(f"{GENERATE_BLOCKS_URL}/5", {})

    load_and_apply_state(proxy, PROJECT_ROOT,
                         context.deployer_account.address.bech32(),
                         USERS)


def advance_blocks(number_of_blocks: int):
    proxy.do_post(f"{GENERATE_BLOCKS_URL}/{number_of_blocks}", {})

def advance_epoch(number_of_epochs: int):
    proxy.do_post(f"{GENERATE_BLOCKS_URL}/{number_of_epochs * 20}", {})

def advance_to_epoch(epoch: int):
    proxy.do_post(f"{GENERATE_BLOCKS_UNTIL_EPOCH_REACHED_URL}/{epoch}", {})

# @pytest.fixture
def users_init() -> list[Account]:
    print(context.deployer_account.address.bech32())
    context.deployer_account.sync_nonce(context.network_provider.proxy)

    users = []
    for user in USERS:
        user_account = Account(pem_file=config.DEFAULT_ACCOUNTS)
        user_account.address = WrapperAddress(user)
        user_account.sync_nonce(context.network_provider.proxy)
        users.append(user_account)

    return users

def dict_compare(d1, d2):
    print(d1)
    print(d2)
    d1_keys = set(d1.keys())
    d2_keys = set(d2.keys())
    shared_keys = d1_keys.intersection(d2_keys)
    added = d1_keys - d2_keys
    removed = d2_keys - d1_keys
    modified = {o : (d1[o], d2[o]) for o in shared_keys if d1[o] != d2[o]}
    same = set(o for o in shared_keys if d1[o] == d2[o])
    return added, removed, modified, same

def check_equal_dicts(dict1, dict2):
    """
    Compare two dictionaries, including nested dictionaries.
    
    Args:
    dict1 (dict): First dictionary to compare.
    dict2 (dict): Second dictionary to compare.
    
    Returns:
    bool: True if dictionaries are equal, False otherwise.
    """
    if dict1.keys() != dict2.keys():
        return False
    
    for key in dict1:
        if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
            if not check_equal_dicts(dict1[key], dict2[key]):
                return False
        elif dict1[key] != dict2[key]:
            return False
    
    return True

class ChainSimulatorControl:
    def __init__(self):
        self.simulator_url = DOCKER_URL

    def start_chain_sim_stack(self):
        # stop first in case one is already running
        p = subprocess.Popen(["docker", "compose", "down"], cwd = DOCKER_URL)
        p.wait()
        
        p = subprocess.Popen(["docker", "compose", "up", "-d"], cwd = DOCKER_URL)
        sleep(60)
        return p

    def stop_chain_sim_stack(self,p):
        p.terminate()
        p = subprocess.Popen(["docker", "compose", "down"], cwd = DOCKER_URL)
        p.wait()
        _ = subprocess.run(["docker", "system", "prune", "-f"], cwd = DOCKER_URL)