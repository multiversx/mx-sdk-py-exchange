from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import base64
import binascii
import os
import json
import threading
import time
from typing import List
from multiversx_sdk import Address
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tools.runners.account_state_runner import get_account_keys_online, report_key_files_compare
from utils.utils_chain import Account
import config
from utils.utils_tx import NetworkProviders
from utils.utils_generic import ensure_folder


PROXY = config.DEFAULT_PROXY
OUTPUT_FOLDER = config.UPGRADER_OUTPUT_FOLDER
SHADOWFORK = "shadowfork" in PROXY

API = config.DEFAULT_API

OUTPUT_PAUSE_STATES = OUTPUT_FOLDER / "contract_pause_states.json"

# The public gateway allows 50 requests / IP / second. Stay under it with headroom, since
# other calls may be running against the same IP at the same time.
CONTRACT_FETCH_MAX_RPS = 40
CONTRACT_FETCH_WORKERS = 8
# Separate connect and read budgets, so one stalled response can't hold a worker for long.
CONTRACT_FETCH_TIMEOUT = (10, 30)
CONTRACT_FETCH_PROGRESS_EVERY = 50
CONTRACT_FETCH_RETRIES = 4
# urllib3 doubles the wait each time and caps at 120s by default, which can turn a flaky
# connection into minutes of invisible sleeping. Keep the worst case per request small.
CONTRACT_FETCH_BACKOFF_FACTOR = 0.5
CONTRACT_FETCH_BACKOFF_MAX = 5


