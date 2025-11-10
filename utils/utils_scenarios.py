from multiversx_sdk import ProxyNetworkProvider, ApiNetworkProvider
from utils.utils_chain import Account, WrapperAddress as Address, get_all_token_nonces_details_for_account, get_token_details_for_address
from multiprocessing.dummy import Pool
from multiversx_sdk import TransactionOnNetwork
from utils.logger import get_logger
from typing import Dict, Any, List, Tuple, Optional
from collections import defaultdict


logger = get_logger(__name__)


class FetchedUser:
    def __init__(self, address: Address, farming_tokens: list, farm_tokens: list) -> None:
        self.address = address
        self.farming_tokens = farming_tokens
        self.farm_tokens = farm_tokens

    def __str__(self) -> str:
        return f'Address: {self.address.bech32()}\nFarming tokens: {self.farming_tokens}\nFarm tokens: {self.farm_tokens}'

    def __repr__(self) -> str:
        return self.__str__()
    
class FetchedUsers:
    def __init__(self) -> None:
        self.users: List[FetchedUser] = []

    def add_user(self, user: FetchedUser) -> None:
        # check if user already exists
        if user.address in [user.address for user in self.users]:
            return
        self.users.append(user)

    def address_exists(self, address: Address) -> bool:
        return address in [user.address for user in self.users]

    # getter for users having farming tokens
    def get_users_with_farming_tokens(self) -> list:
        return [user for user in self.users if len(user.farming_tokens) > 0]
    
    # getter for users having farm tokens
    def get_users_with_farm_tokens(self) -> list:
        return [user for user in self.users if len(user.farm_tokens) > 0]
    
    # getter for users having more than one farm tokens
    def get_users_with_multiple_farm_tokens(self) -> list:
        return [user for user in self.users if len(user.farm_tokens) > 1]
    
    # getter for users having both farming and farm tokens
    def get_users_with_both_tokens(self) -> list:
        return [user for user in self.users if len(user.farming_tokens) > 0 and len(user.farm_tokens) > 0]

    def __str__(self) -> str:
        return '\n'.join([str(user) for user in self.users])

    def __repr__(self) -> str:
        return self.__str__()

class Pagination:
    def __init__(self, start: int, size: int) -> None:
        self.start = start
        self.size = size

    def get_start(self) -> int:
        return self.start

    def get_size(self) -> int:
        return self.size
    
    def get_pagination_dict(self) -> dict[str, int]:
        return {
            "from": self.start,
            "size": self.size
        }
    

def collect_farm_contract_users(users_count: int, 
                                contract_address: str, farming_token: str, farm_token: str, 
                                source_api: ApiNetworkProvider,
                                dest_proxy: ProxyNetworkProvider,
                                users_pagination_start: int = 0) -> FetchedUsers:
    logger.info(f'Collecting users from farm contract {contract_address} ...')

    pagination = Pagination(users_pagination_start, users_count)
    transactions = source_api.get_transactions(Address(contract_address), pagination.get_pagination_dict())

    fetched_users = FetchedUsers()
    set_users = set()

    def process_tx(tx: TransactionOnNetwork):
        user = Address(tx.sender.to_bech32())
        
        # avoid duplicates
        if user.to_bech32() in set_users:
            return
        set_users.add(user.to_bech32())

        logger.debug(f'Processing user {user.to_bech32()} ...')
        try:
            farming_tokens_in_account = get_all_token_nonces_details_for_account(farming_token, user.to_bech32(), dest_proxy)
            farm_tokens_in_account = get_all_token_nonces_details_for_account(farm_token, user.to_bech32(), dest_proxy)

            if len(farming_tokens_in_account) > 0 or len(farm_tokens_in_account) > 0:
                fetched_users.add_user(FetchedUser(user, farming_tokens_in_account, farm_tokens_in_account))
        except Exception as e:
            logger.warning(f'Error processing user {user.to_bech32()}: {e}')

    Pool(10).map(process_tx, transactions)

    logger.info(f'Number of users fetched: {len(fetched_users.users)}')
    logger.info(f'Number of users with farming tokens: {len(fetched_users.get_users_with_farming_tokens())}')
    logger.info(f'Number of users with farm tokens: {len(fetched_users.get_users_with_farm_tokens())}')
    logger.info(f'Number of users with both farming and farm tokens: {len(fetched_users.get_users_with_both_tokens())}')

    return fetched_users


def get_token_in_account(proxy: ProxyNetworkProvider, user: Account, token: str, nonce: int = 0) -> Tuple[int, int, str]:
    """Retrieves the token nonce and amount in the account for a specific token or any token in the account"""
    token_nonce, token_amount, token_attributes = 0, 0, ""

    if nonce > 0:
        # looking for a specific token nonce
        token_nonce = nonce
        all_tokens = get_all_token_nonces_details_for_account(token, user.address.bech32(), proxy)
        for token in all_tokens:
            if token['nonce'] == token_nonce:
                token_amount = int(token['balance'])
    else:
        # looking for whatever token in account
        token_nonce, token_amount, token_attributes = get_token_details_for_address(token, user.address.bech32(), proxy)

    return token_nonce, token_amount, token_attributes


