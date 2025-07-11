import pytest
from argparse import Namespace
from time import sleep
from multiversx_sdk import Address
from context import Context
from tools.chain_simulator_connector import start_handler, ChainSimulator
from contracts.router_contract import RouterContract
from utils.contract_data_fetchers import RouterContractDataFetcher
from utils.utils_chain import WrapperAddress
from utils.logger import get_logger

logger = get_logger(__name__)

@pytest.mark.parametrize("env", ["chainsim"])
def test_claim_developer_rewards(env):
    import config

    if env == "chainsim":
        # Start chain simulator
        docker_path = config.HOME / "Projects/testing/full-stack-docker-compose/chain-simulator"
        state_path = config.DEFAULT_WORKSPACE / "states"
        args = Namespace(docker_path=str(docker_path), state_path=str(state_path))

        chain_sim, found_accounts = start_handler(args)
        chain_sim = ChainSimulator()
        logger.info(f'Chain sim started. Loaded {len(found_accounts)} accounts')
        sleep(10)

    # Load context
    import importlib
    import os
    os.environ["MX_DEX_ENV"] = env
    importlib.reload(config)
    import config

    context = Context()

    router_contract: RouterContract = context.get_contracts(config.ROUTER_V2)[0]
    context.deployer_account.sync_nonce(context.network_provider.proxy)

    # Upgrade router
    bytecode = config.HOME / "Projects/dex/mx-exchange-sc/output-docker/router/router.wasm"
    router_contract.contract_upgrade(context.deployer_account, context.network_provider.proxy, bytecode)
    if env == "chainsim":
        chain_sim.advance_blocks(1)

    # Find pairs with developer rewards
    router_data_fetcher = RouterContractDataFetcher(Address.new_from_bech32(router_contract.address), context.network_provider.proxy.url)
    registered_pairs = router_data_fetcher.get_data("getAllPairsManagedAddresses")
    logger.info(f'Found {len(registered_pairs)} pairs')

    count = 0
    sum = 0
    selected_pairs = []
    for pair_address in registered_pairs:
        address = WrapperAddress.from_hex(pair_address)
        min_threshold = 0.1 * 10**18
        account_on_chain = context.network_provider.proxy.get_account(address)
        if account_on_chain.contract_developer_reward > min_threshold:
            count += 1
            sum += account_on_chain.contract_developer_reward
            selected_pairs.append(pair_address)
    logger.info(f"Found {count} pairs with developer rewards summing: {sum} (min threshold: {min_threshold})")
    assert count > 0, "Didn't find any pairs with developer rewards above the threshold."

    # Claim developer rewards
    owner_balance_before = context.network_provider.proxy.get_account(context.deployer_account.address).balance
    router_balance_before = context.network_provider.proxy.get_account(WrapperAddress(router_contract.address)).balance

    hashes = []
    chunk_size = 20
    b32_pairs = [WrapperAddress.from_hex(pair_address).bech32() for pair_address in selected_pairs]
    chunks = [b32_pairs[i:i + chunk_size] for i in range(0, len(b32_pairs), chunk_size)]
    for chunk in chunks:
        hash = router_contract.claim_developer_rewards_pairs(context.deployer_account, context.network_provider.proxy, chunk)
        hashes.append(hash)
        if env == "chainsim":
            chain_sim.advance_blocks(1)
        sleep(1)

    # hash = router_contract.withdraw_egld(context.deployer_account, context.network_provider.proxy)
    # hashes.append(hash)
    # if env == "chainsim":
    #     chain_sim.advance_blocks(1)
    
    # calculate total paid fee
    total_paid_fee = 0
    for hash in hashes:
        total_paid_fee += int(context.network_provider.proxy.get_transaction(hash).raw["fee"])
    logger.info(f"Total paid fee: {total_paid_fee}")
    
    sleep(2)

    owner_balance_after = context.network_provider.proxy.get_account(context.deployer_account.address).balance
    router_balance_after = context.network_provider.proxy.get_account(WrapperAddress(router_contract.address)).balance
    
    logger.info(f"Owner balance difference: {owner_balance_after - owner_balance_before}")
    logger.info(f"Router balance difference: {router_balance_after - router_balance_before}")

    assert router_balance_after == router_balance_before, "Router balance should be the same"
    expected_owner_balance = owner_balance_before + (sum - total_paid_fee)
    assert owner_balance_after == expected_owner_balance, f"Owner balance should be greater. Expected: {expected_owner_balance}, Actual: {owner_balance_after}"