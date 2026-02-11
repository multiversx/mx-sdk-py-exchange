# Integration Testing Framework

This directory contains the comprehensive integration testing framework for xExchange smart contracts.

## Overview

This framework performs **black-box testing** of deployed smart contracts on various blockchain environments:
- **Chain Simulator** (local, controllable blockchain)
- **Devnet** (test network with pre-existing state)
- **Shadowfork** (mainnet clone for realistic testing)

## Directory Structure

```
tests/
├── environments/           # Environment abstraction layer
│   ├── base_environment.py          # Abstract base class
│   ├── chainsim_environment.py      # Chain simulator (controllable)
│   ├── devnet_environment.py        # Devnet (live test network)
│   └── shadowfork_environment.py    # Shadowfork (mainnet clone)
│
├── helpers/                # Test utilities and assertions
│   ├── assertions.py                # Black-box state assertions
│   ├── contract_state.py            # State snapshot helpers
│   └── scenarios.py                 # Common test scenarios
│
├── integration/            # Integration tests (happy paths + edge cases)
│   ├── pair/
│   │   ├── test_add_liquidity.py
│   │   ├── test_remove_liquidity.py
│   │   ├── test_swap_fixed_input.py
│   │   └── test_swap_fixed_output.py
│   ├── farm/                        # (future)
│   ├── router/                      # (future)
│   └── metastaking/                 # (future)
│
├── security/               # Security-focused adversarial tests
│   ├── pair/
│   │   ├── test_reentrancy.py
│   │   ├── test_sandwich_attack.py
│   │   └── test_zero_amount_attack.py
│   └── farm/                        # (future)
│
├── stress/                 # Performance and load tests
│   ├── test_concurrent_swaps.py
│   └── test_gas_limits.py
│
├── conftest.py             # Pytest fixtures (shared test setup)
├── pytest.ini              # Pytest configuration
└── README.md               # This file
```

## Key Concepts

### 1. Environment Abstraction

Tests are environment-agnostic. The same test runs on:
- **Chain Simulator**: Full control over block/epoch progression
- **Devnet/Shadowfork**: Graceful degradation (waits for natural block time)

```python
# Test works on ANY environment
def test_swap(pair_contract, alice, blockchain_controller):
    tx_hash = pair_contract.swap_fixed_input(...)
    blockchain_controller.wait_for_tx(tx_hash)  # Adapts to environment
```

### 2. Black-Box Testing

Tests interact with contracts ONLY through:
- **Transactions** (endpoint calls)
- **View Functions** (state queries)
- **Events** (transaction logs)

We do NOT test Python code or internal contract logic - only observable on-chain behavior.

### 3. Test Categories

**Integration Tests** (`integration/`)
- Verify correct operation under normal conditions
- Test edge cases (boundary values, empty pools)
- Validate state transitions

**Security Tests** (`security/`)
- Simulate malicious actors
- Test attack vectors (reentrancy, overflow, front-running)
- Verify error handling

**Stress Tests** (`stress/`)
- Measure gas consumption
- Test concurrent operations
- Validate performance under load

## Running Tests

### Prerequisites

```bash
# Set Python path
export PYTHONPATH=.

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Run All Tests (Chain Simulator)

```bash
pytest --env=chainsim tests/
```

### Run Specific Test Suite

```bash
# Only Pair integration tests
pytest --env=chainsim tests/integration/pair/

# Only security tests
pytest -m security

# Only fast tests (exclude slow)
pytest -m "integration and not slow"
```

### Run on Different Environments

```bash
# Chain Simulator (default)
pytest --env=chainsim tests/integration/pair/

# Devnet (requires connection)
pytest --env=devnet tests/integration/pair/

# Shadowfork (requires shadowfork running)
pytest --env=shadowfork tests/integration/pair/
```

### Specify Chain Simulator Path

```bash
pytest --env=chainsim --docker-path=/path/to/chain-simulator tests/
```

## Writing Tests

### Example: Integration Test

```python
import pytest
from contracts.pair_contract import AddLiquidityEvent
from utils.utils_chain import nominated_amount
from tests.helpers.assertions import SmartContractAssertions

