# Pair Contract Integration Test Coverage Plan

**Last Updated:** 2026-02-10
**Current Coverage:** ~47.4% (45/95 tests complete)
**Target Coverage:** 95%

---

## 📊 Progress Overview

- ✅ **Completed:** 45 tests (47.4%)
- 🚧 **In Progress:** 0 tests
- ⏳ **Planned:** 50 tests

---

## Test Categories

### 🌊 Category 1: Liquidity Operations (21 tests) - 18/21 COMPLETE ✅

#### Add Liquidity (11 tests)
- [x] `test_add_initial_liquidity_empty_pool` - **COMPLETED** ✅
  - Issues tokens, deploys pair, adds initial liquidity
  - File: `test_add_liquidity.py:51-227`
- [x] `test_add_liquidity_to_existing_pool` - **REVIEWED & ENHANCED** ✅
  - Added: Pool initialization for test independence
  - Added: LP token verification (minting and balance)
  - Added: Exact reserve increase verification
  - Added: Pool ratio maintenance check (<0.1% change)
  - File: `test_add_liquidity.py:228-353`
- [x] `test_add_liquidity_various_slippage` - **REVIEWED** ⚠️
  - Status: Needs enhancement - currently all parameterized tests succeed
  - TODO: Add negative test case (slippage exceeded scenario)
  - File: `test_add_liquidity.py:356-457`
- [x] `test_add_liquidity_minimum_amounts` - **REVIEWED & ENHANCED** ✅
  - Added: Exact reserve increase assertions
  - Added: LP token minting verification
  - Added: Specific error message validation
  - Improved: Branching logic for success/failure cases
  - File: `test_add_liquidity.py:462-587`
- [x] `test_add_liquidity_imbalanced_amounts` - **COMPLETED** ✅
  - User provides imbalanced token amounts
  - Contract should adjust and return excess
  - File: `test_add_liquidity.py:777-962`
- [ ] `test_add_liquidity_slippage_exceeded`
  - Pool ratio changes beyond slippage tolerance
  - Transaction should fail with proper error
- [x] `test_add_liquidity_zero_amounts` - **COMPLETED** ✅
  - Attempt to add zero of both tokens
  - Should fail with validation error
  - File: `test_add_liquidity.py:516-594`
- [x] `test_add_liquidity_wrong_token_order` - **COMPLETED** ✅
  - Send second token as first, first as second
  - Contract should handle or reject
  - File: `test_add_liquidity.py:682-791`
- [x] `test_add_liquidity_single_token` - **COMPLETED** ✅
  - Send only one token (not both)
  - Should fail - both tokens required
  - File: `test_add_liquidity.py:596-680`
- [ ] `test_add_liquidity_multiple_users_sequential`
  - Alice, Bob, Charlie add liquidity sequentially
  - Verify proportional LP distribution
- [ ] `test_add_liquidity_with_fees_accumulated`
  - Add liquidity after swaps have accumulated fees
  - LP value should include accrued fees

#### Remove Liquidity (10 tests) - **ALL COMPLETED** ✅
- [x] `test_remove_liquidity_partial` - **COMPLETED** ✅
  - Remove 50% of LP tokens
  - Verifies proportional token returns, reserve decreases, ratio maintenance
  - Validates constant product decreases proportionally
  - File: `test_remove_liquidity.py:36-260`
- [x] `test_remove_liquidity_full` - **COMPLETED** ✅
  - Burn all LP tokens (100% withdrawal)
  - Handles minimum liquidity locking mechanism
  - Verifies Alice gets back her full contribution
  - File: `test_remove_liquidity.py:262-454`
- [x] `test_remove_liquidity_minimum_amounts` - **COMPLETED** ✅
  - Set minimum output amounts with 5% slippage tolerance
  - Verify slippage protection works, user receives at least minimum
  - File: `test_remove_liquidity.py:456-603`
- [x] `test_remove_liquidity_slippage_protection` - **COMPLETED** ✅
  - Tests 1%, 5%, 10% slippage tolerance levels
  - Minimum amounts protect user at each level
  - File: `test_remove_liquidity.py:605-730`
- [x] `test_remove_liquidity_slippage_exceeded` - **COMPLETED** ✅
  - Sets impossible minimum amounts (200% of expected)
  - Transaction fails, LP tokens NOT burned, balances unchanged
  - File: `test_remove_liquidity.py:732-869`
