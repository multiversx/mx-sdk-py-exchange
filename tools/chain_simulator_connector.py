import json
import os
import subprocess
import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, List

import requests
import yaml
from multiversx_sdk import ProxyNetworkProvider
from multiversx_sdk.core.address import Address

import config
from context import Context
from contracts.contract_identities import DEXContractInterface
from tools.runners.account_state_runner import get_account_data_online, get_account_keys_online
from utils.logger import get_logger
from utils.utils_chain import WrapperAddress, string_to_hex
from utils.utils_generic import log_step_fail, log_step_pass, log_warning
from utils.utils_tx import ESDTToken

logger = get_logger(__name__)


# Hex-encoded storage key prefixes for safe price observations in pair contracts.
# These keys store round-dependent TWAP data that causes "cast to i64 error" when
# loaded mainnet state has round numbers higher than the chain simulator's current round.
# Filtering these keys lets pair contracts reinitialize safe price from scratch.
SAFE_PRICE_KEY_PREFIXES = [
    "70726963655f6f62736572766174696f6e73",  # "price_observations" (covers .item* and .len)
    "736166655f70726963655f63757272656e745f696e646578",  # "safe_price_current_index"
]

# Hex-encoded storage key for firstWeekStartEpoch in fees collector and boosted contracts.
# Week calculation: week = (current_epoch - first_week_start_epoch) / 7
# When mainnet state has first_week_start_epoch=862, the chain simulator needs epoch 869+.
# Overriding to 0 means epoch 7+ suffices for week >= 1.
FIRST_WEEK_START_EPOCH_KEY = "66697273745765656b537461727445706f6368"  # "firstWeekStartEpoch"

# Hex-encoded storage keys for last reward timestamps in farm/staking contracts.
# These store Unix timestamps from mainnet (e.g. ~1.74 billion seconds).
# When chain sim starts at round 0 (timestamp ~0), the elapsed time calculation
# underflows: elapsed = 0 - mainnet_timestamp wraps to a huge u64, exhausting the
# reward capacity in a single claim. Resetting to 0 means elapsed = current_timestamp
# which is a small positive number, and rewards accrue correctly from chain sim start.
# Contracts may use either camelCase or snake_case storage keys depending on version.
# Filter both variants to ensure mainnet values are always reset.
LAST_REWARD_TIMESTAMP_KEYS = [
    "6c61737452657761726454696d657374616d70",  # "lastRewardTimestamp" (camelCase)
    "6c6173745f7265776172645f74696d657374616d70",  # "last_reward_timestamp" (snake_case)
]
LAST_REWARD_BLOCK_NONCE_KEYS = [
    "6c617374526577617264426c6f636b4e6f6e6365",  # "lastRewardBlockNonce" (camelCase)
    "6c6173745f7265776172645f626c6f636b5f6e6f6e6365",  # "last_reward_block_nonce" (snake_case)
]

# Hex-encoded storage key prefixes for boosted yields week-dependent data.
# These keys store mainnet week numbers (e.g. week 169) which are incompatible with
# chain simulator epochs (epoch ~10 → week ~2). The boostedYieldsConfig contains
# last_update_week which triggers "Invalid config week" when current_week < last_update_week.
# Clearing all week-dependent keys lets the contract reinitialize from scratch.
BOOSTED_YIELDS_WEEK_KEY_PREFIXES = [
    "626f6f737465645969656c6473436f6e666967",  # "boostedYieldsConfig"
    "6c617374476c6f62616c5570646174655765656b",  # "lastGlobalUpdateWeek"
    "6661726d537570706c79466f725765656b",  # "farmSupplyForWeek"
    "746f74616c456e65726779466f725765656b",  # "totalEnergyForWeek"
    "746f74616c52657761726473466f725765656b",  # "totalRewardsForWeek"
    "746f74616c4c6f636b6564546f6b656e73466f725765656b",  # "totalLockedTokensForWeek"
    "72656d61696e696e67426f6f7374656452657761726473546f44697374726962757465",  # "remainingBoostedRewardsToDistribute"
    "63757272656e74436c61696d50726f6772657373",  # "currentClaimProgress"
    "616363756d756c6174656452657761726473466f725765656b",  # "accumulatedRewardsForWeek"
    "6c6f636b6564546f6b656e73496e4275636b6574",  # "lockedTokensInBucket"
    "66697273744275636b65744964",  # "firstBucketId"
    "6c617374436f6c6c656374556e646973745765656b",  # "lastCollectUndistWeek"
]

SIMULATOR_URL = "http://localhost:8085"
API_URL = "http://localhost:3001"
GENERATE_BLOCKS_URL = f"{SIMULATOR_URL}/simulator/generate-blocks/"
SET_STATE_URL = f"{SIMULATOR_URL}/simulator/set-state"
SEND_USER_FUNDS_URL = f"{SIMULATOR_URL}/transaction/send-user-funds"
STATES_FOLDER = "states"
BLOCKS_PER_EPOCH = 10


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


def get_sc_states_files_in_folder(state_folder: Path) -> list[Path]:
    state_files = list(state_folder.iterdir())

    sc_state_files = []
    for file in state_files:
        if file and "all_keys.json" in file.name:
            logger.info(f"Return file path: {file.as_posix()}")
            sc_state_files.append(file)

    return sc_state_files


