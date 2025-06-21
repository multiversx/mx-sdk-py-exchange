import json
from time import sleep
import pytest
import config
from pathlib import Path
from multiversx_sdk import ApiNetworkProvider, ProxyNetworkProvider
from context import Context

from contracts.farm_contract import FarmContract, EnterFarmEvent
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from events.farm_events import ClaimRewardsFarmEvent, ExitFarmEvent

from tools.automated_scenarios.conftest import ChainSimulatorControl, advance_blocks, advance_epoch, apply_states, dict_compare, load_and_apply_state, setup_chain_sim, users_init
from tools.automated_scenarios.config_data import USERS, PROJECT_ROOT, proxy, api, tx_hash
from tools.chain_simulator_connector import SIMULATOR_URL
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES
from utils.utils_chain import Account, WrapperAddress, base64_to_hex, decode_merged_attributes, get_all_token_nonces_details_for_account
from utils.utils_scenarios import get_token_in_account
from utils.utils_tx import ESDTToken

context = Context()
context.network_provider.proxy = proxy
context.network_provider.api = api
chain_control = ChainSimulatorControl()

energy_factory: SimpleLockEnergyContract
energy_factory = context.get_contracts(config.SIMPLE_LOCKS_ENERGY)[0]
#UTK FARM
farm_contract: FarmContract = context.deploy_structure.get_deployed_contract_by_index(config.FARMS_V2, 4)

wasm_path = "https://github.com/multiversx/mx-exchange-sc/releases/download/v3.3.1-rc1/farm-with-locked-rewards.wasm"
contract_code_hash = "78c4451db7425405e85b638a556043c143878ee1f3fc542f424d8f9aba1a61ee"

def claim_rewards(user: Account):
    user.sync_nonce(proxy)

    farm_tk_balance, farm_tk_nonce = 0, 0
    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmToken, user.address.bech32(), proxy)
    print(f'Found {len(tokens_in_account)} positions of {farm_contract.farmToken} in account')
    for token in tokens_in_account:
        if int(token['balance']) > farm_tk_balance:
            farm_tk_balance = int(token['balance'])
            farm_tk_nonce = token['nonce']
            break
    if not farm_tk_nonce:
        raise Exception("Not enough farm token balance")

    event = ClaimRewardsFarmEvent(farm_tk_balance, farm_tk_nonce, '')

    tx_hash = farm_contract.claimRewards(context.network_provider, user, event)
    advance_blocks(1)
    
    return tx_hash

def claim_boosted_rewards(user: Account):
    farm_tk_balance, farm_tk_nonce = 0, 0

    event = ClaimRewardsFarmEvent(farm_tk_balance, farm_tk_nonce, '')

    tx_hash = farm_contract.claim_boosted_rewards(context.network_provider, user, event)
    advance_blocks(1)

    return tx_hash

def enter_farm_new(user: Account):
    farming_tk_balance = 0
    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmingToken, user.address.bech32(), proxy)
    print(f'Found {len(tokens_in_account)} farming tokens in account')
    for token in tokens_in_account:
        if int(token['balance']) > farming_tk_balance:
            farming_tk_balance = int(token['balance'])
            break
    if not farming_tk_balance:
        raise Exception("Not enough farming token balance")
    
    event = EnterFarmEvent(farm_contract.farmingToken, 0, farming_tk_balance,
                       "", 0, 0)
    tx_hash = farm_contract.enterFarm(context.network_provider, user, event)
    advance_blocks(1)

    return tx_hash

def enter_farm_consolidated(user: Account):
    farming_tk_balance = 0
    event = EnterFarmEvent(farm_contract.farmingToken, 0, farming_tk_balance,
                       "", 0, 0)
    tx_hash = farm_contract.claim_boosted_rewards(context.network_provider, user, event)
    advance_blocks(1)

    farm_contract.get_user_farm_token_stats(user, proxy)
    return tx_hash

def exit_farm(user: Account):
    farm_contract.get_user_farm_token_stats(user, proxy)
    token_nonce, token_balance, token_attributes = get_token_in_account(proxy,user,farm_contract.farmToken)
    event = ExitFarmEvent(farm_contract.farmToken, token_balance, token_nonce, '')
    tx_hash = farm_contract.exitFarm(context.network_provider, user, event)
    advance_blocks(1)

    return tx_hash 

