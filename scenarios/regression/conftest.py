import json
import os
import subprocess
import sys
from pathlib import Path
from time import sleep
from typing import Any
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum, auto
from collections import defaultdict

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

class DictType(Enum):
    USER_FARM_STATS_1 = auto()
    USER_STAKING_STATS_1 = auto()
    USER_2_FARM_STATS_1 = auto()
    USER_2_STAKING_STATS_1 = auto()
    PROXY_FARM_STATS_1 = auto()
    PROXY_STAKING_STATS_1 = auto()
    FARM_CONTRACT_STATS_1 = auto()
    STAKING_CONTRACT_STATS_1 = auto()
    TOKEN_ATTRS_1 = auto()
    USER_FARM_STATS_2 = auto()
    USER_STAKING_STATS_2 = auto()
    USER_2_FARM_STATS_2 = auto()
    USER_2_STAKING_STATS_2 = auto()
    PROXY_FARM_STATS_2 = auto()
    PROXY_STAKING_STATS_2 = auto()
    FARM_CONTRACT_STATS_2 = auto()
    STAKING_CONTRACT_STATS_2 = auto()
    TOKEN_ATTRS_2 = auto()
    OP1 = auto()
    OP2 = auto()
    OP3 = auto()
    OP4 = auto()

@dataclass
class DictComparison:
    before: Dict[str, Any]
    after: Dict[str, Any]
    description: str
    phase: str

class DictCollector:
    def __init__(self):
        self.reset()

    def reset(self):
        """Reset all collections for a new scenario"""
        self.before_upgrade: Dict[DictType, List[Tuple[Dict[str, Any], str]]] = defaultdict(list)
        self.after_upgrade: Dict[DictType, List[Tuple[Dict[str, Any], str]]] = defaultdict(list)
        self.current_phase = "before"  # "before" or "after"
    
    def set_phase(self, phase: str):
        """Set the current collection phase"""
        if phase not in ["before", "after"]:
            raise ValueError("Phase must be 'before' or 'after'")
        self.current_phase = phase

    def add(self, dict_type: DictType, dict_data: Dict[str, Any], description: str = ""):
        """Add a dictionary to the current phase collection"""
        if self.current_phase == "before":
            self.before_upgrade[dict_type].append((dict_data, description))
        else:
            self.after_upgrade[dict_type].append((dict_data, description))

    def _compare_dicts(self, dict1: Any, dict2: Any) -> Tuple[bool, Optional[str]]:
        """
        Compare two objects that can be either dictionaries or lists of dictionaries.
        Returns (is_equal, difference_description)
        """
        # Handle lists of dictionaries
        if isinstance(dict1, list) and isinstance(dict2, list):
            if len(dict1) != len(dict2):
                return False, f"Different list lengths: {len(dict1)} != {len(dict2)}"
            
            for i, (item1, item2) in enumerate(zip(dict1, dict2)):
                if isinstance(item1, (dict, list)) and isinstance(item2, (dict, list)):
                    is_equal, diff = self._compare_dicts(item1, item2)
                    if not is_equal:
                        return False, f"List item {i} difference: {diff}"
                elif item1 != item2:
                    return False, f"List item {i} mismatch: {item1} != {item2}"
            return True, None

        # Handle dictionaries
        if isinstance(dict1, dict) and isinstance(dict2, dict):
            if dict1.keys() != dict2.keys():
                missing_keys = set(dict1.keys()) - set(dict2.keys())
                extra_keys = set(dict2.keys()) - set(dict1.keys())
                return False, f"Different keys. Missing: {missing_keys}, Extra: {extra_keys}"

            for key in dict1:
                if isinstance(dict1[key], (dict, list)) and isinstance(dict2[key], (dict, list)):
                    is_equal, diff = self._compare_dicts(dict1[key], dict2[key])
                    if not is_equal:
                        return False, f"Nested difference at key '{key}': {diff}"
                elif dict1[key] != dict2[key]:
                    return False, f"Value mismatch for key '{key}': {dict1[key]} != {dict2[key]}"
            return True, None

        # Handle case where types don't match
        if type(dict1) != type(dict2):
            return False, f"Type mismatch: {type(dict1)} != {type(dict2)}"

        # Handle other cases
        return dict1 == dict2, f"Value mismatch: {dict1} != {dict2}" if dict1 != dict2 else None

    def compare_all(self) -> List[str]:
        """
        Compare all collected dictionary pairs and return a list of differences found.
        """
        differences = []

        for dict_type in DictType:
            before_list = self.before_upgrade[dict_type]
            after_list = self.after_upgrade[dict_type]

            # Check if we have matching pairs
            if len(before_list) != len(after_list):
                differences.append(
                    f"{dict_type.name}: Mismatched number of collections - "
                    f"Before: {len(before_list)}, After: {len(after_list)}"
                )
                continue

            # Compare each pair
            for i, ((before_dict, before_desc), (after_dict, after_desc)) in enumerate(zip(before_list, after_list)):
                is_equal, diff = self._compare_dicts(before_dict, after_dict)
                if not is_equal:
                    diff_msg = f"{dict_type.name} comparison failed"
                    if before_desc or after_desc:
                        diff_msg += f" (Before: {before_desc}, After: {after_desc})"
                    diff_msg += f": {diff}"
                    differences.append(diff_msg)

        return differences
    
    def print_collections(self):
        """
        Print a formatted view of all collections before and after upgrade.
        """
        print("\nCollections Summary:")
        print("=" * 80)

        for dict_type in DictType:            
            before_list = self.before_upgrade[dict_type]
            after_list = self.after_upgrade[dict_type]

            if not before_list and not after_list:
                continue

            print(f"\n{dict_type.name}:")
            print("-" * 40)

            print("\nBefore upgrade:")
            if not before_list:
                print("  No collections")
            for i, (data, desc) in enumerate(before_list, 1):
                print(f"  Collection {i}" + (f" ({desc})" if desc else ""))
                if isinstance(data, dict):
                    for key, value in data.items():
                        print(f"    {key}: {value}")
                else:
                    print(f"    {data}")

            print("\nAfter upgrade:")
            if not after_list:
                print("  No collections")
            for i, (data, desc) in enumerate(after_list, 1):
                print(f"  Collection {i}" + (f" ({desc})" if desc else ""))
                if isinstance(data, dict):
                    for key, value in data.items():
                        print(f"    {key}: {value}")
                else:
                    print(f"    {data}")

            print("\n" + "=" * 80)

# Example usage:
"""
collector = DictCollector()

# Before upgrade
collector.set_phase("before")
collector.add(DictType.USER_STATS, u1, "Initial user stats")
collector.add(DictType.CONTRACT_STATS, c1, "Initial contract stats")
collector.add(DictType.TOKEN_ATTRS, tk_attrs_1, "Initial token attributes")
collector.add(DictType.CLAIM_OPS, claim_ops_1, "Initial claim operations")

# After upgrade
collector.set_phase("after")
collector.add(DictType.USER_STATS, u3, "Post-upgrade user stats")
collector.add(DictType.CONTRACT_STATS, c3, "Post-upgrade contract stats")
collector.add(DictType.TOKEN_ATTRS, tk_attrs_2, "Post-upgrade token attributes")
collector.add(DictType.CLAIM_OPS, claim_ops_3, "Post-upgrade claim operations")

# Compare results
differences = collector.compare_all()
if differences:
    print("Found differences:")
    for diff in differences:
        print(f"- {diff}")
else:
    print("All comparisons passed!")

# Alternatively, at the end of your test
differences = collector.compare_all()
assert not differences, "\n".join(differences)

# Reset for next scenario
collector.reset()
"""
