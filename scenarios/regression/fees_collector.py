def claim_rewards_test():
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