def get_address_states_in_folder(
    state_folder: Path, addresses: list[str]
) -> list[dict[str, Any]] | None:
    states = []

    for address in addresses:
        logger.debug(f"Loading state for {address}")
        user_path = f"0_{address}_0_chain_config_state.json"
        system_account_path = f"0_system_account_state_{address}.json"

        user_file = state_folder / user_path
        system_file = state_folder / system_account_path

        if user_file.exists():
            with open(user_file) as file:
                user_state = json.load(file)
                if user_state:
                    logger.debug(f"Found {user_file.name}")
                    states.append(user_state)

        if system_file.exists():
            with open(system_file) as file:
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
            with open(file, encoding="UTF-8") as f:
                return json.load(f)
    return None


def filter_safe_price_keys(
    states: list[Any], key_prefixes: list[str] = None
) -> tuple[list[Any], int]:
    """Filter round-dependent safe price storage keys from account states.

    Pair contracts store TWAP price observations tagged with mainnet round numbers.
    When loaded into a chain simulator with much lower round numbers, arithmetic
    underflow occurs (current_round - stored_round < 0 → "cast to i64 error").

    Removing these keys lets the contract reinitialize safe price observations
    using the chain simulator's current round numbers.

    Args:
        states: List of account state dicts (each with optional 'pairs' storage dict)
        key_prefixes: Hex key prefixes to filter (defaults to SAFE_PRICE_KEY_PREFIXES)

    Returns:
        Tuple of (filtered_states, count_of_removed_keys)
    """
    if key_prefixes is None:
        key_prefixes = SAFE_PRICE_KEY_PREFIXES

    total_removed = 0
    for account_state in states:
        if not isinstance(account_state, dict) or "pairs" not in account_state:
            continue
        pairs = account_state["pairs"]
        keys_to_remove = [k for k in pairs if any(k.startswith(prefix) for prefix in key_prefixes)]
        for k in keys_to_remove:
            del pairs[k]
        total_removed += len(keys_to_remove)

    return states, total_removed


def override_first_week_start_epoch(
    states: list[Any], new_value: str = ""
) -> tuple[list[Any], int]:
    """Override firstWeekStartEpoch storage key to 0 in all account states.

    Fees collector (and boosted contracts) compute the current week as:
        week = (current_epoch - first_week_start_epoch) / 7
    When mainnet state has first_week_start_epoch=862, the chain simulator needs
    to be at epoch 869+ for valid weeks. By overriding to 0, epoch 7+ suffices.

    Args:
        states: List of account state dicts (each with optional 'pairs' storage dict)
        new_value: Hex-encoded new value (default "" = 0 for u64)

    Returns:
        Tuple of (modified_states, count_of_overridden_keys)
    """
    total_overridden = 0
    for account_state in states:
        if not isinstance(account_state, dict) or "pairs" not in account_state:
            continue
        pairs = account_state["pairs"]
        if FIRST_WEEK_START_EPOCH_KEY in pairs:
            old_value = pairs[FIRST_WEEK_START_EPOCH_KEY]
            pairs[FIRST_WEEK_START_EPOCH_KEY] = new_value
            total_overridden += 1
            address = account_state.get("address", "unknown")
            logger.info(f"Overrode firstWeekStartEpoch for {address}: {old_value} -> 0")

    return states, total_overridden


def get_all_sc_states_in_folder(state_folder: Path) -> list[Any]:
    state_file_paths = get_sc_states_files_in_folder(state_folder)
    if len(state_file_paths) == 0:
        return []

    all_sc_states = []
    for file_path in state_file_paths:
        with open(file_path, encoding="UTF-8") as f:
            all_sc_states.append(json.load(f))

    return all_sc_states