- [x] `test_remove_liquidity_zero_lp_tokens` - **COMPLETED** ✅
  - Attempt to burn 0 LP tokens
  - Should fail validation, state unchanged
  - File: `test_remove_liquidity.py:871-967`
- [x] `test_remove_liquidity_more_than_owned` - **COMPLETED** ✅
  - Try to burn 2x LP tokens than user owns
  - Fails with insufficient balance, all state unchanged
  - File: `test_remove_liquidity.py:969-1083`
- [x] `test_remove_liquidity_after_swaps` - **COMPLETED** ✅
  - Bob performs 5 swaps changing pool ratio
  - Alice removes liquidity at new ratio, benefits from fees
  - Verifies k increased due to accumulated fees
  - File: `test_remove_liquidity.py:1085-1272`
- [x] `test_remove_liquidity_multiple_users` - **COMPLETED** ✅
  - Alice, Bob, Charlie add liquidity with different amounts
  - Each removes in reverse order, receives proportional share
  - Verifies LP distribution fairness and isolation
  - File: `test_remove_liquidity.py:1274-1543`
- [x] `test_remove_liquidity_to_empty_pool` - **COMPLETED** ✅
  - Last LP removes all remaining liquidity
  - Pool maintains minimum locked liquidity (prevents manipulation)
  - Pool ratio preserved even with tiny reserves
  - File: `test_remove_liquidity.py:1545-1724`

---

### 🔄 Category 2: Swap Operations (18 tests) - 18/18 COMPLETE ✅

#### Swap Fixed Input (10 tests) - **ALL COMPLETED** ✅
- [x] `test_swap_fixed_input_first_to_second` - **COMPLETED** ✅
  - Swap exact amount of token A for token B
  - Verifies output within slippage, reserves changed, k increased, user balances
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_second_to_first` - **COMPLETED** ✅
  - Swap exact amount of token B for token A (reverse direction)
  - Validates bidirectional swaps work identically
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_minimum_output` - **COMPLETED** ✅
  - Set amountBmin to exactly getAmountOut value (0% slippage)
  - Tests tightest possible slippage protection
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_slippage_exceeded` - **COMPLETED** ✅
  - Set amountBmin to 200% of expected (impossible)
  - Transaction fails, reserves and balances unchanged
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_large_amount` - **COMPLETED** ✅
  - Swap 40% of first reserve, verifies large price impact
  - Compares rate with small swap to validate bonding curve
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_small_amount` - **COMPLETED** ✅
  - Dust amount swap (1000 atomic units)
  - Succeeds or fails gracefully, state consistent either way
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_zero_amount` - **COMPLETED** ✅
  - Attempt swap with 0 input
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_exceeds_reserve` - **COMPLETED** ✅
  - Swap 10x the first reserve with impossible min output
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_wrong_token` - **COMPLETED** ✅
  - Send FAKE-aaaaaa token not in the pair
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_input.py`
- [x] `test_swap_fixed_input_multiple_sequential` - **COMPLETED** ✅
  - 10 sequential swaps alternating direction
  - k monotonically increases, reserves stay positive throughout
  - File: `test_swap_fixed_input.py`

#### Swap Fixed Output (8 tests) - **ALL COMPLETED** ✅
- [x] `test_swap_fixed_output_first_to_second` - **COMPLETED** ✅
  - Request exact amount of tokenB, verify exact output received
  - Input deducted <= amountAmax, k increased
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_second_to_first` - **COMPLETED** ✅
  - Request exact amount of tokenA using tokenB as input
  - Same assertions mirrored
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_maximum_input` - **COMPLETED** ✅
  - Set amountAmax tightly (5% above estimated)
  - Validates protection against excessive spending
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_max_input_exceeded` - **COMPLETED** ✅
  - Set amountAmax to 50% of estimated (too low)
  - Transaction fails, reserves and balances unchanged
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_large_output` - **COMPLETED** ✅
  - Request 40% of second reserve as output
  - Large input required, k holds, exact output received
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_exceeds_reserve` - **COMPLETED** ✅
  - Request 2x second reserve (impossible)
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_zero_amount` - **COMPLETED** ✅
  - Request 0 tokens as output
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_output.py`
- [x] `test_swap_fixed_output_wrong_token` - **COMPLETED** ✅
  - Request FAKE-aaaaaa as output token
  - Transaction fails, reserves unchanged
  - File: `test_swap_fixed_output.py`