class RequestRateLimiter:
    """Hands out evenly spaced request slots so concurrent workers stay under a rate ceiling."""

    def __init__(self, max_requests_per_second: float):
        self._min_interval = 1 / max_requests_per_second
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self):
        with self._lock:
            slot = max(time.monotonic(), self._next_slot)
            self._next_slot = slot + self._min_interval

        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def run_with_progress(work, items: list, label: str) -> list:
    """Run work(item) over items in parallel, reporting progress. Results keep the input order."""

    results = [None] * len(items)
    started = time.monotonic()
    completed = 0

    with ThreadPoolExecutor(max_workers=CONTRACT_FETCH_WORKERS) as executor:
        futures = {executor.submit(work, item): index for index, item in enumerate(items)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            completed += 1
            if completed % CONTRACT_FETCH_PROGRESS_EVERY == 0 or completed == len(items):
                print(f"  {label}: {completed}/{len(items)} "
                      f"({time.monotonic() - started:.0f}s elapsed)", flush=True)

    return results


class LoggingRetry(Retry):
    """Retry policy that says why it is backing off, so a slow run doesn't look like a hang."""

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        if response is not None:
            reason = f"HTTP {response.status}"
        elif error is not None:
            reason = f"{type(error).__name__}: {error}"
        else:
            reason = "unknown"
        print(f"  retrying after {reason}", flush=True)
        return super().increment(method, url, response, error, _pool, _stacktrace)


def build_pooled_session(pool_size: int) -> requests.Session:
    """Build a session that reuses connections and backs off on rate limits.

    The SDK opens a new session per request, so every call pays for a fresh TLS handshake.
    Reusing connections roughly halves the wall time of a bulk fetch. Note 429 is in the
    retry list: the SDK's default retry policy does not cover rate limiting.
    """

    retry_strategy = LoggingRetry(total=CONTRACT_FETCH_RETRIES,
                                  backoff_factor=CONTRACT_FETCH_BACKOFF_FACTOR,
                                  backoff_max=CONTRACT_FETCH_BACKOFF_MAX,
                                  status_forcelist=[429, 500, 502, 503, 504],
                                  allowed_methods=["GET", "POST"], respect_retry_after_header=True)
    adapter = HTTPAdapter(max_retries=retry_strategy,
                          pool_connections=pool_size, pool_maxsize=pool_size)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_contract_code(session: requests.Session, limiter: RequestRateLimiter, address: str) -> tuple:
    """Read one contract's code hash and code. Returns (code_hash, code, error).

    Goes straight at the address endpoint rather than through the SDK's get_account, which
    also fetches guardian data on a second request - unused here, and double the rate budget.
    """

    try:
        limiter.acquire()
        response = session.get(f"{PROXY.rstrip('/')}/address/{address}", timeout=CONTRACT_FETCH_TIMEOUT)
        response.raise_for_status()
        account = response.json().get("data", {}).get("account", {})

        raw_code_hash = account.get("codeHash") or ""
        if not raw_code_hash:
            return "", "", "no contract code hash"

        # The gateway sends the code hash base64 encoded and the code already hex encoded.
        return base64.b64decode(raw_code_hash).hex(), account.get("code", ""), ""
    except Exception as e:
        return "", "", str(e)


def fetch_and_save_contracts(contract_addresses: list, contract_label: str, save_path: Path):
    """Fetch and save contracts data in a json file"""

    print(f"Fetching {len(contract_addresses)} {contract_label} contracts "
          f"with {CONTRACT_FETCH_WORKERS} workers at up to {CONTRACT_FETCH_MAX_RPS} req/s...", flush=True)

    limiter = RequestRateLimiter(CONTRACT_FETCH_MAX_RPS)
    session = build_pooled_session(CONTRACT_FETCH_WORKERS)
    started = time.monotonic()
    try:
        results = run_with_progress(
            lambda address: fetch_contract_code(session, limiter, address), contract_addresses, contract_label)
    finally:
        session.close()

    pairs_data = {}
    failed = []

    for address, (code_hash, code, error) in zip(contract_addresses, results):
        if error:
            failed.append((address, error))
            continue

        if code_hash not in pairs_data:
            pairs_data[code_hash] = {
                contract_label: [],
                "code": code
            }
            save_wasm(code, code_hash)
        pairs_data[code_hash][contract_label].append(Address.new_from_bech32(address).to_bech32())

    print(f"Fetched {len(contract_addresses) - len(failed)}/{len(contract_addresses)} "
          f"{contract_label} contracts in {time.monotonic() - started:.1f}s")

    if failed:
        # Saving a partial file would silently drop contracts from every command that reads it.
        for address, error in failed[:10]:
            print(f"Failed to fetch {contract_label} {address}: {error}")
        raise RuntimeError(f"could not fetch {len(failed)}/{len(contract_addresses)} "
                           f"{contract_label} contracts; refusing to save partial data")

    ensure_folder(save_path.parent)

    with open(save_path, "w", encoding="UTF-8") as writer:
        json.dump(pairs_data, writer, indent=4)
        print(f"Dumped {contract_label} data in {save_path}")


def query_contract_pause_state(session: requests.Session, limiter: RequestRateLimiter, address: str) -> tuple:
    """Read one contract's getState view. Returns (state, error).

    Queries the VM endpoint directly instead of going through DataFetcher, which rebuilds a
    SmartContractController per call and so refetches the network config on every contract.
    """

    try:
        limiter.acquire()
        response = session.post(f"{PROXY.rstrip('/')}/vm-values/query",
                                json={"scAddress": address, "funcName": "getState", "args": []},
                                timeout=CONTRACT_FETCH_TIMEOUT)
        response.raise_for_status()
        data = response.json().get("data", {}).get("data", {})

        if data.get("returnCode") != "ok":
            return None, f"{data.get('returnCode')}: {data.get('returnMessage')}"

        return_data = data.get("returnData") or []
        if not return_data or not return_data[0]:
            return 0, ""

        return int(base64.b64decode(return_data[0]).hex(), 16), ""
    except Exception as e:
        return None, str(e)


def fetch_contract_pause_states(contract_addresses: List[str]) -> tuple:
    """Read the pause state of many contracts in parallel. Returns (states, failures).

    A failed query is reported as a failure rather than folded into the states, because the
    view helpers answer -1 on error and consumers read that as a real state.
    """

    print(f"Fetching pause state of {len(contract_addresses)} contracts "
          f"with {CONTRACT_FETCH_WORKERS} workers at up to {CONTRACT_FETCH_MAX_RPS} req/s...", flush=True)

    limiter = RequestRateLimiter(CONTRACT_FETCH_MAX_RPS)
    session = build_pooled_session(CONTRACT_FETCH_WORKERS)
    started = time.monotonic()
    try:
        results = run_with_progress(
            lambda address: query_contract_pause_state(session, limiter, address), contract_addresses, "pause states")
    finally:
        session.close()

    states = {}
    failures = []
    for address, (state, error) in zip(contract_addresses, results):
        if error:
            failures.append((address, error))
        else:
            states[address] = state

    print(f"Fetched {len(states)}/{len(contract_addresses)} pause states "
          f"in {time.monotonic() - started:.1f}s")
    return states, failures


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


def rule_of_three(first_amount, first_equivalent, second_amount):
    return (second_amount * first_equivalent) // first_amount