@pytest.mark.integration
def test_add_liquidity(pair_contract, alice, network_proxy, blockchain_controller):
    """Test adding liquidity to pair contract"""

    # 1. Capture initial state (BLACK BOX - view function only)
    old_reserves = fetch_reserves(pair_contract.address, network_proxy)

    # 2. Execute transaction
    event = AddLiquidityEvent(
        tokenA=pair_contract.firstToken,
        amountA=nominated_amount(1000),
        amountAmin=nominated_amount(950),
        tokenB=pair_contract.secondToken,
        amountB=nominated_amount(1000),
        amountBmin=nominated_amount(950)
    )

    alice.sync_nonce(network_proxy)
    tx_hash = pair_contract.add_liquidity(network_proxy, alice, event)
    blockchain_controller.wait_for_tx(tx_hash)

    # 3. Verify state change (BLACK BOX - view function only)
    SmartContractAssertions.assert_reserves_increased(
        pair_contract.address, old_reserves, network_proxy
    )
```

### Example: Security Test

```python
@pytest.mark.security
def test_zero_amount_attack(pair_contract, alice, network_proxy):
    """Verify contract rejects zero-amount swaps"""

    event = SwapFixedInputEvent(
        tokenA=pair_contract.firstToken,
        amountA=0,  # MALICIOUS INPUT
        tokenB=pair_contract.secondToken,
        amountBmin=0
    )

    with pytest.raises(Exception) as exc_info:
        pair_contract.swap_fixed_input(network_proxy, alice, event)

    assert "amount must be greater than zero" in str(exc_info.value).lower()
```

## Fixtures Available

**Environment & Network:**
- `test_environment` - Configured environment (chainsim/devnet/shadowfork)
- `network_proxy` - MultiversX network proxy
- `blockchain_controller` - Helper to control blockchain time

**Contracts:**
- `dex_context` - Fully deployed DEX infrastructure
- `pair_contract` - A Pair contract instance
- `farm_contract` - A Farm contract instance
- `router_contract` - Router contract instance

**Accounts:**
- `deployer_account` - Contract owner (admin permissions)
- `test_accounts` - List of funded user accounts
- `alice`, `bob` - Individual test users

## Test Markers

Use markers to categorize tests:

```python
@pytest.mark.integration  # Integration test
@pytest.mark.security     # Security test
@pytest.mark.slow         # Takes >30 seconds
@pytest.mark.chainsim     # Requires chain simulator
@pytest.mark.devnet       # Requires devnet
```

Run specific markers:
```bash
pytest -m "security and not slow"
```

## Development Status

### ✅ Completed
- Directory structure
- Documentation

### 🚧 In Progress
- Environment abstraction layer
- Core pytest fixtures
- Assertion helpers

### 📋 Planned
- Pair contract integration tests
- Pair contract security tests
- Farm contract tests
- Router contract tests
- Stress/performance tests

## Contributing

When adding new tests:

1. **Choose correct category** (integration, security, or stress)
2. **Use fixtures** for setup (don't repeat code)
3. **Test black-box only** (view functions + transactions)
4. **Add markers** to categorize your test
5. **Document expected behavior** in docstrings

Example template:

```python
@pytest.mark.integration
def test_my_feature(pair_contract, alice, network_proxy, blockchain_controller):
    """
    SCENARIO: [Describe what user does]
    EXPECTED: [Describe expected outcome]
    SECURITY: [Any security considerations]
    """
    # 1. Setup - capture initial state

    # 2. Execute - perform transaction

    # 3. Verify - check state changes
```

## Architecture Principles

1. **Environment Independence** - Same test runs on any environment
2. **Black-Box Only** - Test via external interfaces, not internals
3. **Fixture Reuse** - Share setup via pytest fixtures
4. **Clear Categorization** - Integration vs Security vs Stress
5. **Security First** - Always test malicious inputs
6. **Explicit Expectations** - Document expected behavior clearly

## Smart Contract Security Checklist

When testing a new contract, ensure coverage of:

- [ ] **Happy paths** (normal operations)
- [ ] **Zero amounts** (edge case)
- [ ] **Maximum amounts** (uint64 max, overflow potential)
- [ ] **Insufficient balance** (user doesn't have tokens)
- [ ] **Slippage tolerance** (various percentages)
- [ ] **Reentrancy** (if cross-contract calls exist)
- [ ] **Access control** (unauthorized caller)
- [ ] **Callback failures** (async cross-shard scenarios)
- [ ] **Gas limits** (operations complete within block gas)
- [ ] **Economic invariants** (constant product, reward conservation)

## Contact

For questions about the testing framework, consult the Protocol Guardian (your friendly neighborhood paranoid SDET).
