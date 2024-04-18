from multiversx_sdk_network_providers import ProxyNetworkProvider
from utils.utils_chain import WrapperAddress as Address, get_all_token_nonces_details_for_account
from multiprocessing.dummy import Pool
from multiversx_sdk_network_providers.api_network_provider import ApiNetworkProvider
from multiversx_sdk_network_providers.interface import IPagination
from multiversx_sdk_network_providers.transactions import TransactionOnNetwork
from utils.logger import get_logger
from typing import List


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

class Pagination(IPagination):
    def __init__(self, start: int, size: int) -> None:
        self.start = start
        self.size = size

    def get_start(self) -> int:
        return self.start

    def get_size(self) -> int:
        return self.size
    

def collect_farm_contract_users(users_count: int, 
                                contract_address: str, farming_token: str, farm_token: str, 
                                source_api: ApiNetworkProvider,
                                dest_proxy: ProxyNetworkProvider) -> FetchedUsers:
    logger.info(f'Collecting users from farm contract {contract_address} ...')

    transactions = source_api.get_account_transactions(Address(contract_address), Pagination(0, users_count))

    fetched_users = FetchedUsers()
    set_users = set()

    def process_tx(tx: TransactionOnNetwork):
        user = tx.sender
        
        # avoid duplicates
        if user.bech32() in set_users:
            return
        set_users.add(user.bech32())

        logger.debug(f'Processing user {user.bech32()} ...')
        try:
            farming_tokens_in_account = get_all_token_nonces_details_for_account(farming_token, user.bech32(), dest_proxy)
            farm_tokens_in_account = get_all_token_nonces_details_for_account(farm_token, user.bech32(), dest_proxy)

            if len(farming_tokens_in_account) > 0 or len(farm_tokens_in_account) > 0:
                fetched_users.add_user(FetchedUser(user, farming_tokens_in_account, farm_tokens_in_account))
        except Exception as e:
            logger.warning(f'Error processing user {user.bech32()}: {e}')

    Pool(10).map(process_tx, transactions)

    logger.info(f'Number of users fetched: {len(fetched_users.users)}')
    logger.info(f'Number of users with farming tokens: {len(fetched_users.get_users_with_farming_tokens())}')
    logger.info(f'Number of users with farm tokens: {len(fetched_users.get_users_with_farm_tokens())}')
    logger.info(f'Number of users with both farming and farm tokens: {len(fetched_users.get_users_with_both_tokens())}')

    return fetched_users