---

### 💰 Category 3: Economic Invariants (7 tests) - 3/7 COMPLETE ✅

- [x] `test_constant_product_maintained_after_swaps` - **COVERED** ✅
  - Covered by: `test_swap_fixed_input_multiple_sequential` (10 swaps, `assert_constant_product_holds` after each, `k_final > k_initial`)
  - Also verified in: every swap test calls `assert_constant_product_holds(k_before)`
- [ ] `test_fees_accumulate_correctly`
  - Execute swaps with 0.3% fee
  - Verify fees remain in reserves
- [ ] `test_lp_token_value_increases_with_fees`
  - LP redemption value should increase as fees accumulate
  - Compare LP value before/after swaps
- [ ] `test_no_arbitrage_opportunity`
  - After normal operations
  - Verify no profitable arbitrage exists
- [x] `test_reserves_never_negative` - **COVERED** ✅
  - Covered by: `test_swap_fixed_input_large_amount`, `test_swap_fixed_input_multiple_sequential`, `test_swap_fixed_output_large_output`
  - All assert `reserves[0] > 0` and `reserves[1] > 0` after operations including extreme cases
- [ ] `test_lp_supply_consistency`
  - Sum of all user LP holdings = total supply
  - Track multiple users
- [x] `test_price_impact_calculation` - **COVERED** ✅
  - Covered by: `test_swap_fixed_input_large_amount`
  - Queries `getAmountOut` for 1 token and 40% of reserve, compares rates, asserts `large_rate < small_rate`

---

### 🔄 Category 4: State Transitions (3 tests)

- [ ] `test_pair_state_active_to_inactive`
  - Pause the pair contract (if owner)
  - Verify state changes
- [ ] `test_pair_state_inactive_operations_fail`
  - All user operations should fail when paused
  - Test swap, add/remove liquidity
- [ ] `test_pair_state_resume`
  - Resume paused pair
  - All operations work again

---

### 👁️ Category 5: View Functions (7 tests) - 3/7 COMPLETE ✅

- [x] `test_get_amount_out` - **COVERED** ✅
  - Covered by: `test_swap_fixed_input_minimum_output`
  - Queries `getAmountOut`, sets `amountBmin = expected_output` (0% slippage), asserts `actual_output >= expected_output`
  - Direct view-vs-execution comparison
- [x] `test_get_equivalent` - **COVERED** ✅
  - Covered by: `test_add_liquidity_to_existing_pool`, `test_add_liquidity_various_slippage`, `test_add_liquidity_imbalanced_amounts`
  - All query `getEquivalent` to calculate second token amount, then verify contract accepts those amounts and reserves increase by exact values
- [x] `test_get_reserves_and_total_supply` - **COVERED** ✅
  - Covered by: every test via `PairAssertions.get_reserves()` which calls `getReservesAndTotalSupply`
  - Values verified against expected state changes (reserve increases/decreases, LP supply changes)
- [ ] `test_get_tokens_for_given_position`
  - Calculate underlying tokens for LP position
  - Verify proportional calculation
- [ ] `test_get_fee_percentages`
  - Query total fee and special fee
  - Verify configuration
- [ ] `test_get_safe_price`
  - Query safe price oracle
  - Verify TWAP calculation
- [ ] `test_get_price_observation`
  - Query historical price observations
  - Verify data points stored correctly

---

### 🛡️ Category 6: Security & Attack Vectors (9 tests)

#### Front-Running Protection (3 tests)
- [ ] `test_sandwich_attack_protection`
  - Simulate sandwich attack scenario
  - Slippage protection should prevent profit
- [ ] `test_front_running_liquidity_add`
  - Front-run liquidity addition with swap
  - Should not profit significantly
- [ ] `test_front_running_liquidity_remove`
  - Front-run liquidity removal
  - Slippage protection works

#### Reentrancy & Callbacks (3 tests)
- [ ] `test_no_reentrancy_on_add_liquidity`
  - Attempt reentrancy during add liquidity
  - Should be blocked by guards
- [ ] `test_no_reentrancy_on_remove_liquidity`
  - Attempt reentrancy during remove
  - Should be blocked