class ChainSimulator:
    def __init__(self, docker_path: Path = None):
        self.docker_path = docker_path
        self.proxy_url = SIMULATOR_URL
        self.api_url = API_URL
        self.process = None

        try:
            network_config = ProxyNetworkProvider(self.proxy_url).get_network_config()
            self.blocks_per_epoch = int(network_config.raw["erd_rounds_per_epoch"])
        except Exception:
            self.blocks_per_epoch = BLOCKS_PER_EPOCH
            logger.warning(
                "Could not get blocks per epoch from network config, using default value."
            )

    def start(self, block: int = 0, round: int = 0, epoch: int = 0):
        p = subprocess.Popen(["docker", "compose", "down"], cwd=self.docker_path)
        p.wait()
        p.terminate()

        # alter docker-compose.yml to start with the correct block, round and epoch & add other necessary mods
        self._update_docker_compose(block, round, epoch)
        self.process = subprocess.Popen(["docker", "compose", "up", "-d"], cwd=self.docker_path)
        time.sleep(30)
        return self.process

    def stop(self):
        if self.process:
            self.process.terminate()
        # go nuclear on anything that might be running
        p = subprocess.Popen(["docker", "compose", "down"], cwd=self.docker_path)
        p.wait()

    def is_running(self) -> bool:
        process_running = self.process is not None and self.process.poll() is None
        instance_running = False
        if not process_running:
            # check if started before creating the instance
            proxy = ProxyNetworkProvider(self.proxy_url)
            try:
                proxy.get_network_status()
                instance_running = True
            except Exception:
                pass
        return process_running or instance_running

    # Maximum storage keys per set-state request. Larger payloads cause the
    # chain simulator to silently fail or create storage that the VM trie
    # cannot access for cross-contract reads.
    STATE_CHUNK_SIZE = 10000

    def _send_single_state(self, state_entry: dict[str, Any]) -> bool:
        """Send a single contract state, chunking storage keys if needed.

        For contracts with many storage keys (>STATE_CHUNK_SIZE), the keys are
        split into multiple set-state requests. Account metadata (code, balance,
        ownerAddress) is sent first, then storage keys in chunks. The chain
        simulator's set-state API merges fields, so each chunk adds to the
        existing trie.

        Args:
            state_entry: Contract state dict with optional 'pairs' storage keys

        Returns:
            True if all requests succeeded
        """
        pairs = state_entry.get("pairs", {})
        if len(pairs) <= self.STATE_CHUNK_SIZE:
            # Small enough to send in one request
            response = requests.post(f"{self.proxy_url}/simulator/set-state", json=[state_entry])
            if response.status_code != 200:
                logger.error(f"Failed to apply state: {response.text}")
                return False
            return True

        address = state_entry.get("address", "unknown")
        logger.info(
            f"Chunking {len(pairs)} storage keys for {address} ({len(pairs) // self.STATE_CHUNK_SIZE + 1} chunks)"
        )

        # Send account metadata first (code, balance, etc.) without storage keys
        account_entry = {k: v for k, v in state_entry.items() if k != "pairs"}
        response = requests.post(f"{self.proxy_url}/simulator/set-state", json=[account_entry])
        if response.status_code != 200:
            logger.error(f"Failed to apply account metadata: {response.text}")
            return False

        # Send storage keys in chunks
        keys_list = list(pairs.items())
        for start in range(0, len(keys_list), self.STATE_CHUNK_SIZE):
            chunk = dict(keys_list[start : start + self.STATE_CHUNK_SIZE])
            response = requests.post(
                f"{self.proxy_url}/simulator/set-state",
                json=[
                    {
                        "address": state_entry["address"],
                        "pairs": chunk,
                    }
                ],
            )
            if response.status_code != 200:
                logger.error(f"Failed to apply storage chunk at offset {start}: {response.text}")
                return False

        # Re-apply code + owner after chunked loading to ensure they weren't cleared
        response = requests.post(f"{self.proxy_url}/simulator/set-state", json=[account_entry])
        if response.status_code != 200:
            logger.error(f"Failed to re-apply account metadata: {response.text}")
            return False

        logger.info(f"Loaded {len(pairs)} storage keys for {address}")
        return True

    def apply_states(self, states: list[list[dict[str, Any]]]):
        for state_batch in states:
            for state_entry in state_batch:
                if not self._send_single_state(state_entry):
                    return False
        return True

    def init_state_from_folder(
        self, state_folder: Path, filter_safe_price: bool = False
    ) -> list[str]:
        """Load all contract and account states from a folder into the chain simulator.

        Args:
            state_folder: Path to folder containing state JSON files
            filter_safe_price: If True, remove safe price observation keys from contract
                state before loading. This prevents "cast to i64 error" when mainnet state
                has round numbers higher than the chain simulator's current round.

        Returns:
            List of loaded user addresses (bech32)
        """
        all_sc_states = get_all_sc_states_in_folder(state_folder)
        user_addresses, contract_addresses = get_standalone_addresses_in_folder(state_folder)
        all_user_states = get_address_states_in_folder(state_folder, user_addresses)
        all_standalone_contract_states = get_address_states_in_folder(
            state_folder, contract_addresses
        )

        if filter_safe_price:
            total_removed = 0
            for sc_states in all_sc_states:
                _, removed = filter_safe_price_keys(sc_states)
                total_removed += removed
            for contract_states in all_standalone_contract_states:
                _, removed = filter_safe_price_keys(contract_states)
                total_removed += removed
            if total_removed:
                logger.info(f"Filtered {total_removed} safe price storage keys from loaded state")

        # Override firstWeekStartEpoch to 0 so chain simulator only needs epoch 7+
        total_overridden = 0
        for sc_states in all_sc_states:
            _, overridden = override_first_week_start_epoch(sc_states)
            total_overridden += overridden
        for contract_states in all_standalone_contract_states:
            _, overridden = override_first_week_start_epoch(contract_states)
            total_overridden += overridden
        if total_overridden:
            logger.info(f"Overrode firstWeekStartEpoch in {total_overridden} contract(s)")

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

    def ensure_pair_template_has_code(self, router_address: str, source_pair_address: str):
        """Ensure the Router's pair template contract has bytecode loaded.

        The Router's createPair uses deployFromSourceContract to clone the pair template.
        When loading mainnet state, the template contract's bytecode may not be included
        in the state dump. This method copies bytecode from an existing pair contract
        to the template address via the set-state API.

        Args:
            router_address: Bech32 address of the Router contract
            source_pair_address: Bech32 address of an existing pair contract to copy code from
        """
        from utils.contract_data_fetchers import RouterContractDataFetcher

        # 1. Query Router for pair template address
        fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_address), self.proxy_url)
        template_hex = fetcher.get_data("getPairTemplateAddress")
        if not template_hex:
            logger.warning("Router returned empty pair template address")
            return
        template_address = Address(bytes.fromhex(template_hex), "erd").to_bech32()

        # 2. Check if template already has code
        resp = requests.get(f"{self.proxy_url}/address/{template_address}")
        template_acct = resp.json()["data"]["account"]
        if template_acct.get("code"):
            logger.info(f"Pair template already has code at {template_address}")
            return

        # 3. Copy code from source pair contract
        resp = requests.get(f"{self.proxy_url}/address/{source_pair_address}")
        source_acct = resp.json()["data"]["account"]
        if not source_acct.get("code"):
            logger.warning(f"Source pair {source_pair_address} has no code to copy")
            return

        state = [
            {
                "address": template_address,
                "nonce": 0,
                "balance": "0",
                "code": source_acct["code"],
                "codeHash": source_acct["codeHash"],
                "codeMetadata": source_acct["codeMetadata"],
                "ownerAddress": source_acct["ownerAddress"],
                "developerReward": "0",
            }
        ]

        resp = requests.post(f"{self.proxy_url}/simulator/set-state", json=state)
        if resp.status_code == 200:
            logger.info(f"Loaded pair template bytecode at {template_address}")
            self.advance_blocks(1)  # Finalize state change
        else:
            logger.error(f"Failed to load pair template bytecode: {resp.text}")

    def advance_nonce_for_deploys(self, contract_address: str):
        """Advance a deployer contract's nonce to a session-unique value.

        Prevents "cannot deploy over existing account" errors when the same
        docker session is reused across multiple test runs. Chain simulator
        retains deployed contract bytecode between runs; when mainnet state
        is reloaded the router nonce resets to ~684, which would cause the
        next createPair to target an address already occupied by a prior run.

        Uses the current Unix timestamp to produce a nonce unique to this
        second-level time slot (range 10,000,000 – 19,999,999). Collision
        probability is negligible for typical CI/dev workflows.

        Only advances if the current nonce is below the computed value.
        """
        import time

        proxy = ProxyNetworkProvider(self.proxy_url)
        try:
            acct = proxy.get_account(Address.new_from_bech32(contract_address))
            session_nonce = int(time.time()) % 10_000_000 + 10_000_000
            if acct.nonce < session_nonce:
                self.apply_states([[{"address": contract_address, "nonce": session_nonce}]])
                logger.info(
                    f"Advanced {contract_address} nonce from {acct.nonce} to {session_nonce} for deploy isolation"
                )
        except Exception as exc:
            logger.warning(f"Could not advance nonce for {contract_address}: {exc}")

    def advance_blocks(self, number_of_blocks: int):
        url = f"{self.proxy_url}/simulator/generate-blocks/{number_of_blocks}"
        response = requests.post(url)
        return response.json()

    def generate_blocks_until_tx_processed(self, tx_hash: str, max_num_blocks: int = 30):
        """Generate blocks until a transaction is fully processed (cross-shard included).

        Uses the chain simulator's dedicated endpoint that generates blocks on ALL shards
        until the transaction reaches a final state (success or failure).

        Args:
            tx_hash: Transaction hash to wait for
            max_num_blocks: Maximum blocks to generate before stopping (default 30)
        """
        url = f"{self.proxy_url}/simulator/generate-blocks-until-transaction-processed/{tx_hash}"
        if max_num_blocks != 20:  # 20 is the server default
            url += f"?maxNumBlocks={max_num_blocks}"
        response = requests.post(url)
        return response.json()

    def advance_epochs(self, number_of_epochs: int):
        blocks_to_advance = self.blocks_per_epoch * number_of_epochs
        return self.advance_blocks(blocks_to_advance)

    def advance_epochs_to_epoch(self, target_epoch: int, chunk_size: int = 500):
        """Advance the chain simulator to a specific epoch.

        Uses the dedicated /simulator/generate-blocks-until-epoch-reached endpoint
        which handles epoch transitions internally. For large jumps, advances in
        chunks to avoid HTTP 500 errors from generating too many blocks at once.

        Args:
            target_epoch: Target epoch number to reach
            chunk_size: Maximum epochs to advance per API call (default 500)
        """
        proxy = ProxyNetworkProvider(self.proxy_url)
        current_epoch = proxy.get_network_status().current_epoch
        if current_epoch >= target_epoch:
            return None

        logger.info(f"Advancing from epoch {current_epoch} to {target_epoch}...")
        while current_epoch < target_epoch:
            chunk_target = min(current_epoch + chunk_size, target_epoch)
            url = f"{self.proxy_url}/simulator/generate-blocks-until-epoch-reached/{chunk_target}"
            response = requests.post(url)
            if response.status_code != 200:
                logger.warning(f"Epoch advancement returned {response.status_code}, retrying...")
            current_epoch = proxy.get_network_status().current_epoch
            logger.info(f"  ... reached epoch {current_epoch}")

        return current_epoch

    def _update_docker_compose(self, block: int, round: int, epoch: int):
        # Load the docker-compose.yaml file
        with open(self.docker_path / "docker-compose.yaml") as file:
            docker_compose = yaml.safe_load(file)

        # Locate the chain-simulator service
        chain_simulator = docker_compose["services"].get("chain-simulator", {})

        # Update the entrypoint — supernova image doesn't have the old config
        # file paths; skip sed commands and non-zero initial epoch/round/nonce
        # (non-zero values break cross-shard transactions permanently).
        chain_simulator["entrypoint"] = (
            f'/bin/bash -c "./start-with-services.sh -log-level *:INFO --rounds-per-epoch={BLOCKS_PER_EPOCH} --initial-round={round} --initial-nonce={block} --initial-epoch={epoch}"'
        )

        # Save the modified docker-compose.yaml file
        with open(self.docker_path / "docker-compose.yaml", "w") as file:
            yaml.dump(docker_compose, file, default_flow_style=False, sort_keys=False)

        logger.info(
            f"Updated {self.docker_path / 'docker-compose.yaml'} with block {block}, round {round}, epoch {epoch}."
        )

    def ensure_contract_state_from_mainnet(
        self,
        contract_address: str,
        mainnet_gateway: str = "https://gateway.multiversx.com",
        filter_first_week_epoch: bool = True,
        filter_boosted_yields_weeks: bool = False,
        reset_last_reward_timestamps: bool = False,
    ):
        """Load a contract's full state (bytecode + storage) from mainnet onto the chain simulator.

        Checks if the contract has code on the chain sim. If not, fetches the account data
        and all storage keys from the mainnet gateway and loads them via set-state API.
        Optionally overrides firstWeekStartEpoch to 0 for boosted contracts.
        Optionally removes boosted yields week-dependent keys that reference mainnet week
        numbers incompatible with chain simulator epochs.

        Args:
            contract_address: Bech32 address of the contract
            mainnet_gateway: Mainnet proxy gateway URL
            filter_first_week_epoch: If True, override firstWeekStartEpoch to 0
            filter_boosted_yields_weeks: If True, remove all boosted yields week keys
            reset_last_reward_timestamps: If True, reset lastRewardTimestamp and
                lastRewardBlockNonce to 0. Required when chain sim starts at round 0
                (timestamp ~0) but mainnet state has high Unix timestamps — without
                this, elapsed = 0 - mainnet_timestamp wraps to a huge u64, exhausting
                the reward capacity instantly on the first claim.
        """
        # 1. Check if contract already has code on chain sim
        resp = requests.get(f"{self.proxy_url}/address/{contract_address}")
        if resp.status_code != 200:
            logger.warning(f"Cannot check contract {contract_address}: {resp.status_code}")
            return False
        local_acct = resp.json()["data"]["account"]
        if local_acct.get("code"):
            logger.info(f"Contract {contract_address} already has code on chain sim")
            return True

        # 2. Fetch account data from mainnet
        logger.info(f"Fetching contract state from mainnet: {contract_address}")
        mainnet_proxy = ProxyNetworkProvider(mainnet_gateway)

        # Get account data (code, balance, nonce, etc.)
        account_data = get_account_data_online(contract_address, mainnet_gateway)
        if not account_data or not account_data.get("code"):
            logger.error(f"Contract {contract_address} has no code on mainnet")
            return False

        # Get all storage keys
        keys = get_account_keys_online(contract_address, mainnet_gateway)

        # 3. Apply filtering
        if filter_first_week_epoch and keys:
            if FIRST_WEEK_START_EPOCH_KEY in keys:
                old_value = keys[FIRST_WEEK_START_EPOCH_KEY]
                keys[FIRST_WEEK_START_EPOCH_KEY] = ""
                logger.info(
                    f"Overrode firstWeekStartEpoch for {contract_address}: {old_value} -> 0"
                )

        if filter_boosted_yields_weeks and keys:
            keys_to_remove = [
                k
                for k in keys
                if any(k.startswith(prefix) for prefix in BOOSTED_YIELDS_WEEK_KEY_PREFIXES)
            ]
            for k in keys_to_remove:
                del keys[k]
            if keys_to_remove:
                logger.info(
                    f"Filtered {len(keys_to_remove)} boosted yields week keys for {contract_address}"
                )

        if reset_last_reward_timestamps and keys:
            for key_variants, label in [
                (LAST_REWARD_TIMESTAMP_KEYS, "lastRewardTimestamp"),
                (LAST_REWARD_BLOCK_NONCE_KEYS, "lastRewardBlockNonce"),
            ]:
                for key in key_variants:
                    if key in keys:
                        old_value = keys[key]
                        keys[key] = ""
                        logger.info(f"Reset {label} for {contract_address}: {old_value} -> 0")

        # 4. Build set-state payload
        account_data.pop("rootHash", None)
        state_entry = {
            "address": contract_address,
            "nonce": account_data.get("nonce", 0),
            "balance": account_data.get("balance", "0"),
            "code": account_data.get("code", ""),
            "codeHash": account_data.get("codeHash", ""),
            "codeMetadata": account_data.get("codeMetadata", ""),
            "ownerAddress": account_data.get("ownerAddress", ""),
            "developerReward": account_data.get("developerReward", "0"),
        }
        if keys:
            state_entry["pairs"] = keys

        # 5. Load onto chain sim (auto-chunks large storage)
        if self._send_single_state(state_entry):
            self.advance_blocks(1)
            return True
        logger.error(f"Failed to load contract state for {contract_address}")
        return False

    def fund_users_w_egld(self, users: list[str], amount: int):
        for user in users:
            self.apply_states(
                [
                    [
                        {
                            "address": user,
                            "balance": str(amount),
                        }
                    ]
                ]
            )
        logger.debug(f"Funded {len(users)} users with {amount} EGLD")

    def fund_users_w_esdt_from_mainnet(self, users: list[str], esdt: str, amount: int):
        from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider

        from utils.utils_chain import dec_to_padded_hex

        mainnet_proxy = ProxyNetworkProvider("https://gateway.multiversx.com")
        mainnet_api = ApiNetworkProvider("https://api.multiversx.com")

        # find holder account on mainnet
        holder_accounts = mainnet_api.do_get_generic(f"tokens/{esdt}/accounts")
        holder_account = None
        for account in holder_accounts:
            address = account.get("address")
            if WrapperAddress(address).is_smart_contract():
                continue
            holder_account = address
            break
        if not holder_account:
            raise Exception("No holder account found")

        # fund users on chain simulator
        current_entry = mainnet_proxy.get_account_storage_entry(
            WrapperAddress(holder_account), f"ELRONDesdt{esdt}"
        )
        if not current_entry:
            raise Exception("No entry found")
        header = current_entry.value.hex()[:2]
        new_entry = f"{header}{dec_to_padded_hex(len(dec_to_padded_hex(amount)) // 2 + 1)}{'00'}{dec_to_padded_hex(amount)}"

        for user in users:
            self.apply_states(
                [[{"address": user, "pairs": {current_entry.key.encode().hex(): new_entry}}]]
            )
        logger.debug(f"Funded {len(users)} users with {amount} {esdt}")


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
        "block": response.highest_final_block_nonce,
    }

    return response_dict


