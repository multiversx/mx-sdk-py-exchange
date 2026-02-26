# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python operational toolkit for the xExchange DEX on MultiversX. Used to deploy, configure, upgrade, and stress-test DEX smart contracts. This is **not a distributable package** — it's an internal operations tool.

## Setup & Common Commands

```bash
# Setup
python3 -m venv ./.venv
source ./.venv/bin/activate
pip install -r ./requirements.txt --upgrade

# REQUIRED before running any script
export PYTHONPATH=.

# Select environment (default: devnet)
export MX_DEX_ENV=devnet  # mainnet | devnet | testnet | chainsim | shadowfork4 | custom

# Deploy a full DEX setup
python3 deploy/dex_deploy.py --deploy-contracts=clean --deploy-tokens=clean

# Run scenarios/tests
python3 scenarios/stress_create_positions.py
python3 scenarios/scenario_dex_v2_all_in.py

# Run unit tests
python3 -m unittest tests/test_environment_config.py -v

# Upgrade contracts
python3 tools/contracts_upgrader.py --fetch-pairs
python3 tools/contracts_upgrader.py --upgrade-pairs --compare-state

# Lint
flake8  # only E501 (line length) is ignored
```

## Architecture

### Entry Point: `context.py`
The `Context` class is the central orchestrator. It initializes the network provider, loads accounts, triggers deployment via `DeployStructure`, and sets up observers. Most scenario scripts instantiate `Context` to get a working environment.

### Configuration System (`config/`)
Multi-environment config built on Pydantic BaseSettings. Environment selected via `MX_DEX_ENV` env var. Each environment (mainnet, devnet, etc.) is defined in `config/environments/`. All config parameters can be overridden via environment variables or a `.env` file. Priority: env vars > `.env` > environment defaults > base defaults.

### Contract Abstractions (`contracts/`)
All 29 contract types implement `DEXContractInterface` (defined in `contracts/contract_identities.py`), which requires:
- `get_config_dict()` / `load_config_dict()` — JSON serialization for deploy state persistence
- `contract_deploy()` / `contract_start()` — lifecycle management
- `get_contract_tokens()` — token introspection

Versioning uses Enums (`FarmContractVersion`, `PairContractVersion`, etc.) and base classes provide shared behavior (`BaseFarmContract`, `BaseBoostedContract`, `BaseSCWhitelistContract`).

### Deployment (`deploy/`)
`DeployStructure` in `deploy/dex_structure.py` manages the full deployment lifecycle. Each contract type is represented as a `ContractStructure` with bytecode path, deploy function, and deployed instances. State is persisted as JSON files in `deploy/configs-{env}/`.

### Utilities (`utils/`)
- `utils_tx.py` — Transaction building, gas management, ESDT transfers, `NetworkProviders` class
- `utils_chain.py` — `Account`, `BunchOfAccounts`, `WrapperAddress` wrappers around MultiversX SDK
- `utils_generic.py` — Parallel execution, JSON I/O, archive utilities
- `contract_data_fetchers.py` — On-chain data fetching via contract views

### Observers (`trackers/`)
Observer pattern via `Observable`/subscriber classes. Tracks economics for farms, pairs, staking, and metastaking contracts.

### Scenarios (`scenarios/`)
Integration and stress test scripts that exercise the deployed DEX. Run directly as Python scripts (not via pytest).

### Integration Testing (`tests/`)
Pytest-based integration tests running against a MultiversX chain simulator (Docker). Tests live in `tests/integration/{contract_type}/`.

**Key files:**
- `tests/conftest.py` — Fixtures: environment setup, account funding, contract loading, `BlockchainController`
- `tests/environments/chainsim_environment.py` — Chain simulator lifecycle (start, state load, block/epoch control)
- `tools/chain_simulator_connector.py` — Low-level chain sim API (set-state, generate-blocks, state filtering)
- `tests/helpers/` — Test assertion helpers (`PairAssertions`, `TransactionAssertions`, `ContractStateSnapshot`)

**Test files (pair contract — 123 tests, 100% passing):**
- `test_add_liquidity.py` — Add liquidity (initial, slippage, edge cases)
- `test_remove_liquidity.py` — Remove liquidity (partial, full, slippage)
- `test_swap_fixed_input.py` — Swap with fixed input amount
- `test_swap_fixed_output.py` — Swap with fixed output amount
- `test_view_functions.py` — View/query functions (reserves, safe price, fees)
- `test_economic_invariants.py` — k=x*y invariant, fee accumulation, LP value
- `test_multi_user.py` — Concurrent users, LP dilution, fee distribution
- `test_edge_cases.py` — Extreme ratios, dust amounts, pool recovery
- `test_fee_mechanics.py` — Fee collection, accumulation, LP value growth
- `test_state_transitions.py` — Pause/resume lifecycle (requires deployer)
- `test_security.py` — Sandwich attacks, front-running, price manipulation
- `test_overflow_boundary.py` — Large/tiny amounts, BigUint boundaries
- `test_contract_integration.py` — Multi-hop swaps, trusted swap pairs, router admin
- `test_safe_price.py` — TWAP oracle: observations, views, math, manipulation resistance, LP valuation, edge cases (34 tests)

