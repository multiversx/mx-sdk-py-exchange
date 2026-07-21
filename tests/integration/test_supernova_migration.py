"""
Supernova Migration Integration Tests

Three independent test classes — one per contract type:
  1. TestPairMigration: upgrade all pairs via router, then swap + add liquidity
  2. TestFarmMigration: upgrade all farms (no_init), then enter + claim + exit
  3. TestStakingMigration: upgrade all staking contracts (no_init), then stake + claim + unstake

Ownership:
  - Pairs are owned by the Router SC → must upgrade via router.upgradePair()
  - Farms are owned by the deployer → direct upgradeContract
  - Staking contracts are owned by the deployer → direct upgradeContract

Run:
    PYTHONPATH=. python -m pytest tests/integration/test_supernova_migration.py -v
    PYTHONPATH=. python -m pytest tests/integration/test_supernova_migration.py::TestPairMigration -v
    PYTHONPATH=. python -m pytest tests/integration/test_supernova_migration.py::TestFarmMigration -v
    PYTHONPATH=. python -m pytest tests/integration/test_supernova_migration.py::TestStakingMigration -v

Prerequisites:
    - Chain simulator running (supernova image)
    - Mainnet state loaded (automatic via conftest)
    - wasm-supernova/ directory with: pair-full.wasm, farm-with-locked-rewards.wasm, farm-staking.wasm
"""

import requests as http_requests
from pathlib import Path

import pytest
from multiversx_sdk import Address
from multiversx_sdk.abi import TokenIdentifierValue, BigUIntValue

import config
from contracts.pair_contract import PairContract, PairContractVersion, SwapFixedInputEvent, AddLiquidityEvent
from utils.contract_data_fetchers import PairContractDataFetcher, FarmContractDataFetcher
from utils.utils_chain import Account
from utils.logger import get_logger
from tests.helpers import PairAssertions, TransactionAssertions


logger = get_logger(__name__)

WASM_DIR = Path(config.DEFAULT_WORKSPACE) / "wasm-supernova"
PAIR_WASM = WASM_DIR / "pair-full.wasm"
FARM_WASM = WASM_DIR / "farm-with-locked-rewards.wasm"
STAKING_WASM = WASM_DIR / "farm-staking.wasm"
ENERGY_FACTORY_WASM = WASM_DIR / "energy-factory.wasm"


def _ensure_contract_owner(contract_address: str, deployer_account: Account, proxy_url: str):
    """Ensure the contract's ownerAddress on chain sim matches the deployer.

    Farm contracts loaded via ensure_contract_state_from_mainnet may not have
    ownerAddress set properly. This patches it via set-state if needed.
    """
    http_requests.post(f"{proxy_url}/simulator/set-state", json=[{
        "address": contract_address,
        "ownerAddress": deployer_account.address.to_bech32(),
    }])
    http_requests.post(f"{proxy_url}/simulator/generate-blocks/1")


# ============================================================================
# PAIR MIGRATION
# ============================================================================