def get_contract_retrieval_labels(contracts: str) -> list[str]:
    labels = []
    base_labels = [
        config.EGLD_WRAPS,
        config.LOCKED_ASSETS,
        config.SIMPLE_LOCKS_ENERGY,
        config.UNSTAKERS,
        config.FEES_COLLECTORS,
        config.ROUTER_V2,
    ]
    if contracts == "base":
        return base_labels
    if contracts == "all":
        labels.extend(base_labels)
        labels.extend(
            [
                config.PROXIES,
                config.PROXIES_V2,
                config.PAIRS_V2,
                config.FARMS_V2,
                config.STAKINGS_V2,
                config.METASTAKINGS_V2,
                config.STAKINGS_BOOSTED,
                config.METASTAKINGS_BOOSTED,
                config.ESCROWS,
                config.LK_WRAPS,
                config.POSITION_CREATOR,
                config.GOVERNANCES,
                config.PRICE_DISCOVERIES,
                config.SIMPLE_LOCKS,
            ]
        )
        return labels
    return contracts.split(",")


def get_context_used_tokens(context: Context) -> list[str]:
    contract_tokens = []
    for contract_label in context.deploy_structure.contracts:
        for contract in context.get_contracts(contract_label):
            contract_tokens.extend(contract.get_contract_tokens())
    return contract_tokens


