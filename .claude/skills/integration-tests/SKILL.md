---
name: integration-tests
description: Run and manage integration tests against the MultiversX chain simulator. Use when writing, running, debugging, or fixing integration tests for DEX smart contracts.
allowed-tools: Bash(docker *), Bash(PYTHONPATH=. python -m pytest *), Bash(curl *)
argument-hint: [test-path-or-action]
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

Total setup: ~8 seconds.

## Test Structure

```
tests/
  conftest.py                     # Session fixtures, environment setup
  environments/
    base_environment.py           # TestEnvironment ABC
    chainsim_environment.py       # Chain simulator environment
  integration/
    pair/
      test_add_liquidity.py       # Liquidity addition tests
      test_remove_liquidity.py    # Liquidity removal tests
      test_swap_fixed_input.py    # Fixed input swap tests
      test_swap_fixed_output.py   # Fixed output swap tests
      test_view_functions.py      # View/query tests
      test_economic_invariants.py # k=x*y invariant tests
```

## Key Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `test_environment` | session | Chain simulator lifecycle |
| `network_providers` | session | API + Proxy network access |
| `dex_context` | session | Loaded DEX contracts from `Context` |
| `pair_contract` | function | First deployed pair (index 1) |
| `blockchain_controller` | function | Block/epoch advancement helper |
| `alice`, `bob`, `charlie` | function | Funded test accounts with synced nonces |
| `ensure_esdt_amounts` | function | Callable to fund accounts with exact token amounts |
| `isolated_pair_factory` | function | Creates fresh pair contracts (has cross-shard limitations) |

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
from utils.contract_data_fetchers import PairContractDataFetcher
from multiversx_sdk import Address

fetcher = PairContractDataFetcher(Address.new_from_bech32(pair_contract.address), network_providers.proxy.url)
first_reserve = fetcher.get_data("getReserve", [pair_contract.firstToken.encode()])
```

## State Filtering Details

Located in `tools/chain_simulator_connector.py`:

| Filter | Keys affected | Why needed |
|--------|--------------|------------|
| `filter_safe_price_keys()` | `price_observations.*`, `safe_price_current_index` | Mainnet rounds (~29M) vs chain sim rounds (~100) causes i64 underflow |
| `override_first_week_start_epoch()` | `firstWeekStartEpoch` | Mainnet value 862 requires epoch 869+; override to 0 needs only epoch 7+ |

## Known Limitations

1. **Factory SC deploys fail**: Router's `createPair` deploys child contracts via metachain. The chain simulator doesn't fully support cross-shard SC creation for child contracts. Tests using `isolated_pair_factory` will fail with "Failed to deploy pair".

2. **Never use `--initial-epoch` > 0**: In `docker-compose.yaml`, adding `--initial-epoch=N` with N > 0 permanently breaks cross-shard transactions with "could not find proof for header".

3. **Stale state between runs**: The chain simulator retains all state between test runs. For clean results, restart: `docker compose down && docker compose up -d` (wait ~25 seconds).

4. **`TransactionStatus` properties**: `is_successful`, `is_failed`, `is_completed` are properties, not methods. Use `tx.status.is_successful` not `tx.status.is_successful()`.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| "cast to i64 error" | Safe price round mismatch | Ensure `filter_safe_price=True` in state loading |
| "Week 0 is not a valid week" | firstWeekStartEpoch too high for current epoch | Ensure `override_first_week_start_epoch` runs during state load |
| "account was not found" on SC deploy | Cross-shard deploy not finalized | Use `generate-blocks-until-transaction-processed` |
| "Failed to deploy pair" | Factory-pattern SC deploy limitation | Known chain sim limitation — skip test or use pre-deployed pairs |
| "could not find proof for header" | `--initial-epoch` > 0 used | Remove `--initial-epoch` from docker-compose, restart |
| Tests pass individually but fail together | Stale chain sim state | Restart chain sim between runs |
