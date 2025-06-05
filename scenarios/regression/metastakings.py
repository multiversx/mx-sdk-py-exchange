import json
from multiprocessing import get_logger
import pprint
from time import sleep
import pytest
import config
from context import Context

from contracts.permissions_hub_contract import PermissionsHubContract
from contracts.metastaking_contract import MetaStakingContract, EnterMetaStakingEvent
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from contracts.farm_contract import FarmContract
from contracts.staking_contract import StakingContract
from events.farm_events import ClaimRewardsFarmEvent, ExitFarmEvent
from events.farm_events import MergePositionFarmEvent,ClaimRewardsFarmEvent

from tools.automated_scenarios.config_data import USERS, PROJECT_ROOT, proxy, api, tx_hash
from tools.chain_simulator_utils import SIMULATOR_URL, advance_blocks, advance_epoch, ChainSimulatorControl
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES
from utils.utils_chain import Account, WrapperAddress, base64_to_hex, decode_merged_attributes, get_all_token_nonces_details_for_account
from utils.utils_scenarios import get_token_in_account
from utils.utils_tx import ESDTToken, multi_esdt_transfer
from conftest import DictCollector, DictType, users_init, setup_chain_sim

logger = get_logger("manual_interactor")

metastaking_contract: MetaStakingContract = context.deploy_structure.get_deployed_contract_by_index(config.METASTAKINGS_V2, 0)
farm_contract: FarmContract = context.deploy_structure.get_deployed_contract_by_index(config.FARMS_V2, 0)
staking_contract: StakingContract = context.deploy_structure.get_deployed_contract_by_index(config.STAKINGS_V2, 0)
chain_control = ChainSimulatorControl()

def enter_farm_new_test():
    user_index = 0
    chain_sim = chain_control.start_chain_sim_stack()
    chain_control.setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_no_consolidation_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_no_consolidation_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def enter_farm_consolidate_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def unstake_test():
    user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = unstake_farm(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial unstake farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = unstake_farm(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial unstake farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)


def claim_dual_yield_test():
    user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_dual_yield(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim dual yield operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_dual_yield(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim dual yield operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def enter_farm_on_behalf_test():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)


    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(whitelisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(whitelisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def enter_farm_on_behalf_consolidate_test():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    farm_token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)


    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, farm_token.token_amount, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    farm_token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, farm_token.token_amount, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def enter_farm_on_behalf_blacklisted_test():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    farm_token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)


    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, farm_token.token_amount, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    farm_token = transfer_tokens(user, whitelisted_user)
    advance_blocks(5)

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, farm_token.token_amount, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def claim_dual_yield_on_behalf_test():
    user_index = 1
    whitelisted_user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)


    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_on_behalf_from_user(whitelisted_user, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    permission_hub_contract.add_to_whitelist(user, context.network_provider.proxy, [whitelisted_user.address.bech32()])
    advance_blocks(1)

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_on_behalf_from_user(whitelisted_user, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def claim_dual_yield_on_behalf_blacklisted_test():
    user_index = 1
    whitelisted_user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    collector = DictCollector()
    collector.set_phase("before")

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_on_behalf_from_user(whitelisted_user, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    staking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    metastaking_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    collector.set_phase("after")

    position_token = transfer_position(user, whitelisted_user)
    advance_blocks(5)

    permission_hub_contract = deploy_permissions_hub()
    advance_blocks(1)

    farm_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    staking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    metastaking_contract.set_permissions_hub_address(context.deployer_account, context.network_provider.proxy, permission_hub_contract.address)
    advance_blocks(1)

    collect_initial_test_data(collector, user, farm_contract, staking_contract)

    tx_hash = claim_on_behalf_from_user(whitelisted_user, position_token.token_amount)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")

    collect_ending_test_data(collector, user, farm_contract, staking_contract)

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)