def fetch_account_state(
    address: str, proxy: ProxyNetworkProvider, block_number: int, file_label: str, file_index: int
) -> dict[str, Any]:
    keys_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_state.json"
    data_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_data.json"
    chain_config_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_{file_label}_{file_index}_chain_config_state.json"
    keys = get_account_keys_online(address, proxy.url, block_number, keys_file, paginated=False)
    data = get_account_data_online(address, proxy.url, block_number, data_file)
    data.pop("rootHash", None)  # remove rootHash from data

    account_state = {}
    account_state.update(data)
    account_state["pairs"] = keys

    # save account chain config state to file
    with open(chain_config_file, "w", encoding="UTF-8") as state_writer:
        json.dump([account_state], state_writer, indent=4)
    logger.info(f"Chain config account state for {address} has been saved to {chain_config_file}.")

    return account_state


def get_token_key_hex(token: ESDTToken) -> str:
    return f"{string_to_hex('ELRONDesdt')}{string_to_hex(token.token_id)}"


def get_token_nonce_key_hex(token: ESDTToken) -> str:
    return f"{get_token_key_hex(token)}{token.get_token_nonce_hex()}"


def fetch_token_system_account_attributes(
    proxy: ProxyNetworkProvider, token: ESDTToken, block_number: int = 0
) -> dict[str, str]:
    block_param = f"?blockNonce={block_number}" if block_number else ""
    key = get_token_key_hex(token)
    resource_url = f"address/erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t/key/{key}{block_param}"
    response = proxy.do_get_generic(resource_url)
    return {key: response.get("value", "")}