class PhaseDictsCollector():
    def __init__(self):
        self.reset()
        self.dict_types = set()

    def reset(self):
        """Reset all collections for a new scenario"""
        self.collections: Dict[str, Dict[str, List[Tuple[Dict[str, Any], str]]]] = {}
        self.current_phase = None
    
    def set_phase(self, phase: str):
        """Set the current collection phase"""
        if not isinstance(phase, str):
            raise ValueError("Phase must be a string")
        if phase not in self.collections:
            self.collections[phase] = defaultdict(list)
        self.current_phase = phase

    def add(self, dict_type: str, dict_data: Dict[str, Any], description: str = ""):
        """Add a dictionary to the current phase collection"""
        if self.current_phase is None:
            raise ValueError("No phase set. Call set_phase() first.")
        if dict_type in self.collections[self.current_phase]:
            raise ValueError(f"Dict type {dict_type} already exists in phase {self.current_phase}")
        
        self.collections[self.current_phase][dict_type].append((dict_data, description))
        self.dict_types.add(dict_type)

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

    def compare_phases(self, phase1: str, phase2: str) -> List[str]:
        """
        Compare collections between two specific phases and return a list of differences found.
        """
        if phase1 not in self.collections or phase2 not in self.collections:
            raise ValueError(f"One or both phases not found: {phase1}, {phase2}")

        differences = []

        for dict_type in self.dict_types:  # This will iterate over all enum values of the concrete type
            phase1_list = self.collections[phase1][dict_type]
            phase2_list = self.collections[phase2][dict_type]

            # Check if we have matching pairs
            if len(phase1_list) != len(phase2_list):
                differences.append(
                    f"{dict_type}: Mismatched number of collections - "
                    f"{phase1}: {len(phase1_list)}, {phase2}: {len(phase2_list)}"
                )
                continue

            # Compare each pair
            for i, ((dict1, desc1), (dict2, desc2)) in enumerate(zip(phase1_list, phase2_list)):
                is_equal, diff = self._compare_dicts(dict1, dict2)
                if not is_equal:
                    diff_msg = f"{dict_type} comparison failed"
                    if desc1 or desc2:
                        diff_msg += f" ({phase1}: {desc1}, {phase2}: {desc2})"
                    diff_msg += f": {diff}"
                    differences.append(diff_msg)

        return differences

    def compare_all(self) -> List[str]:
        """
        Compare all collected dictionary pairs between consecutive phases and return a list of differences found.
        """
        differences = []
        phases = sorted(self.collections.keys())
        
        if len(phases) < 2:
            return differences

        for i in range(len(phases) - 1):
            phase1, phase2 = phases[i], phases[i + 1]
            phase_differences = self.compare_phases(phase1, phase2)
            if phase_differences:
                differences.extend([f"Comparing {phase1} -> {phase2}: {diff}" for diff in phase_differences])

        return differences
    
    def print_collections(self):
        """
        Print a formatted view of all collections across all phases.
        """
        logger.info("\nCollections Summary:")
        logger.info("=" * 80)

        for phase in sorted(self.collections.keys()):
            logger.info(f"\nPhase: {phase}")
            logger.info("-" * 40)

            for dict_type in self.dict_types:  # This will iterate over all enum values of the concrete type
                collections_list = self.collections[phase][dict_type]

                if not collections_list:
                    logger.info(f"  No collections")
                    continue

                logger.info(f"\n{dict_type}:")
                logger.info("-" * 20)

                for i, (data, desc) in enumerate(collections_list, 1):
                    logger.info(f"  Collection {i}" + (f" ({desc})" if desc else ""))
                    if isinstance(data, dict):
                        for key, value in data.items():
                            logger.info(f"    {key}: {value}")
                    else:
                        logger.info(f"    {data}")

            logger.info("\n" + "=" * 80)

# Example usage:
"""
collector = PhaseDictsCollector()

# Phase 1
collector.set_phase("initial")
collector.add("USER_STATS", initial_stats, "Initial state")

# Phase 2
collector.set_phase("upgrade")
collector.add("USER_STATS", upgrade_stats, "During upgrade")

# Phase 3
collector.set_phase("final")
collector.add("USER_STATS", final_stats, "Final state")

# Compare specific phases
differences = collector.compare_phases("initial", "final")

# Or compare all phases in sequence
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

# Print all collections
collector.print_collections()

# Reset for next scenario
collector.reset()
"""