- [ ] `test_no_reentrancy_on_swap`
  - Attempt reentrancy during swap
  - Should be blocked

#### Integer Overflow/Underflow (2 tests)
- [ ] `test_no_overflow_large_amounts`
  - Test with amounts near u64::MAX
  - All operations should handle safely
- [ ] `test_no_underflow_edge_cases`
  - Test with minimum amounts
  - No underflow in calculations

#### Price Manipulation (1 test)
- [ ] `test_safe_price_oracle_manipulation`
  - Attempt to manipulate TWAP
  - Safe price should resist single-block manipulation

---

### 👥 Category 7: Multi-User Scenarios (5 tests) - 1/5 COMPLETE ✅

- [x] `test_concurrent_liquidity_providers` - **COVERED** ✅
  - Covered by: `test_remove_liquidity_multiple_users`
  - Alice, Bob, Charlie add different amounts, verifies proportional LP distribution and each receives proportional share on withdrawal
- [ ] `test_concurrent_swaps`
  - Multiple users swap simultaneously
  - All succeed, correct amounts
- [ ] `test_lp_dilution`
  - Early LP adds liquidity
  - Later LPs dilute early position correctly
- [ ] `test_proportional_fee_distribution`
  - Fees accumulated from swaps
  - Each LP gets proportional share on exit
- [ ] `test_user_isolation`
  - One user's actions don't affect others
  - Balance isolation verified

---

### ⚠️ Category 8: Edge Cases & Boundary Conditions (6 tests) - 2/6 COMPLETE ✅

- [x] `test_pool_empty_after_all_liquidity_removed` - **COVERED** ✅
  - Covered by: `test_remove_liquidity_full` and `test_remove_liquidity_to_empty_pool`
  - Both use isolated pools, remove all LP tokens, verify minimum locked liquidity remains and reserves approach zero
- [ ] `test_first_liquidity_provider_advantage`
  - First LP sets initial price ratio
  - Can create imbalanced pool
- [ ] `test_extreme_price_ratios`
  - Create pool with 1:1000000 ratio
  - Verify operations still work
- [x] `test_dust_amount_handling` - **COVERED** ✅
  - Covered by: `test_add_liquidity_minimum_amounts` (1 atomic unit add liquidity) and `test_swap_fixed_input_small_amount` (1000 atomic units swap)
  - Both handle success or graceful failure, verify state consistency
- [ ] `test_maximum_amount_handling`
  - Near u64::MAX amounts
  - Verify safe math operations
- [ ] `test_pool_recovery_after_drain`
  - Drain pool completely
  - Re-add liquidity and verify works

---

### 💵 Category 9: Fee Mechanics (5 tests)

- [ ] `test_standard_fee_collection`
  - Verify 0.3% fee on all swaps
  - Fee remains in reserves
- [ ] `test_special_fee_if_configured`
  - If special fee set
  - Verify correct fee calculation
- [ ] `test_fees_collector_integration`
  - If fees collector configured
  - Fees sent to collector address
- [ ] `test_fee_accumulation_over_multiple_swaps`
  - Execute 100 swaps
  - Verify cumulative fees correct
- [ ] `test_lp_value_increase_from_fees`
  - LP token redemption value
  - Increases proportionally with fees

---

### 🔗 Category 10: Integration with Other Contracts (4 tests)

- [ ] `test_router_multi_hop_swap`
  - Swap A→B→C through router
  - Verify correct final output
- [ ] `test_farm_staking_lp_tokens`
  - LP tokens can be staked in farm
  - Verify token transfer works
- [ ] `test_proxy_contract_interactions`
  - If proxy contract set
  - Test proxy operations
- [ ] `test_trusted_swap_pair_integration`
  - Add trusted swap pair
  - Verify integration works

---

### 💪 Category 11: Stress & Performance Tests (4 tests)

- [ ] `test_high_volume_swaps`
  - Execute 1000+ swaps sequentially
  - All succeed within gas limits
- [ ] `test_many_small_liquidity_additions`
  - 100+ users add small amounts
  - LP distribution correct
- [ ] `test_pool_under_heavy_use`
  - Mixed operations at scale
  - Add/remove/swap randomly
- [ ] `test_gas_limits_not_exceeded`
  - All operations stay within gas limits
  - No transaction failures due to gas

---

## 📝 Testing Guidelines