def fetch_token_nonce_system_account_attributes(
    proxy: ProxyNetworkProvider, token: ESDTToken, block_number: int = 0
) -> dict[str, str]:
    block_param = f"?blockNonce={block_number}" if block_number else ""
    key = get_token_nonce_key_hex(token)
    resource_url = f"address/erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t/key/{key}{block_param}"
    response = proxy.do_get_generic(resource_url)
    return {key: response.get("value", "")}


def fetch_context_system_account_state_from_account(
    proxy: ProxyNetworkProvider, context: Context, address: str, block_number: int = 0
) -> dict[str, Any]:
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

    logger.debug(
        f"Starting retrieval of system account keys for context related meta esdts owned by {address}."
    )
    logger.debug(f"Number of meta esdt tokens found in account: {len(user_tokens)}")
    for token in user_tokens:
        print(
            f"\rProcessing token {user_tokens.index(token) + 1}/{len(user_tokens)}",
            end="",
            flush=True,
        )  # this can take a while depending on the number of tokens

        temp_token = ESDTToken.from_full_token_name(token.token.identifier)
        if temp_token.token_id not in context_tokens:
            continue
        sys_account_token_attributes = fetch_token_nonce_system_account_attributes(
            proxy, temp_token, block_number
        )
        sys_account_keys.update(sys_account_token_attributes)
    print()  # new line after progress bar

    sys_account_state = {
        "address": "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t",
        "pairs": sys_account_keys,
    }

    # save system account state to file
    sys_account_state_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_system_account_state_{address}.json"
    with open(sys_account_state_file, "w", encoding="UTF-8") as state_writer:
        json.dump([sys_account_state], state_writer, indent=4)
    logger.info(
        f"System account state for tokens in {address} has been saved to {sys_account_state_file}."
    )

    return sys_account_state