**Running tests:**
```bash
# Prerequisites: Docker running, chain simulator started
docker compose up -d

# Run all pair tests
PYTHONPATH=. python -m pytest tests/integration/pair/ -v

# Run specific test file
PYTHONPATH=. python -m pytest tests/integration/pair/test_swap_fixed_input.py -v

# Run specific test
PYTHONPATH=. python -m pytest tests/integration/pair/test_add_liquidity.py::TestPairAddLiquidity::test_add_liquidity_basic -v
```

**Chain Simulator Architecture:**
- Docker image: `multiversx/chainsimulator:v1.11.3` at `localhost:8085`
- Config: `docker-compose.yaml` with `--rounds-per-epoch=5`
- Pre-saved mainnet state loaded from `states/` folder via `/simulator/set-state` API
- State filtering at load time removes round-dependent data (safe price TWAP observations) and overrides epoch-dependent keys (`firstWeekStartEpoch` → 0) to avoid arithmetic errors

**State Filtering (critical for mainnet state on chain simulator):**
- **Safe price keys**: Pair contracts store TWAP observations tagged with mainnet round numbers (~29M). Chain simulator rounds are much lower, causing `current_round - stored_round` underflow → "cast to i64 error". Filtered via `filter_safe_price_keys()`.
- **firstWeekStartEpoch**: Fees collector stores epoch 862. Chain sim at low epochs gets `week = 0` → "Week 0 is not a valid week". Overridden to 0 via `override_first_week_start_epoch()`, so epoch 7+ gives valid weeks.

**Transaction Processing:**
- Same-shard transactions: 1-2 blocks to finalize
- Cross-shard transactions: Use `generate-blocks-until-transaction-processed/{tx_hash}` endpoint
- NEVER use fixed block counts for cross-shard finalization — always use the dedicated endpoint
- SC deploys go through metachain (cross-shard). The `get_deployed_address_from_tx()` in `utils/utils_tx.py` handles this.

**Known Limitations:**
- **Pair template bytecode**: The Router's `createPair` uses `deployFromSourceContract` to clone a pair template. When loading mainnet state, the template's bytecode may not be in the state dump. The `ensure_pair_template_has_code()` method in `chain_simulator_connector.py` copies bytecode from an existing pair to the template address (called automatically during test setup via `conftest.py`)
- NEVER use `--initial-epoch` with non-zero values in docker-compose — breaks cross-shard transactions permanently ("could not find proof for header")
- Chain simulator retains state between test runs unless restarted (`docker compose down && docker compose up -d`)

## Key Conventions

- All scripts require `PYTHONPATH=.` set at root
- Logging via `get_logger(__name__)` from `utils/logger.py` (color-coded console + file output to `logs/trace.log`)
- Contract labels are string constants defined in `config/__init__.py` (e.g., `PAIRS`, `FARMS_UNLOCKED`, `STAKINGS`)
- Contract bytecode can be local WASM files or GitHub release URLs
- Deployed state saved/loaded via `deployed_*.json` files under the config save path
- `TransactionStatus` fields (`is_successful`, `is_failed`, `is_completed`) are **properties**, not methods — use `tx.status.is_successful` not `tx.status.is_successful()`

## Integration Test Conventions

- **Helpers**: Use `PairAssertions.get_reserves()`, `PairAssertions.assert_constant_product_holds()`, `TransactionAssertions.assert_transaction_success/failed()` from `tests/helpers/`
- **Deployer tests**: The `deployer_account` fixture does NOT auto-fund with EGLD on chain sim. Call `_ensure_deployer_has_egld()` with `test_environment` fixture for admin operations (pause/resume)
- **Reserve-relative amounts**: Tests sharing a session-scoped pool must use reserve-relative amounts (e.g., 0.1% of reserve) instead of fixed values, to avoid failures when prior tests modify reserves
- **Multi-pair tests**: Use `all_pair_contracts` fixture; pairs share WEGLD as a common token for multi-hop swaps
- **Config labels**: `config.FARMS_V2` = "farms_boosted", `config.FARMS_LOCKED` = "farms_locked", `config.PAIRS_V2` = "pairs_v2", `config.ROUTER_V2` = router. There is no `config.FARMS_BOOSTED`
- **Cleanup pattern**: Tests that modify contract state (pause/resume) must use `try/finally` to always restore state for other tests