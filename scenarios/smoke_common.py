import config
import pprint
from typing import List, Tuple
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider
from utils.utils_chain import Account
from utils.utils_scenarios import collect_farm_contract_users, FetchedUser
from utils.utils_generic import get_logger
from tools.runners.metastaking_runner import get_metastaking_v2_addresses, fetch_and_save_metastakings_from_chain
from tools.runners.farm_runner import get_farm_addresses_from_chain
from tools.runners.staking_runner import get_staking_addresses_from_chain
from contracts.metastaking_contract import MetaStakingContract, MetaStakingContractVersion
from contracts.farm_contract import FarmContract, FarmContractVersion
from contracts.staking_contract import StakingContract, StakingContractVersion

logger = get_logger("manual_interactor")


def collect_users_for_smoke_test(contract_address: str, farming_token: str, farm_token: str, proxy: ProxyNetworkProvider) -> List[FetchedUser]:
    mainnet_api = ApiNetworkProvider("https://api.multiversx.com")
    fetched_users = collect_farm_contract_users(200, contract_address, farming_token, farm_token,
                                                mainnet_api, proxy)

    users: List[FetchedUser] = fetched_users.get_users_with_both_tokens()
    fetch_attempts = 0
    while not users and fetch_attempts < 5:
        fetched_users = collect_farm_contract_users(200, contract_address, farming_token, farm_token,
                                                    mainnet_api, proxy, fetch_attempts * 200)
        users: List[FetchedUser] = fetched_users.get_users_with_both_tokens()
        fetch_attempts += 1
    if not users:
        logger.warning(f"No users found with both tokens for {contract_address}")
        return fetched_users.get_users_with_farm_tokens()
    
    return users


def forge_user(user: FetchedUser, proxy: ProxyNetworkProvider) -> Account:
    user_account = Account(pem_file=config.DEFAULT_ACCOUNTS)
    user_account.address = user.address
    user_account.sync_nonce(proxy)
    return user_account


def parameter_pairs(type: type, proxy: ProxyNetworkProvider) -> List[Tuple[type, Account]]:
    if type == MetaStakingContract:
        fetch_and_save_metastakings_from_chain("")
        contract_addresses = get_metastaking_v2_addresses()
    elif type == FarmContract:
        contract_addresses = get_farm_addresses_from_chain("v2")
    elif type == StakingContract:
        contract_addresses = get_staking_addresses_from_chain()

    test_parameter_pairs = []
    for address in contract_addresses:
        if type == MetaStakingContract:
            contract = MetaStakingContract.load_contract_by_address(address, MetaStakingContractVersion.V3Boosted)
            farm_token = contract.metastake_token
            farming_token = contract.farm_token
        elif type == FarmContract:
            contract = FarmContract.load_contract_by_address(address, FarmContractVersion.V2Boosted)
            farm_token = contract.farmToken
            farming_token = contract.farmingToken
        elif type == StakingContract:
            contract = StakingContract.load_contract_by_address(address, StakingContractVersion.V2)
            farm_token = contract.farm_token
            farming_token = contract.farming_token
        pprint.pprint(contract.__dict__)

        # Collect users
        users = collect_users_for_smoke_test(address, farm_token, farming_token, proxy)
        if not users:
            logger.error(f"Skipping {address}")
            continue

        user = forge_user(users[0], proxy)
        test_parameter_pairs.append((contract, user))

    print(f"Done! Collected {len(test_parameter_pairs)} test parameter pairs out of {len(contract_addresses)} {type.__name__} addresses")
    return test_parameter_pairs