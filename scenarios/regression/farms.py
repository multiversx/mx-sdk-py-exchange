import json
import pprint
from time import sleep
import pytest
import config
from context import Context

from contracts.permissions_hub_contract import PermissionsHubContract
from contracts.farm_contract import FarmContract, EnterFarmEvent
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from events.farm_events import ClaimRewardsFarmEvent, ExitFarmEvent
from events.farm_events import MergePositionFarmEvent,ClaimRewardsFarmEvent

from tools.automated_scenarios.config_data import USERS, PROJECT_ROOT, proxy, api, tx_hash
from tools.chain_simulator_utils import SIMULATOR_URL, advance_blocks, advance_epoch, ChainSimulatorControl
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES
from utils.utils_chain import Account, WrapperAddress, base64_to_hex, decode_merged_attributes, get_all_token_nonces_details_for_account
from utils.utils_scenarios import get_token_in_account
from utils.utils_tx import ESDTToken, multi_esdt_transfer
from conftest import DictCollector, DictType, users_init, setup_chain_sim

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

def merge_positions(user):
    user.sync_nonce(context.network_provider.proxy)
    
    farm_tk_balance = 0
    tokens_in_account = get_all_token_nonces_details_for_account(
        farm_contract.farmToken, user.address.bech32(), context.network_provider.proxy
    )
    print(f'Found {len(tokens_in_account)} farm tokens in account')
    
    event_list = []
    for token in tokens_in_account:
        if int(token['balance']) > farm_tk_balance:
            event_list.append(MergePositionFarmEvent(int(token['balance']), token['nonce'], None))
    
    tx_hash = farm_contract.mergePositions(context.network_provider, user, event_list)
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

def enter_farm_on_behalf(claim_account, user_address):
    claim_account.sync_nonce(context.network_provider.proxy)
    
    farming_tk_balance = 0
    tokens_in_account = get_all_token_nonces_details_for_account(
        farm_contract.farmingToken, claim_account.address.bech32(), context.network_provider.proxy
    )
    print(f'Found {len(tokens_in_account)} farming tokens in account')
    
    for token in tokens_in_account:
        if int(token['balance']) > 0:
            farming_tk_balance = int(token['balance'])
            break
    
    if not farming_tk_balance:
        raise Exception("Not enough farming token balance")
    
    farm_tk_balance, farm_tk_nonce = 0, 0
    tokens_in_account = get_all_token_nonces_details_for_account(
        farm_contract.farmToken, claim_account.address.bech32(), context.network_provider.proxy
    )
    print(f'Found {len(tokens_in_account)} farm tokens in account')
    
    for token in tokens_in_account:
        if int(token['balance']) > farm_tk_balance:
            farm_tk_balance = int(token['balance'])
            farm_tk_nonce = token['nonce']
            break
    
    if farm_tk_balance > 0:
        event = EnterFarmEvent(
            farm_contract.farmingToken, 0, farming_tk_balance,
            farm_contract.farmToken, farm_tk_nonce, farm_tk_balance, user_address.address.bech32()
        )
    else:
        event = EnterFarmEvent(
            farm_contract.farmingToken, 0, farming_tk_balance,
            None, 0, 0, user_address.address.bech32()
        )
    
    tx_hash = farm_contract.enter_farm_on_behalf(context.network_provider, claim_account, event)
    return tx_hash

def claim_rewards_on_behalf(whitelisted_account, user_account):
    whitelisted_account.sync_nonce(context.network_provider.proxy)

    farm_tk_balance, farm_tk_nonce = 0, 0
    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmToken, whitelisted_account.address.bech32(), context.network_provider.proxy)
    print(f'Found {len(tokens_in_account)} positions of {farm_contract.farmToken} in account')
    for token in tokens_in_account:
        if int(token['balance']) > farm_tk_balance:
            farm_tk_balance = int(token['balance'])
            farm_tk_nonce = token['nonce']
            break

    if not farm_tk_nonce:
        raise Exception("Not enough farm token balance")

    event = ClaimRewardsFarmEvent(farm_tk_balance, farm_tk_nonce, '', user_account.address.bech32())

    tx_hash = farm_contract.claim_rewards_on_behalf(context.network_provider, whitelisted_account, event)
    return tx_hash