def fetch_system_account_state_from_token(
    token: str, proxy: ProxyNetworkProvider, block_number: int = 0
) -> dict[str, Any]:
    sys_account_keys = fetch_token_nonce_system_account_attributes(
        proxy, ESDTToken.from_full_token_name(token), block_number
    )

    # TODO: need a fix below to uncomment the fetch_token_system_account_attributes function;
    # TODO: transfer roles on chain simulator don't work correctly if this is active, but without it, some roles can't be correctly assigned
    # sys_account_keys.update(fetch_token_system_account_attributes(proxy, ESDTToken.from_full_token_name(token), block_number))

    sys_account_state = {
        "address": "erd1lllllllllllllllllllllllllllllllllllllllllllllllllllsckry7t",
        "pairs": sys_account_keys,
    }

    # save system account state to file
    sys_account_state_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_system_account_state_{token}.json"
    with open(sys_account_state_file, "w", encoding="UTF-8") as state_writer:
        json.dump([sys_account_state], state_writer, indent=4)
    logger.info(f"System account state for {token} has been saved to {sys_account_state_file}.")

    return sys_account_state


def compose_system_account_state_from_contract_state(
    contract: DEXContractInterface,
    contract_state: dict[str, Any],
    proxy: ProxyNetworkProvider,
    block_number: int = 0,
) -> dict[str, Any]:
    """
    Compose system account state from contract state by searching for meta esdts for which the contract is the creator (not owner).
    It looks for the existence of the last nonce of each token and fetches the system account state for that nonce.
    """
    system_account_state = {}
    tokens = contract.get_contract_tokens()

    for token in tokens:
        # Convert 'ELRONDnonce' and token name to hex
        elrond_nonce_hex = string_to_hex("ELRONDnonce")
        token_hex = string_to_hex(token)
        search_key = f"{elrond_nonce_hex}{token_hex}"

        # Search through contract state keys
        if search_key in contract_state["pairs"].keys():
            # Found matching key, get nonce value and fetch system account state
            nonce = contract_state["pairs"][search_key]

            token_with_nonce = f"{token}-{nonce}"
            token_system_account_state = fetch_system_account_state_from_token(
                token_with_nonce, proxy, block_number
            )
            # Merge the pairs from token_system_account_state into system_account_state
            if not system_account_state:
                system_account_state = token_system_account_state
            else:
                system_account_state["pairs"].update(token_system_account_state["pairs"])

    return system_account_state


def fetch_contract_states(
    context: Context, args, proxy: ProxyNetworkProvider, block_number: int = 0
) -> dict[str, Any]:
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
            system_account_state = compose_system_account_state_from_contract_state(
                contract, account_state, proxy, block_number
            )
            if system_account_state:
                all_keys.append(system_account_state)

            # get system account state for all the context related meta esdts the contract owns
            system_account_state = fetch_context_system_account_state_from_account(
                proxy, context, contract.address, block_number
            )
            if system_account_state:
                all_keys.append(system_account_state)

    # get ESDT issue account state
    logger.info("Retrieving state for ESDT issue account.")
    account_state = fetch_account_state(
        config.TOKENS_CONTRACT_ADDRESS, proxy, block_number, "esdt_issue", 0
    )
    if account_state:
        all_keys.append(account_state)

    # dump all keys to a file
    all_keys_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_{args.contracts}_all_keys.json"
    with open(all_keys_file, "w", encoding="UTF-8") as state_writer:
        json.dump(all_keys, state_writer, indent=4)
    logger.info(
        f"State for {args.contracts} contracts has been retrieved and saved to {all_keys_file}."
    )

    chronology = get_current_shard_chronology(proxy, contracts_shard)
    logger.info(f"Current shard chronology: {chronology}")
    # save chronology to file
    chronology_file = f"{config.DEFAULT_WORKSPACE.absolute()}/{STATES_FOLDER}/{block_number}_shard_chronology.json"
    with open(chronology_file, "w", encoding="UTF-8") as chronology_writer:
        json.dump(chronology, chronology_writer, indent=4)
    logger.info(f"Shard chronology has been saved to {chronology_file}.")

    return all_keys