def user_farm_token_stats(user):
    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmingToken, user.address.bech32(), context.network_provider.proxy)
    print(f'Account: {user.address.bech32()}')
    print(f'Looking for {farm_contract.farmingToken} and {farm_contract.farmToken} tokens')
    print(f'Farming Tokens in account:')
    for token in tokens_in_account:
        print(f'\t{token}')
    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmToken, user.address.bech32(), context.network_provider.proxy)
    print(f'Farm Tokens in account:')
    all_decoded_attributes = []
    for token in tokens_in_account:
        print(f'\t{token}')
        decoded_attributes = decode_merged_attributes(base64_to_hex(token["attributes"]), FARM_TOKEN_ATTRIBUTES)
        print(f'\t\t{decoded_attributes}')
        all_decoded_attributes.append(decoded_attributes)
        
    return all_decoded_attributes

def farm_upgrade():
    deployer = context.deployer_account
    deployer.address = WrapperAddress(config.DEX_OWNER_ADDRESS)
    deployer.sync_nonce(proxy)
    tx_hash = farm_contract.contract_upgrade(deployer, context.network_provider.proxy, 
                                            wasm_path, 
                                            [], True)

    advance_blocks(1)
    tx_hash = farm_contract.resume(context.deployer_account, context.network_provider.proxy)
    advance_blocks(1)

    code_hash = context.network_provider.proxy.get_account(WrapperAddress(farm_contract.address)).code_hash
    assert base64_to_hex(code_hash) == contract_code_hash
    
    return tx_hash

@pytest.mark.regression
def test_scenario():
    chain_sim_process = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    
    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-024432.json", "r") as file:
        UTKWEGLDFL_STATE = json.load(file)

    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-02427b.json", "r") as file:
        UTKWEGLDFL_STATE2 = json.load(file)

    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE)
    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE2)

    user1 = users_init()[0]
    user2 = users_init()[1]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    user1_stats_before = farm_contract.get_all_user_boosted_stats(user1.address.to_bech32(), context.network_provider.proxy)
    user2_stats_before = farm_contract.get_all_user_boosted_stats(user2.address.to_bech32(), context.network_provider.proxy)
    farm_stats_before = farm_contract.get_all_stats(context.network_provider.proxy)

    tx_hash_1 = enter_farm_new(user1)
    advance_blocks(5)
    consumed_blocks = 5
    sleep(5)
    enter_farm_ops_1 = context.network_provider.get_tx_operations(tx_hash_1, True)

    tx_hash_2 = claim_rewards(user2)
    advance_blocks(1)
    consumed_blocks += 1
    sleep(5)
    claim_ops_1 = context.network_provider.get_tx_operations(tx_hash_2, True)
    
    user1_stats_after = farm_contract.get_all_user_boosted_stats(user1.address.to_bech32(), context.network_provider.proxy)
    user2_stats_after = farm_contract.get_all_user_boosted_stats(user2.address.to_bech32(), context.network_provider.proxy)
    farm_stats_after = farm_contract.get_all_stats(context.network_provider.proxy)
    tk_attrs_1 = user_farm_token_stats(user1)
    tk_attrs_2 = user_farm_token_stats(user2)

    #######################################################
    chain_control.stop_chain_sim_stack(chain_sim_process)
    
    chain_sim_process = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user1 = users_init()[0]
    user2 = users_init()[1]
    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-024432.json", "r") as file:
        UTKWEGLDFL_STATE = json.load(file)

    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-02427b.json", "r") as file:
        UTKWEGLDFL_STATE2 = json.load(file)

    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE)
    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE2)

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2
    sleep(10)

    user1_stats_before2 = farm_contract.get_all_user_boosted_stats(user1.address.to_bech32(), context.network_provider.proxy)
    user2_stats_before2 = farm_contract.get_all_user_boosted_stats(user2.address.to_bech32(), context.network_provider.proxy)
    farm_stats_before2 = farm_contract.get_all_stats(context.network_provider.proxy)

    assert user1_stats_before == user1_stats_before2
    assert user2_stats_before == user2_stats_before2
    assert farm_stats_before == farm_stats_before2

    tx_hash_3 = enter_farm_new(user1)
    advance_blocks(5)
    consumed_blocks = 5
    sleep(10)
    enter_farm_ops_2 = context.network_provider.get_tx_operations(tx_hash_3, True)

    tx_hash_4 = claim_rewards(user2)
    advance_blocks(1)
    consumed_blocks += 1
    sleep(10)
    claim_ops_2 = context.network_provider.get_tx_operations(tx_hash_4, True)

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    user1_stats_after2 = farm_contract.get_all_user_boosted_stats(user1.address.to_bech32(), context.network_provider.proxy)
    user2_stats_after2 = farm_contract.get_all_user_boosted_stats(user2.address.to_bech32(), context.network_provider.proxy)
    farm_stats_after2 = farm_contract.get_all_stats(context.network_provider.proxy)
    tk_attrs_3 = user_farm_token_stats(user1)
    tk_attrs_4 = user_farm_token_stats(user2)

    assert user1_stats_after == user1_stats_after2
    assert user2_stats_after == user2_stats_after2
    assert farm_stats_after == farm_stats_after2
    assert tk_attrs_1 == tk_attrs_3
    assert tk_attrs_2 == tk_attrs_4
    assert enter_farm_ops_1 == enter_farm_ops_2
    assert claim_ops_1 == claim_ops_2
    
    chain_control.stop_chain_sim_stack(chain_sim_process)

