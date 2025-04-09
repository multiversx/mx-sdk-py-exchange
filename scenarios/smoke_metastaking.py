import config
import time
import pytest
import pprint
from typing import List, Tuple
from multiversx_sdk import ApiNetworkProvider
from context import Context
from utils.utils_chain import WrapperAddress, Account
from utils.utils_scenarios import get_token_in_account, collect_farm_contract_users, FetchedUser
from utils.utils_generic import get_logger
from utils.utils_tx import ESDTToken
from tools.runners.metastaking_runner import get_metastaking_v2_addresses, fetch_and_save_metastakings_from_chain
from contracts.metastaking_contract import MetaStakingContract, MetaStakingContractVersion
from scenarios.smoke_common import forge_user, collect_users_for_smoke_test, parameter_pairs


logger = get_logger("manual_interactor")


def claim_rewards_for_user(metastake_contract: MetaStakingContract, user: Account) -> str:
    token_nonce, token_balance, _ = get_token_in_account(context.network_provider.proxy, user, metastake_contract.metastake_token)
    if token_balance == 0:
        pytest.skip(f'No token balance for {user.address.bech32()} on {metastake_contract.address}')
    tokens = [ESDTToken(metastake_contract.metastake_token, token_nonce, token_balance)]
    
    return metastake_contract.claim_rewards_metastaking(context.network_provider.proxy, user, [tokens])

def enter_metastake_for_user(metastake_contract: MetaStakingContract, user: Account) -> str:
    token_nonce, token_balance, _ = get_token_in_account(context.network_provider.proxy, user, metastake_contract.farm_token)
    if token_balance == 0:
        pytest.skip(f'No token balance for {user.address.bech32()} on {metastake_contract.address}')
    tokens = [ESDTToken(metastake_contract.farm_token, token_nonce, token_balance)]

    metastake_token_nonce, metastake_token_balance, _ = get_token_in_account(context.network_provider.proxy, user, metastake_contract.metastake_token)
    if metastake_token_balance > 0:
        tokens.append(ESDTToken(metastake_contract.metastake_token, metastake_token_nonce, metastake_token_balance))
    
    return metastake_contract.enter_metastake(context.network_provider.proxy, user, [tokens])

def exit_metastake_for_user(metastake_contract: MetaStakingContract, user: Account) -> str:
    token_nonce, token_balance, _ = get_token_in_account(context.network_provider.proxy, user, metastake_contract.metastake_token)
    if token_balance == 0:
        pytest.skip(f'No token balance for {user.address.bech32()} on {metastake_contract.address}')
    tokens = [ESDTToken(metastake_contract.metastake_token, token_nonce, token_balance)]

    return metastake_contract.exit_metastake(context.network_provider.proxy, user, [tokens, 1, 1])


### SETUP ###

context = Context()
test_parameter_pairs = parameter_pairs(MetaStakingContract, context.network_provider.proxy)

### TESTS ###


@pytest.mark.parametrize("metastake_contract, user", test_parameter_pairs)
def test_claim_metastakingv2(metastake_contract: MetaStakingContract, user: Account):
    user.sync_nonce(context.network_provider.proxy)
    # claim rewards
    tx_hash = claim_rewards_for_user(metastake_contract, user)
    time.sleep(6 if user.address.get_shard() == 1 else 40)
    result = context.network_provider.check_complex_tx_status(tx_hash, "claim rewards")
    assert result, f"Claim rewards for {user.address.bech32()} on {metastake_contract.address} failed"


@pytest.mark.parametrize("metastake_contract, user", test_parameter_pairs)
def test_enter_metastakingv2(metastake_contract: MetaStakingContract, user: Account):
    user.sync_nonce(context.network_provider.proxy)
    # enter metastake
    tx_hash = enter_metastake_for_user(metastake_contract, user)
    time.sleep(6 if user.address.get_shard() == 1 else 40)
    result = context.network_provider.check_complex_tx_status(tx_hash, "enter metastake")
    assert result, f"Enter metastake for {user.address.bech32()} on {metastake_contract.address} failed"


@pytest.mark.parametrize("metastake_contract, user", test_parameter_pairs)
def test_exit_metastakingv2(metastake_contract: MetaStakingContract, user: Account):
    user.sync_nonce(context.network_provider.proxy)
    # exit metastake
    tx_hash = exit_metastake_for_user(metastake_contract, user)
    time.sleep(6 if user.address.get_shard() == 1 else 40)
    result = context.network_provider.check_complex_tx_status(tx_hash, "exit metastake")
    assert result, f"Exit metastake for {user.address.bech32()} on {metastake_contract.address} failed"