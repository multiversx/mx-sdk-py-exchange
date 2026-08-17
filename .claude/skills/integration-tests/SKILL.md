---
name: integration-tests
description: Run and manage integration tests against the MultiversX chain simulator. Use when writing, running, debugging, or fixing integration tests for DEX smart contracts.
---

# Integration Test Framework

## Quick Start

```bash
# 1. Start chain simulator (fresh state)
docker compose down && docker compose up -d
# Wait ~25 seconds for startup

# 2. Run tests
PYTHONPATH=. python -m pytest tests/integration/pair/ -v
```

## Chain Simulator

- **Image**: `multiversx/chainsimulator:v1.11.3`
- **Proxy**: `http://localhost:8085`
- **Config**: `docker-compose.yaml` with `--rounds-per-epoch=5`
- **State folder**: `states/` (pre-saved mainnet contract state)

### Useful API endpoints

```bash
# Check if running
curl -s http://localhost:8085/network/status/0 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Epoch: {d[\"data\"][\"status\"][\"erd_epoch_number\"]}')"

# Generate blocks manually
curl -X POST http://localhost:8085/simulator/generate-blocks/1

# Process specific transaction (cross-shard safe)
curl -X POST http://localhost:8085/simulator/generate-blocks-until-transaction-processed/{tx_hash}

# Advance to specific epoch
curl -X POST http://localhost:8085/simulator/generate-blocks-until-epoch-reached/10
```

## Test Environment Setup Flow

When `pytest` starts, `tests/conftest.py` creates a `ChainsimEnvironment` that:

1. Connects to existing chain simulator (or starts one via docker)
2. Advances to epoch 10 (~4 seconds with rounds-per-epoch=5)
3. Loads mainnet state from `states/` with filtering:
   - **Safe price keys removed**: Prevents "cast to i64 error" from round mismatch
   - **firstWeekStartEpoch overridden to 0**: Prevents "Week 0 is not a valid week" at low epochs