def fetch_user_state_with_tokens(
    user_address: str, context: Context, proxy: ProxyNetworkProvider, block_number: int = 0
) -> dict[str, Any]:
    address = WrapperAddress(user_address)

    # get user account state
    _ = fetch_account_state(address.bech32(), proxy, block_number, user_address, 0)

    # compose system account token attributes
    _ = fetch_context_system_account_state_from_account(
        proxy, context, address.bech32(), block_number
    )


def retrieve_handler(args: Any):
    if not hasattr(args, "gateway") or not args.gateway:
        log_step_fail("Gateway is required. Please provide a gateway address.")
        return

    context = Context()
    proxy = ProxyNetworkProvider(args.gateway)
    # if block is not empty, use it to retrieve all state from that specific block
    contracts_shard = WrapperAddress(context.get_contracts(config.ROUTER_V2)[0].address).get_shard()
    if hasattr(args, "block") and args.block:
        block_number = get_retrieve_block(proxy, contracts_shard, int(args.block))
    else:
        block_number = 0

    if hasattr(args, "contracts") and args.contracts:
        if args.contract_index:
            if not args.contracts:
                log_step_fail(
                    "Contract index provided but no contracts to retrieve from. Please provide a specific type of contracts."
                )
                return
            if args.contracts == "base" or args.contracts == "all":
                log_step_fail(
                    "Contract index provided but contracts to retrieve from are not specific. Please provide a specific type of contracts."
                )
                return
            if "," in args.contracts:
                log_step_fail(
                    "Contract index provided but multiple contracts to retrieve from. Please provide a single contract label."
                )
                return

        fetch_contract_states(context, args, proxy, block_number)

    if hasattr(args, "account") and args.account:
        fetch_user_state_with_tokens(args.account, context, proxy, block_number)

    if hasattr(args, "token") and args.token:
        fetch_system_account_state_from_token(args.token, proxy, block_number)


def start_handler(args: Any) -> tuple[ChainSimulator, list[str]]:
    """
    Starts the chain simulator and loads all the contract and account states found in the default folder.
    """

    if (
        not hasattr(args, "docker_path")
        or not args.docker_path
        or not Path(args.docker_path).exists()
    ):
        log_step_fail(
            "Docker path is not provided or does not exist. Please provide a valid docker path."
        )
        return None
    if not hasattr(args, "state_path") or not args.state_path or not Path(args.state_path).exists():
        log_warning(
            f"State path is not provided or does not exist. Using default folder: {STATES_FOLDER}"
        )
        args.state_path = config.DEFAULT_WORKSPACE.absolute() / STATES_FOLDER

    chronology = get_shard_chronology_in_folder(Path(args.state_path))
    if not chronology:
        log_step_fail("Shard chronology file not found. Please provide a valid state path.")
        return None

    chain_sim = ChainSimulator(Path(args.docker_path))
    chain_sim.start(block=chronology["block"], round=chronology["round"], epoch=chronology["epoch"])
    found_accounts = chain_sim.init_state_from_folder(Path(args.state_path))

    return chain_sim, found_accounts


def main(cli_args: list[str]):
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    retrieve_parser = subparsers.add_parser("retrieve", help="retrive chain simulator states")
    retrieve_parser.add_argument("--gateway", required=False, default="")
    retrieve_parser.add_argument(
        "--block", required=False, default=""
    )  # 0 - frozen to last block, x - frozen to specific block number, empty - unfrozen
    retrieve_parser.add_argument(
        "--system-account", required=False, default="offline"
    )  # offline | online
    retrieve_parser.add_argument(
        "--contracts", required=False, default=""
    )  # all | base | comma separated labels of contracts
    retrieve_parser.add_argument(
        "--contract-index", required=False, default=""
    )  # index of contract to retrieve state from; should only be used in conjunction with one specific type of --contracts
    retrieve_parser.add_argument(
        "--account", required=False, default=""
    )  # explicit account address to retrieve state from
    retrieve_parser.add_argument(
        "--token", required=False, default=""
    )  # explicit token to retrieve sys account state for
    retrieve_parser.set_defaults(func=retrieve_handler)

    start_parser = subparsers.add_parser("start", help="start chain simulator")
    start_parser.add_argument(
        "--docker-path",
        required=False,
        default="",
        help="path to full stack chain simulator docker compose folder",
    )
    start_parser.add_argument(
        "--state-path",
        required=False,
        default="",
        help="path to folder where chain simulator states are saved",
    )
    start_parser.set_defaults(func=start_handler)

    args = parser.parse_args(cli_args)
    if not hasattr(args, "func"):
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