@pytest.mark.integration
class TestPairMigration:

    def test_upgrade_and_operate(
        self,
        all_pair_contracts,
        pair_contract,
        router_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        Upgrade all pairs to supernova via router, then verify swap + add liquidity.

        Pairs are owned by the Router SC, so we use contract_upgrade_via_router()
        which calls router.upgradePair(). The deployer must be the router's owner.

        Steps:
            1. For each pair: capture reserves -> upgrade via router -> assert reserves unchanged
            2. Swap on primary pair -> assert output == getAmountOut
            3. Add liquidity on primary pair -> assert reserves increased, k holds
        """
        assert PAIR_WASM.exists(), f"Pair WASM not found at {PAIR_WASM}"

        from tests.integration.farm_staking import _ensure_deployer_has_egld
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # Step 1: Upgrade the router's pair TEMPLATE with supernova bytecode.
        # The router uses deployFromSourceContract to clone the template for upgradePair.
        # The template must be upgraded first so subsequent upgradePair calls use new code.
        from utils.contract_data_fetchers import RouterContractDataFetcher
        router_fetcher = RouterContractDataFetcher(
            Address.new_from_bech32(router_contract.address), network_providers.proxy.url
        )
        template_hex = router_fetcher.get_data("getPairTemplateAddress")
        template_address = Address(bytes.fromhex(template_hex), "erd").to_bech32()
        logger.info(f"Upgrading pair template at {template_address}")

        # Template is owned by the router — set our deployer as owner for the upgrade
        _ensure_contract_owner(template_address, deployer_account, network_providers.proxy.url)

        template_pair = PairContract("", "", PairContractVersion.V2, address=template_address)
        deployer_account.sync_nonce(network_providers.proxy)
        tx_hash = template_pair.contract_upgrade(
            deployer_account, network_providers.proxy, str(PAIR_WASM), [], no_init=True
        )
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
        logger.info("Pair template upgraded to supernova")

        # Step 2: Upgrade each pair via router.upgradePair([firstToken, secondToken])
        logger.info(f"Upgrading {len(all_pair_contracts)} pair contracts via router")

        for i, pair in enumerate(all_pair_contracts):
            reserves_before = PairAssertions.get_reserves(pair.address, network_providers.proxy)

            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = router_contract.pair_contract_upgrade(
                deployer_account, network_providers.proxy,
                [pair.firstToken, pair.secondToken]
            )
            blockchain_controller.wait_for_tx(tx_hash)
            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            reserves_after = PairAssertions.get_reserves(pair.address, network_providers.proxy)
            assert reserves_after == reserves_before, (
                f"Pair {pair.firstToken}/{pair.secondToken} state changed after upgrade:\n"
                f"  Before: {reserves_before}\n  After: {reserves_after}"
            )
            logger.info(f"  [{i+1}/{len(all_pair_contracts)}] {pair.firstToken}/{pair.secondToken} — OK")

        # --- SWAP POST-UPGRADE ---
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        swap_amount = reserves[0] // 1000
        k_before = reserves[0] * reserves[1]

        fetcher = PairContractDataFetcher(
            Address.new_from_bech32(pair_contract.address), network_providers.proxy.url
        )
        expected_output = fetcher.get_data(
            "getAmountOut",
            [TokenIdentifierValue(pair_contract.firstToken), BigUIntValue(swap_amount)]
        )
        assert expected_output > 0, "getAmountOut should return positive value post-upgrade"

        all_fungible_before = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        second_before = sum(t.balance for t in all_fungible_before if t.identifier == pair_contract.secondToken)

        ensure_esdt_amounts(alice, {pair_contract.firstToken: swap_amount})
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.swap_fixed_input(network_providers, alice, SwapFixedInputEvent(
            tokenA=pair_contract.firstToken, amountA=swap_amount,
            tokenB=pair_contract.secondToken, amountBmin=int(expected_output * 0.95)
        ))
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        all_fungible_after = network_providers.proxy.get_fungible_tokens_of_account(alice.address)
        second_after = sum(t.balance for t in all_fungible_after if t.identifier == pair_contract.secondToken)
        assert second_after - second_before == expected_output, (
            f"Swap output mismatch: expected {expected_output}, got {second_after - second_before}"
        )
        logger.info(f"Swap post-upgrade: OK (output={expected_output})")

        # --- ADD LIQUIDITY POST-UPGRADE ---
        reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
        add_first = reserves[0] // 1000
        add_second = reserves[1] // 1000

        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: add_first,
            pair_contract.secondToken: add_second,
        })
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.add_liquidity(network_providers, alice, AddLiquidityEvent(
            tokenA=pair_contract.firstToken, amountA=add_first, amountAmin=1,
            tokenB=pair_contract.secondToken, amountB=add_second, amountBmin=1,
        ))
        blockchain_controller.wait_for_tx(tx_hash)
        TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

        PairAssertions.assert_constant_product_holds(
            pair_contract.address, k_before, network_providers.proxy
        )
        logger.info("Add liquidity post-upgrade: OK")


# ============================================================================
# FARM MIGRATION
# ============================================================================

@pytest.mark.integration
class TestFarmMigration:

    def test_upgrade_and_operate(
        self,
        dex_context,
        farm_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        Upgrade all farm contracts to supernova, then verify enter + claim + exit.

        Farms are owned by the deployer. Upgrade uses no_init=True to preserve state.
        Farm contracts loaded from mainnet may not have ownerAddress set on chain sim,
        so we patch it before upgrading.

        Steps:
            1. For each farm: set owner -> capture RPS/supply -> upgrade (no_init) -> verify
            2. On primary farm: enterFarm -> claimRewards -> exitFarm
        """
        assert FARM_WASM.exists(), f"Farm WASM not found at {FARM_WASM}"

        from tests.integration.farm import (
            _check_farm_has_code, _get_stake_amount,
            _enter_farm, _claim_rewards, _exit_farm, _get_farm_tokens_for_user,
        )
        from tests.integration.farm_staking import _ensure_deployer_has_egld
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # --- UPGRADE ALL FARMS ---
        farms = dex_context.get_contracts(config.FARMS_V2)
        assert farms, "No boosted farm contracts deployed"

        logger.info(f"Upgrading {len(farms)} farm contracts")
        failed_upgrades = []
        for i, farm in enumerate(farms):
            # Ensure farm has bytecode + state on chain sim (only first farm is
            # loaded by conftest; the rest may not have code yet)
            if test_environment.supports_time_control():
                from tests.environments import ChainsimEnvironment
                if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
                    test_environment.chain_sim.ensure_contract_state_from_mainnet(
                        farm.address,
                        filter_first_week_epoch=True,
                        filter_boosted_yields_weeks=True,
                        reset_last_reward_timestamps=True,
                    )
            # Ensure deployer is set as owner
            _ensure_contract_owner(farm.address, deployer_account, network_providers.proxy.url)

            fetcher = FarmContractDataFetcher(
                Address.new_from_bech32(farm.address), network_providers.proxy.url
            )
            rps_before = fetcher.get_data("getRewardPerShare")
            supply_before = fetcher.get_data("getFarmTokenSupply")

            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = farm.contract_upgrade(
                deployer_account, network_providers.proxy, str(FARM_WASM), [], no_init=True
            )
            blockchain_controller.wait_for_tx(tx_hash)

            tx_data = network_providers.proxy.get_transaction(tx_hash)
            if not tx_data.status.is_successful:
                error_msg = TransactionAssertions._extract_error_from_tx(tx_data)
                failed_upgrades.append((farm.farmingToken, farm.address, error_msg))
                logger.warning(
                    f"  [{i+1}/{len(farms)}] {farm.farmingToken} — UPGRADE FAILED: {error_msg}"
                )
                continue

            rps_after = fetcher.get_data("getRewardPerShare")
            supply_after = fetcher.get_data("getFarmTokenSupply")
            assert rps_after >= rps_before, f"Farm RPS decreased: {rps_before} -> {rps_after}"
            assert supply_after == supply_before, f"Farm supply changed: {supply_before} -> {supply_after}"
            logger.info(f"  [{i+1}/{len(farms)}] {farm.farmingToken} — OK")

        if failed_upgrades:
            details = "\n".join(
                f"  - {token} ({addr}): {err}" for token, addr, err in failed_upgrades
            )
            assert False, (
                f"{len(failed_upgrades)}/{len(farms)} farm upgrades failed:\n{details}"
            )

        # --- OPERATIONS POST-UPGRADE ---
        if not _check_farm_has_code(farm_contract, network_providers.proxy):
            pytest.skip("Farm contract bytecode not loaded")

        # Upgrade the energy factory (simple_lock_energy) to supernova.
        # The farm's enterFarm calls lock_virtual on this SC, so it must
        # be on the supernova version for post-upgrade farm operations to work.
        assert ENERGY_FACTORY_WASM.exists(), f"Energy factory WASM not found at {ENERGY_FACTORY_WASM}"
        locking_scs = dex_context.get_contracts(config.SIMPLE_LOCKS_ENERGY)
        if locking_scs:
            locking_sc = locking_scs[0]

            # Ensure energy factory has full state loaded (350k keys — apply_states
            # auto-chunks large states now, so this will work reliably).
            if test_environment.supports_time_control():
                from tests.environments import ChainsimEnvironment
                if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
                    import json
                    state_file = Path(config.DEFAULT_WORKSPACE) / "states" / "0_simple_locks_energy_0_chain_config_state.json"
                    if state_file.exists():
                        with open(state_file) as f:
                            full_state = json.load(f)
                        # apply_states handles chunking automatically
                        test_environment.chain_sim.apply_states([full_state if isinstance(full_state, list) else [full_state]])
                        test_environment.chain_sim.advance_blocks(1)

            # Replace bytecode with supernova version via set-state
            _ensure_contract_owner(locking_sc.address, deployer_account, network_providers.proxy.url)
            code_hex = ENERGY_FACTORY_WASM.read_bytes().hex()
            http_requests.post(f"{network_providers.proxy.url}/simulator/set-state", json=[{
                "address": locking_sc.address,
                "code": code_hex,
            }])
            http_requests.post(f"{network_providers.proxy.url}/simulator/generate-blocks/1")
            logger.info("Energy factory upgraded to supernova")

        farming_token = farm_contract.farmingToken
        stake_amount = _get_stake_amount(farm_contract, network_providers.proxy)

        # Enter
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx = _enter_farm(farm_contract, alice, farming_token, stake_amount,
                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Enter farm post-upgrade: OK")

        # Claim
        blockchain_controller.wait_blocks(5)
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens"
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        tx = _claim_rewards(farm_contract, alice, ft.token.nonce, ft.amount,
                            network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Claim rewards post-upgrade: OK")

        # Exit
        farm_tokens = _get_farm_tokens_for_user(farm_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        tx = _exit_farm(farm_contract, alice, ft.token.nonce, ft.amount,
                        network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Exit farm post-upgrade: OK")


# ============================================================================
# FARM STAKING MIGRATION
# ============================================================================

@pytest.mark.integration
class TestStakingMigration:

    def test_upgrade_and_operate(
        self,
        dex_context,
        staking_contract,
        alice,
        deployer_account,
        test_environment,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """
        Upgrade all staking contracts to supernova, then verify stake + claim + unstake.

        Staking contracts are owned by the deployer. Upgrade uses no_init=True to
        preserve state (avoids re-initialization which can trigger arithmetic errors
        from mainnet-era timestamps).

        Steps:
            1. For each staking: capture RPS/capacity/supply -> upgrade (no_init) -> verify
            2. On primary staking: stakeFarm -> claimRewards -> unstakeFarm
        """
        assert STAKING_WASM.exists(), f"Staking WASM not found at {STAKING_WASM}"

        from tests.integration.farm_staking import (
            _check_staking_has_code, _get_stake_amount,
            _stake_farm, _claim_rewards, _unstake_farm, _get_farm_tokens_for_user,
            _ensure_deployer_has_egld,
        )
        _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)

        # --- UPGRADE ALL STAKING CONTRACTS ---
        stakings_v2 = dex_context.get_contracts(config.STAKINGS_V2) or []
        stakings_boosted = dex_context.get_contracts(config.STAKINGS_BOOSTED) or []
        all_stakings = stakings_v2 + stakings_boosted
        assert all_stakings, "No staking contracts deployed"

        logger.info(f"Upgrading {len(all_stakings)} staking contracts")
        failed_upgrades = []
        for i, staking in enumerate(all_stakings):
            # Ensure staking has bytecode + state on chain sim
            if test_environment.supports_time_control():
                from tests.environments import ChainsimEnvironment
                if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
                    test_environment.chain_sim.ensure_contract_state_from_mainnet(
                        staking.address,
                        filter_first_week_epoch=True,
                        filter_boosted_yields_weeks=True,
                        reset_last_reward_timestamps=True,
                    )
            # Ensure deployer is set as owner
            _ensure_contract_owner(staking.address, deployer_account, network_providers.proxy.url)

            rps_before = staking.get_reward_per_share(network_providers.proxy)
            capacity_before = staking.get_reward_capacity(network_providers.proxy)
            supply_before = staking.get_farm_token_supply(network_providers.proxy)

            deployer_account.sync_nonce(network_providers.proxy)
            tx_hash = staking.contract_upgrade(
                deployer_account, network_providers.proxy, str(STAKING_WASM), [], no_init=True
            )
            blockchain_controller.wait_for_tx(tx_hash)

            tx_data = network_providers.proxy.get_transaction(tx_hash)
            if not tx_data.status.is_successful:
                error_msg = TransactionAssertions._extract_error_from_tx(tx_data)
                failed_upgrades.append((staking.farming_token, staking.address, error_msg))
                logger.warning(
                    f"  [{i+1}/{len(all_stakings)}] {staking.farming_token} — UPGRADE FAILED: {error_msg}"
                )
                continue

            TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)

            rps_after = staking.get_reward_per_share(network_providers.proxy)
            capacity_after = staking.get_reward_capacity(network_providers.proxy)
            supply_after = staking.get_farm_token_supply(network_providers.proxy)

            assert rps_after >= rps_before, f"RPS decreased: {rps_before} -> {rps_after}"
            assert capacity_after == capacity_before, f"Capacity changed: {capacity_before} -> {capacity_after}"
            assert supply_after == supply_before, f"Supply changed: {supply_before} -> {supply_after}"
            logger.info(f"  [{i+1}/{len(all_stakings)}] {staking.farming_token} — OK")

        if failed_upgrades:
            details = "\n".join(
                f"  - {token} ({addr}): {err}" for token, addr, err in failed_upgrades
            )
            assert False, (
                f"{len(failed_upgrades)}/{len(all_stakings)} staking upgrades failed:\n{details}"
            )

        # --- OPERATIONS POST-UPGRADE ---
        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Stake
        ensure_esdt_amounts(alice, {farming_token: stake_amount})
        tx = _stake_farm(staking_contract, alice, farming_token, stake_amount,
                         network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Stake post-upgrade: OK")

        # Claim
        blockchain_controller.wait_blocks(5)
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        assert len(farm_tokens) > 0, "Alice should have farm tokens"
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        tx = _claim_rewards(staking_contract, alice, ft.token.nonce, ft.amount,
                            network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Claim rewards post-upgrade: OK")

        # Unstake
        farm_tokens = _get_farm_tokens_for_user(staking_contract, alice, network_providers.proxy)
        ft = max(farm_tokens, key=lambda t: t.token.nonce)
        tx = _unstake_farm(staking_contract, alice, ft.token.nonce, ft.balance,
                           network_providers, blockchain_controller)
        TransactionAssertions.assert_transaction_success(tx, network_providers.proxy)
        logger.info("Unstake post-upgrade: OK")