### Test Structure
Each test should follow this pattern:
```python
def test_operation_scenario(
    self,
    pair_contract: PairContract,
    alice: Account,
    network_providers,
    blockchain_controller,
    ensure_esdt_amounts
):
    """
    SCENARIO: Clear description

    GIVEN: Initial state
    WHEN: Action performed
    THEN: Expected outcome

    SECURITY: Security considerations (if applicable)
    """
    logger.info("TEST: Description")

    # 1. Setup & arrange
    # 2. Execute action
    # 3. Assert results
    # 4. Verify invariants
```

### Assertion Best Practices
- Use `PairAssertions` helper methods
- Use `TransactionAssertions` for tx verification
- Always verify transaction succeeded before state checks
- Check economic invariants (k=xy, fees, LP value)
- Log intermediate values for debugging

### Black-Box Testing Principles
- Query state via view functions only
- Execute actions via contract endpoints
- No direct state manipulation
- No access to internal contract logic
- Verify behavior through observable effects

---

## 🎯 Priority Implementation Order

### Phase 1: Core Functionality (Priority: HIGH)
**Target:** 40% coverage
1. Swap Fixed Input tests (10 tests)
2. Remove Liquidity tests (10 tests)
3. Economic Invariants (7 tests)
4. View Functions (7 tests)

### Phase 2: Security & Edge Cases (Priority: MEDIUM)
**Target:** 70% coverage
1. Swap Fixed Output tests (8 tests)
2. Security & Attack Vectors (9 tests)
3. Multi-User Scenarios (5 tests)
4. Edge Cases (6 tests)

### Phase 3: Advanced Features (Priority: LOW)
**Target:** 95% coverage
1. State Transitions (3 tests)
2. Fee Mechanics (5 tests)
3. Integration Tests (4 tests)
4. Stress Tests (4 tests)

---

## 📊 Estimated Effort

| Category | Tests | Effort (hours) | Priority |
|----------|-------|----------------|----------|
| Add Liquidity | 11 | 8 | ✅ DONE |
| Remove Liquidity | 10 | 12 | ✅ DONE |
| Swap Fixed Input | 10 | 14 | ✅ DONE |
| Swap Fixed Output | 8 | 10 | ✅ DONE |
| Economic Invariants | 7 (3 covered) | 8 | HIGH |
| View Functions | 7 (3 covered) | 6 | HIGH |
| Security | 9 | 16 | MEDIUM |
| Multi-User | 5 (1 covered) | 10 | MEDIUM |
| Edge Cases | 6 (2 covered) | 12 | MEDIUM |
| State Transitions | 3 | 4 | LOW |
| Fee Mechanics | 5 | 8 | LOW |
| Integration | 4 | 12 | LOW |
| Stress Tests | 4 | 8 | LOW |
| **TOTAL** | **95** | **128 hours** | |

---

## 🚀 Next Steps

1. ✅ Complete `test_add_initial_liquidity_empty_pool` - **DONE**
2. ✅ Review and update existing add liquidity tests - **DONE**
3. ✅ Implement Remove Liquidity tests (10 tests) - **DONE**
4. ✅ Implement Swap Fixed Input tests (10 tests) - **DONE**
5. ✅ Implement Swap Fixed Output tests (8 tests) - **DONE**
6. Start Phase 1 continued: Add remaining Economic Invariant tests (4 remaining: fees, LP value, arbitrage, LP supply)
7. Add remaining View Function tests (4 remaining: position, fees, safe price, observations)
8. Continue with Phase 2: Security (9), Multi-User (4 remaining), Edge Cases (4 remaining)
9. Phase 3: State Transitions (3), Fee Mechanics (5), Integration (4), Stress (4)

---

## 📌 Notes

- All tests must use black-box testing approach
- Token issuance transactions require 8 blocks wait time
- Use `ensure_esdt_amounts` fixture for precise token funding
- Always decode binary token identifiers: `topics[0].decode('utf-8')`
- Follow existing test patterns and naming conventions
- Add detailed docstrings with GIVEN/WHEN/THEN/SECURITY sections

---

**Repository:** mx-sdk-py-exchange
**Test File:** `tests/integration/pair/test_add_liquidity.py` (and future files)
**Framework:** pytest with MultiversX SDK
**Environment:** Chain Simulator (chainsim) for fast testing