def transfer_position(user_account, destination):
    user_account.sync_nonce(context.network_provider.proxy)

    tokens_in_account = get_all_token_nonces_details_for_account(farm_contract.farmToken, user_account.address.bech32(), context.network_provider.proxy)
    print(f'Found {len(tokens_in_account)} farm tokens in account')
    for token in tokens_in_account:
        if int(token['balance']) > 0:
            farm_tk = token
            break
    token = ESDTToken(farm_tk['tokenIdentifier'], farm_tk['nonce'], int(farm_tk['balance']))
    print(f'Sending: {token.get_token_data()} from {user_account.address.bech32()}')
    multi_esdt_transfer(context.network_provider.proxy, 1000000, user_account, destination.address, [token])

def deploy_permissions_hub():
    permissions_hub_contract = PermissionsHubContract("")
    _, address = permissions_hub_contract.contract_deploy(context.deployer_account, context.network_provider.proxy, 
                                            "https://github.com/multiversx/mx-exchange-sc/releases/download/v3.2.2-rc2/permissions-hub.wasm",
                                            [])
    permissions_hub_contract.address = address
    return permissions_hub_contract

def set_permissions_hub(permissions_hub_contract: PermissionsHubContract):
    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permissions_hub_contract.address)

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

@pytest.mark.regression
def enter_farm_test():
    user_index = 1
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    event = EnterFarmEvent(farm_contract.farmingToken, 0, 0)
    tx_hash = farm_contract.enterFarm(context.network_provider, user, event)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def enter_farm_consolidate_test():
    user_index = 2
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_consolidated(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_consolidated(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def exit_farm_test():
    user_index = 2
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = exit_farm(user)
    advance_blocks(5)
    sleep(2)
    exit_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, exit_op_1, "Initial exit farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = exit_farm(user)
    advance_blocks(5)
    sleep(2)
    exit_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, exit_op_1, "Initial exit operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def claim_rewards_test():
    user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def claim_rewards_multiple_positions_test():
    user_index = 2
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)

    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    tx_hash = claim_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, claim_op_1, "Initial claim farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)

    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    tx_hash = claim_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, claim_op_1, "Initial claim operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def claim_boosted_rewards_test():
    user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_boosted_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim boosted farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")


    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_boosted_rewards(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim boosted operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def merge_positions_test():
    user_index = 2
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    tx_hash = merge_positions(user)
    advance_blocks(5)
    sleep(2)
    merge_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, merge_op_1, "Initial merge positions operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_new(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter operation")

    tx_hash = merge_positions(user)
    advance_blocks(5)
    sleep(2)
    merge_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, merge_op_1, "Initial merge positions operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

    def enter_on_behalf_test():
        user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[1]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(5)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(whitelisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[1]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(whitelisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def enter_on_behalf_consolidate_test():
    user_index = 2
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[1]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(5)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(whitelisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[1]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(whitelisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def enter_on_behalf_blacklisted_test():
    user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[2]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_blacklist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[1]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_blacklist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def claim_rewards_on_behalf_test():
    user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[2]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm on behalf farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[1]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)

@pytest.mark.regression
def claim_on_behalf_blacklisted_test():
    user_index = user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[2]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_blacklist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm on behalf farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    chain_control.stop_chain_sim_stack(chain_sim)
    chain_sim = chain_control.start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[1]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    permissions_hub_contract.add_to_blacklist(user, context.network_provider.proxy, [blacklisted_user.address.bech32()])
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_rewards_on_behalf(blacklisted_user, user)
    advance_blocks(5)
    sleep(6)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    chain_control.stop_chain_sim_stack(chain_sim)