4. Generates 1 block to finalize state
5. Initializes `Context` with deployed contracts
6. Ensures pair template has bytecode (copies from existing pair if missing, needed for Router's `createPair`)

Total setup: ~8 seconds.

## Test Structure

```
tests/
  conftest.py                       # Session fixtures, environment setup
  helpers/
    __init__.py                     # Exports PairAssertions, TransactionAssertions, etc.
    assertions.py                   # Black-box assertion helpers
    contract_state.py               # ContractStateSnapshot, MultiContractSnapshot
  environments/
    base_environment.py             # TestEnvironment ABC
    chainsim_environment.py         # Chain simulator environment
  integration/
    pair/
      test_add_liquidity.py         # Liquidity addition (11 tests)
      test_remove_liquidity.py      # Liquidity removal (10 tests)
      test_swap_fixed_input.py      # Fixed input swaps (10 tests)
      test_swap_fixed_output.py     # Fixed output swaps (8 tests)
      test_view_functions.py        # View/query functions (7 tests)
      test_economic_invariants.py   # k=x*y invariant, fees (4 tests)
      test_multi_user.py            # Concurrent users, dilution (4 tests)
      test_edge_cases.py            # Extreme ratios, dust, recovery (3 tests)
      test_fee_mechanics.py         # Fee collection & accumulation (5 tests)
      test_state_transitions.py     # Pause/resume lifecycle (3 tests)
      test_security.py              # Sandwich, front-running, oracle (4 tests)
      test_overflow_boundary.py     # Large/tiny amounts, BigUint (3 tests)
      test_contract_integration.py  # Multi-hop, trusted pairs, router admin (3 tests)
      test_safe_price.py            # TWAP oracle: observations, views, math, manipulation, LP valuation (34 tests)
      TEST_COVERAGE_PLAN.md         # Coverage tracking (100%, 123/123 tests)
```

## Key Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `test_environment` | session | Chain simulator lifecycle |
| `network_providers` | session | API + Proxy network access |
| `dex_context` | session | Loaded DEX contracts from `Context` |
| `pair_contract` | function | Pair at index 1 from `config.PAIRS_V2` |
| `all_pair_contracts` | function | All pairs from `config.PAIRS_V2` (for multi-hop) |
| `router_contract` | function | Router from `config.ROUTER_V2` |
| `deployer_account` | session | DEX owner — does NOT auto-fund EGLD on chain sim |
| `blockchain_controller` | function | Block/epoch advancement helper |
| `alice`, `bob`, `charlie` | function | Funded test accounts with synced nonces |
| `ensure_esdt_amounts` | function | Callable to fund accounts with exact token amounts |
| `isolated_pair_factory` | function | Creates fresh pair contracts (has cross-shard limitations) |

### Deployer account EGLD funding

The `deployer_account` starts with 0 EGLD on chain sim. Tests using deployer (pause/resume, admin ops) must fund it first:

```python
def _ensure_deployer_has_egld(deployer_account, test_environment, network_providers):
    from tests.environments import ChainsimEnvironment
    if isinstance(test_environment, ChainsimEnvironment) and test_environment.chain_sim:
        account_data = network_providers.proxy.get_account(deployer_account.address)
        if account_data.balance < nominated_amount(10):
            test_environment.chain_sim.fund_users_w_egld(
                [deployer_account.address.to_bech32()], nominated_amount(10)
            )
```

## Writing Tests

### Basic pattern

```python
@pytest.mark.integration
class TestMyFeature:
    def test_something(self, pair_contract, alice, network_providers, blockchain_controller, ensure_esdt_amounts):
        # 1. Fund account
        ensure_esdt_amounts(alice, {
            pair_contract.firstToken: nominated_amount(100),
            pair_contract.secondToken: nominated_amount(100),
        })

        # 2. Execute transaction
        alice.sync_nonce(network_providers.proxy)
        tx_hash = pair_contract.some_operation(network_providers, alice, args)

        # 3. Wait for processing
        blockchain_controller.wait_for_tx(tx_hash)

        # 4. Assert results
        tx_result = network_providers.proxy.get_transaction(tx_hash)
        assert tx_result.status.is_successful  # Property, NOT method!
```

### Transaction processing rules

- **Same-shard tx**: `blockchain_controller.wait_for_tx(tx_hash)` handles it
- **Cross-shard tx**: Same call — uses `generate-blocks-until-transaction-processed` internally
- **NEVER** use `advance_blocks(N)` with a fixed N for cross-shard finalization
- **NEVER** call `tx.status.is_successful()` with parentheses — it's a property

### Checking reserves and state

```python
# Preferred: use test helpers
from tests.helpers import PairAssertions, TransactionAssertions

# Get reserves (returns tuple: first_reserve, second_reserve, lp_supply)
reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)

# Assert k invariant holds (k_after >= k_before)
PairAssertions.assert_constant_product_holds(pair_contract.address, k_before, network_providers.proxy)

# Assert transaction success/failure
TransactionAssertions.assert_transaction_success(tx_hash, network_providers.proxy)
TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

# Low-level: direct data fetcher
from utils.contract_data_fetchers import PairContractDataFetcher
from multiversx_sdk import Address

fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
first_reserve = fetcher.get_data("getReserve", [pair_contract.firstToken.encode()])
```

### Reserve-relative amounts (pool-state independence)

Tests sharing a session-scoped pool must use reserve-relative amounts instead of fixed values,
since prior tests modify reserves:

```python
reserves = PairAssertions.get_reserves(pair_contract.address, network_providers.proxy)
swap_amount = reserves[0] // 1000  # 0.1% of first reserve
```

### Admin operations (pause/resume, trusted pairs)

Tests modifying contract state must use `try/finally` to restore state:

```python
def test_pause_resume(self, pair_contract, deployer_account, ...):
    _ensure_deployer_has_egld(deployer_account, test_environment, network_providers)
    deployer_account.sync_nonce(network_providers.proxy)
    tx_pause = pair_contract.set_active_no_swaps(deployer_account, network_providers.proxy)
    blockchain_controller.wait_for_tx(tx_pause)
    try:
        # ... test paused behavior ...
    finally:
        deployer_account.sync_nonce(network_providers.proxy)
        tx_resume = pair_contract.resume(deployer_account, network_providers.proxy)
        blockchain_controller.wait_for_tx(tx_resume)
```

## State Filtering Details

Located in `tools/chain_simulator_connector.py`:

| Filter | Keys affected | Why needed |
|--------|--------------|------------|
| `filter_safe_price_keys()` | `price_observations.*`, `safe_price_current_index` | Mainnet rounds (~29M) vs chain sim rounds (~100) causes i64 underflow |
| `override_first_week_start_epoch()` | `firstWeekStartEpoch` | Mainnet value 862 requires epoch 869+; override to 0 needs only epoch 7+ |

## Config Label Reference

| Constant | Value | Notes |
|----------|-------|-------|
| `config.PAIRS_V2` | "pairs_v2" | Pair contracts; fixture uses index 1 |
| `config.ROUTER_V2` | router label | Router contract |
| `config.FARMS_V2` | "farms_boosted" | Boosted farms (NOT `FARMS_BOOSTED`) |
| `config.FARMS_LOCKED` | "farms_locked" | Locked reward farms |

## Known Limitations

1. **Pair template bytecode**: Router's `createPair` uses `deployFromSourceContract` to clone a pair template. When loading mainnet state, the template's bytecode may not be included. Fixed by `ensure_pair_template_has_code()` in `chain_simulator_connector.py` — copies bytecode from an existing pair to the template address via set-state API. Called automatically during test setup via `conftest.py`.

2. **Never use `--initial-epoch` > 0**: In `docker-compose.yaml`, adding `--initial-epoch=N` with N > 0 permanently breaks cross-shard transactions with "could not find proof for header".

3. **Stale state between runs**: The chain simulator retains all state between test runs. For clean results, restart: `docker compose down && docker compose up -d` (wait ~25 seconds).

4. **`TransactionStatus` properties**: `is_successful`, `is_failed`, `is_completed` are properties, not methods. Use `tx.status.is_successful` not `tx.status.is_successful()`.

5. **No `config.FARMS_BOOSTED`**: The attribute is `config.FARMS_V2` (maps to "farms_boosted" internally). Using `config.FARMS_BOOSTED` raises `AttributeError`.

6. **Chain sim timeout under load**: Heavy swap sequences (e.g., safe price manipulation resistance tests) can cause SDK `TimeoutError`. The `_perform_swap` helper in `test_safe_price.py` includes retry logic (3 attempts with block advancement between retries).

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| "cast to i64 error" | Safe price round mismatch | Ensure `filter_safe_price=True` in state loading |
| "Week 0 is not a valid week" | firstWeekStartEpoch too high for current epoch | Ensure `override_first_week_start_epoch` runs during state load |
| "account was not found" on createPair | Pair template has no bytecode | `ensure_pair_template_has_code()` copies bytecode from existing pair via set-state |
| "could not find proof for header" | `--initial-epoch` > 0 used | Remove `--initial-epoch` from docker-compose, restart |
| Tests pass individually but fail together | Stale chain sim state | Restart chain sim between runs |
| "Slippage exceeded" on multi-hop swap | Intermediate amount too large for second pool | Use reserve-relative amounts (0.1%) and cap intermediate to 0.1% of target pool reserve |
| `AttributeError: FARMS_BOOSTED` | Wrong config label | Use `config.FARMS_V2` (maps to "farms_boosted") |
| `TimeoutError: Fetching transaction` | Chain sim slow under heavy swap load | Retry logic in `_perform_swap` (test_safe_price.py) handles this automatically |
