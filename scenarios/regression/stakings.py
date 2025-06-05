import sys
import pprint
from pathlib import Path
sys.path.append(str(Path.cwd().parent.parent.absolute()))

import config
import ipytest
ipytest.autoconfig()

from context import Context
from utils.utils_chain import WrapperAddress as Address, Account, base64_to_hex
from utils.logger import get_logger

from contracts.staking_contract import StakingContract

from multiversx_sdk import ProxyNetworkProvider, ApiNetworkProvider

logger = get_logger("manual_interactor")

SIMULATOR_URL = "http://localhost:8085"
SIMULATOR_API = "http://localhost:3001"
GENERATE_BLOCKS_URL = f"{SIMULATOR_URL}/simulator/generate-blocks"
PROJECT_ROOT = Path.cwd().parent.parent
proxy = ProxyNetworkProvider(SIMULATOR_URL)
api = ApiNetworkProvider(SIMULATOR_API)

context = Context()
context.network_provider.proxy = proxy
context.network_provider.api = api


farm_contract: StakingContract = context.deploy_structure.get_deployed_contract_by_index(config.STAKINGS_V2, 0)

def enter_farm_new_test():
    user_index = 1
    chain_sim = start_chain_sim_stack()
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

    tx_hash = stake_farm_no_consolidation_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial stake farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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

    tx_hash = stake_farm_no_consolidation_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial stake operation")

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

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = stake_farm_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial stake farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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

    tx_hash = stake_farm_for_user(user)
    advance_blocks(5)
    sleep(2)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial stake farm operation")

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

    stop_chain_sim_stack(chain_sim)

def unstake_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)
    up0 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up0, "Initial user positions")

    tx_hash = unstake_for_user(user)
    advance_blocks(5)
    sleep(2)
    unstake_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, unstake_op_1, "Initial unstake operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up1, "Ending user positions")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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
    up0 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up0, "Initial user positions")

    tx_hash = unstake_for_user(user)
    advance_blocks(5)
    sleep(2)
    unstake_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, unstake_op_1, "Initial unstake operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up1, "Ending user positions")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim) 

def unbond_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)
    up0 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up0, "Initial user positions")

    tx_hash = unstake_for_user(user)
    advance_blocks(5)
    sleep(2)
    unstake_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, unstake_op_1, "Initial unstake operation")

    tx_hash = unbond_for_user(user)
    advance_blocks(5)
    sleep(2)
    unbond_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, unbond_op_1, "Initial unbond operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up1, "Ending user positions")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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
    up0 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up0, "Initial user positions")

    tx_hash = unstake_for_user(user)
    advance_blocks(5)
    sleep(2)
    unstake_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, unstake_op_1, "Initial unstake operation")

    tx_hash = unbond_for_user(user)
    advance_blocks(5)
    sleep(2)
    unbond_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, unbond_op_1, "Initial unbond operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up1, "Ending user positions")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def claim_rewards_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
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

    tx_hash = claim_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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

    tx_hash = claim_rewards_user(user)
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

    stop_chain_sim_stack(chain_sim)

def claim_rewards_multiple_positions_test():
    user_index = 2
    chain_sim = start_chain_sim_stack()
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

    tx_hash = enter_farm_for_user(user)
    advance_blocks(5)
    sleep(2)

    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")
    up1 = get_user_positions(user)
    collector.add(DictType.USER_POSITION_INITIAL, up1, "Initial user positions")

    tx_hash = claim_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, claim_op_1, "Initial claim farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up2 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up2, "Ending user positions")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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

    tx_hash = enter_farm_for_user(user)
    advance_blocks(5)
    sleep(2)

    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial enter farm operation")
    up1 = get_user_positions(user)
    collector.add(DictType.USER_POSITION_INITIAL, up1, "Initial user positions")

    tx_hash = claim_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP2, claim_op_1, "Initial claim operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up2 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up2, "Ending user positions")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def claim_boosted_rewards_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
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

    tx_hash = claim_boosted_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    claim_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, claim_op_1, "Initial claim boosted farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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

    tx_hash = claim_boosted_rewards_user(user)
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

    stop_chain_sim_stack(chain_sim)

def compound_rewards_test():
    user_index = 0
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    pprint.pprint(farm_contract.get_config_dict())

    collector = DictCollector()
    collector.set_phase("before")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up1, "Initial user positions")

    tx_hash = compound_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    compound_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, compound_op_1, "Initial compound farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up2 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up2, "Ending user positions")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
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
    up1 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")
    collector.add(DictType.USER_POSITION_INITIAL, up1, "Initial user positions")

    tx_hash = compound_rewards_user(user)
    advance_blocks(5)
    sleep(2)
    compound_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, compound_op_1, "Initial compound farm operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)
    up2 = get_user_positions(user)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")
    collector.add(DictType.USER_POSITION_FINAL, up2, "Ending user positions")

    differences = collector.compare_all()
    if differences:
        print("Found differences:")
        for diff in differences:
            print(f"- {diff}")
    else:
        print("All comparisons passed!")
    collector.print_collections()

    stop_chain_sim_stack(chain_sim)