@pytest.mark.regression
def test_scenario2():
    chain_sim_process = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    initial_blocks = 10
    advance_blocks(initial_blocks)
    user = users_init()[0]

    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-024432.json", "r") as file:
        UTKWEGLDFL_STATE = json.load(file)

    with open(PROJECT_ROOT / "states" / "0_system_account_state_UTKWEGLDFL-ba26d2-02427b.json", "r") as file:
        UTKWEGLDFL_STATE2 = json.load(file)

    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE)
    proxy.do_post(f"{SIMULATOR_URL}/simulator/set-state", UTKWEGLDFL_STATE2)

    user_stats_before = farm_contract.get_all_user_boosted_stats(user.address.to_bech32(), context.network_provider.proxy)
    farm_stats_before = farm_contract.get_all_stats(context.network_provider.proxy)

    tx_hash_1 = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)
    enter_farm_ops_1 = context.network_provider.get_tx_operations(tx_hash_1, True)

    advance_epoch(7)
    tx_hash_2 = claim_rewards(user)
    advance_blocks(1)
    sleep(2)
    claim_ops_1 = context.network_provider.get_tx_operations(tx_hash_2, True)
    test_claim(tx_hash_2, user)

    tx_hash_3 = exit_farm(user) #1 block
    sleep(2)

    user_stats_after = farm_contract.get_all_user_boosted_stats(user.address.to_bech32(), context.network_provider.proxy)
    farm_stats_after = farm_contract.get_all_stats(context.network_provider.proxy)

    chain_control.stop_chain_sim_stack(chain_sim_process)

    ###################################################
    chain_sim_process = chain_control.start_chain_sim_stack()
    setup_chain_sim()

    farm_upgrade() # eats 2 blocks
    consumed_blocks += 2
    user_stats_before2 = farm_contract.get_all_user_boosted_stats(user.address.to_bech32(), context.network_provider.proxy)
    farm_stats_before2 = farm_contract.get_all_stats(context.network_provider.proxy)

    assert user_stats_before == user_stats_before2
    assert farm_stats_before == farm_stats_before2

    tx_hash_1 = enter_farm_new(user)
    advance_blocks(5)
    consumed_blocks = 5
    sleep(2)
    enter_farm_ops_2 = context.network_provider.get_tx_operations(tx_hash_1, True)

    advance_epoch(7)
    tx_hash_2 = claim_rewards(user)
    advance_blocks(1)
    consumed_blocks += 1
    sleep(2)
    claim_ops_2 = context.network_provider.get_tx_operations(tx_hash_3, True)
    test_claim(tx_hash_2, user)

    tx_hash_3 = exit_farm(user) #1 block
    consumed_blocks += 1
    sleep(2)

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    user_stats_after2 = farm_contract.get_all_user_boosted_stats(user.address.to_bech32(), context.network_provider.proxy)
    farm_stats_after2 = farm_contract.get_all_stats(context.network_provider.proxy)

    assert enter_farm_ops_1 == enter_farm_ops_2 
    assert claim_ops_1 == claim_ops_2
    assert user_stats_after == user_stats_after2
    assert farm_stats_after == farm_stats_after2

@pytest.mark.parametrize("tx_hash", [tx_hash])
def test_claim(tx_hash: str, user: Account):
    op_to_look_for = { # the Staked token transfered from staking contract to metastake contract
            "action": "transfer",
            "sender": farm_contract.address,
            "receiver": user.address,
            "collection": farm_contract.farmToken
        }
    op = context.network_provider.get_tx_operations(tx_hash, op_to_look_for)
    new_fl_token = op.get('identifier')
    new_fl_token_value = int(op.get('value'))

    return new_fl_token, new_fl_token_value