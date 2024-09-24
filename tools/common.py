from pathlib import Path
import binascii
import os
import json
from typing import List
from multiversx_sdk import Address, ProxyNetworkProvider
import requests
from tools.runners.account_state_runner import get_account_keys_online, report_key_files_compare
from utils.utils_chain import Account, base64_to_hex
import config
from utils.utils_tx import NetworkProviders
from utils.utils_generic import ensure_folder


PROXY = config.DEFAULT_PROXY
OUTPUT_FOLDER = config.UPGRADER_OUTPUT_FOLDER
SHADOWFORK = "shadowfork" in PROXY

API = config.DEFAULT_API

OUTPUT_PAUSE_STATES = OUTPUT_FOLDER / "contract_pause_states.json"


def fetch_and_save_contracts(contract_addresses: list, contract_label: str, save_path: Path):
    """Fetch and save contracts data in a json file"""

    proxy = ProxyNetworkProvider(config.DEFAULT_PROXY)
    pairs_data = {}

    for address in contract_addresses:
        contract_addr = Address.new_from_bech32(address)
        account_data = proxy.get_account(contract_addr)
        if not account_data.code_hash:
            print(f"Account data not found for {contract_label} {address}")
            continue
        code_hash = base64_to_hex(account_data.code_hash)

        if code_hash not in pairs_data:
            pairs_data[code_hash] = {
                contract_label: [],
                "code": account_data.code.hex()
            }
            save_wasm(account_data.code.hex(), code_hash)
        pairs_data[code_hash][contract_label].append(contract_addr.bech32())

    ensure_folder(save_path.parent)

    with open(save_path, "w", encoding="UTF-8") as writer:
        json.dump(pairs_data, writer, indent=4)
        print(f"Dumped {contract_label} data in {save_path}")


def fetch_contracts_states(prefix: str, network_providers: NetworkProviders, contract_addresses: List[str], label: str):
    """Fetch contracts states"""

    for contract_address in contract_addresses:
        filename = get_contract_save_name(label, contract_address, prefix)
        get_account_keys_online(contract_address, network_providers.proxy.url,
                                with_save_in=str(OUTPUT_FOLDER / f"{filename}.json"))


def fetch_new_and_compare_contract_states(contract_type: str, contract_address, network_providers: NetworkProviders):
    """Fetch new contract state and compare it with the old one"""

    old_state_filename = get_contract_save_name(contract_type, contract_address, "pre")
    new_state_filename = get_contract_save_name(contract_type, contract_address, "mid")
    fetch_contract_state(contract_address, new_state_filename, network_providers)
    report_key_files_compare(str(OUTPUT_FOLDER), old_state_filename, new_state_filename, True)


def fetch_contract_state(contract_address: str, save_name: str, network_providers: NetworkProviders):
    """Fetch contract state"""

    get_account_keys_online(contract_address, network_providers.proxy.url,
                            with_save_in=str(OUTPUT_FOLDER / f"{save_name}.json"))


def save_wasm(code_data_hex: str, code_hash: str):
    """Save wasm binary"""

    binary_string = binascii.unhexlify(code_data_hex)

    if not os.path.exists(OUTPUT_FOLDER):
        os.mkdir(OUTPUT_FOLDER)

    output_file = os.path.join(OUTPUT_FOLDER, f"{code_hash}.wasm")
    with open(f"{output_file}", 'wb') as b:
        b.write(binary_string)

    print(f"Created wasm binary in: {output_file}")


def get_saved_contracts_data(saved_file: Path) -> dict:
    """Get saved contracts data"""

    if not os.path.exists(saved_file):
        raise FileNotFoundError("Saved contract data from mainnet not available!")

    print("Reading data...")
    with open(saved_file, encoding="UTF-8") as reader:
        contracts_data = json.load(reader)
    return contracts_data


def get_saved_contract_addresses(contract_label: str, saved_file: Path, searched_bytecode_hash: str = '') -> list:
    """Get saved contract addresses"""

    contracts_data = {}

    try:
        contracts_data = get_saved_contracts_data(saved_file)
    except FileNotFoundError as error:
        print(f"Error encountered for {contract_label}: {error}")

    contracts_addresses = []
    for bytecode_hash, contracts in contracts_data.items():
        if searched_bytecode_hash and bytecode_hash != searched_bytecode_hash:
            continue
        contracts_addresses.extend(contracts[contract_label])
    return contracts_addresses


def get_owner(proxy) -> Account:
    """Get owner account"""

    owner = Account.from_file(config.DEFAULT_OWNER)
    if SHADOWFORK:
        owner.address = Address.new_from_bech32(config.DEX_OWNER_ADDRESS)      # ONLY FOR SHADOWFORK
    owner.sync_nonce(proxy)
    return owner


def get_user_continue(force_yes: bool = False) -> bool:
    """Get user confirmation to continue"""

    if force_yes:
        return True

    typed = input("Continue? y/n\n")
    while typed != "y" and typed != "n":
        typed = input("Wrong choice. Continue? y/n\n")
    if typed == "n":
        return False
    return True


def run_graphql_query(uri, query):
    """Run graphql query"""

    headers = {}
    status_code = 200
    request = requests.post(uri, json={'query': query}, headers=headers, timeout=60)

    if request.status_code == status_code:
        return request.json()

    raise Exception(f"Unexpected status code returned: {request.status_code}")


def get_contract_save_name(contract_type: str, address: str, prefix: str):
    """Get contract save name"""

    return f"{prefix}_{contract_type}_{address}"