def stake_farm_on_behalf_new():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    whitelisted_user = users_init()[whitelisted_user_index]

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

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(whitelisted_user, user)
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
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

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

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(whitelisted_user, user)
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

    stop_chain_sim_stack(chain_sim)

def stake_farm_on_behalf_consolidated_test():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    token = get_single_user_position(user)
    advance_blocks(5)

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

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, token.token_amount)
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
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    token = get_single_user_position(user)
    advance_blocks(5)

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

    tx_hash = enter_farm_on_behalf_for_user(whitelisted_user, user, token.token_amount)
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

    stop_chain_sim_stack(chain_sim)

def stake_farm_on_behalf_blacklisted_test():
    user_index = 0
    blacklisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    blacklisted_user = users_init()[blacklisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    token = get_single_user_position(user)
    advance_blocks(5)

    transfer_position(user, blacklisted_user, token.token_amount)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
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

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(blacklisted_user, user)
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
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[blacklisted_user_index]

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

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = enter_farm_on_behalf_no_consolidation_for_user(blacklisted_user, user)
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

    stop_chain_sim_stack(chain_sim)

def claim_rewards_on_behalf_test():
    user_index = 0
    whitelisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    whitelisted_user = users_init()[whitelisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    token = get_single_user_position(user)
    advance_blocks(5)

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

    tx_hash = claim_on_behalf_from_user(whitelisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    whitelisted_user = users_init()[whitelisted_user_index]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    token = get_single_user_position(user)
    advance_blocks(5)

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

    tx_hash = claim_on_behalf_from_user(whitelisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim on behalf operation")

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

    stop_chain_sim_stack(chain_sim)

def claim_rewards_on_behalf_blacklisted_test():
    user_index = 0
    blacklisted_user_index = 1
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]

    blacklisted_user = users_init()[blacklisted_user_index]

    initial_blocks = 10
    advance_blocks(initial_blocks)

    token = get_single_user_position(user)
    advance_blocks(5)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
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

    tx_hash = claim_on_behalf_from_user(blacklisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim on behalf operation")

    u21 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u22 = farm_contract.get_all_user_boosted_stats(whitelisted_user.address.bech32(), context.network_provider.proxy)
    c21 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_2, u21, "Ending farm user stats")
    collector.add(DictType.USER_FARM_STATS_2_BEHALF, u22, "Ending farm user on behalf stats")
    collector.add(DictType.FARM_CONTRACT_STATS_2, c21, "Ending farm contract stats")

    # ------------------------------------------------------------------------------------------------
    stop_chain_sim_stack(chain_sim)
    chain_sim = start_chain_sim_stack()
    setup_chain_sim()
    user = users_init()[user_index]
    blacklisted_user = users_init()[blacklisted_user_index]

    advance_blocks(1)
    consumed_blocks = 1

    farm_upgrade()  # eats 2 blocks
    consumed_blocks += 2

    block_diff = initial_blocks - consumed_blocks
    advance_blocks(block_diff)

    token = get_single_user_position(user)
    advance_blocks(5)

    transfer_position(user, blacklisted_user)
    advance_blocks(5)

    permissions_hub_contract = deploy_permissions_hub()
    advance_blocks(5)

    set_permissions_hub(permissions_hub_contract)
    advance_blocks(5)

    collector.set_phase("after")

    u11 = farm_contract.get_all_user_boosted_stats(user.address.bech32(), context.network_provider.proxy)
    u12 = farm_contract.get_all_user_boosted_stats(blacklisted_user.address.bech32(), context.network_provider.proxy)
    c11 = farm_contract.get_all_stats(context.network_provider.proxy)

    collector.add(DictType.USER_FARM_STATS_1, u11, "Initial farm user stats")
    collector.add(DictType.USER_FARM_STATS_1_BEHALF, u12, "Initial farm user stats on behalf")
    collector.add(DictType.FARM_CONTRACT_STATS_1, c11, "Initial farm contract stats")

    tx_hash = claim_on_behalf_from_user(blacklisted_user, user, token.token_amount)
    advance_blocks(5)
    sleep(6)
    enter_op_1 = context.network_provider.get_tx_operations(tx_hash, True)
    collector.add(DictType.OP1, enter_op_1, "Initial claim on behalf operation")

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

    stop_chain_sim_stack(chain_sim)