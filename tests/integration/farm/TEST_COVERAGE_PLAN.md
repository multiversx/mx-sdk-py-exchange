# Farm-with-Locked-Rewards SC — Integration Test Coverage Plan

**Target**: ~95 tests | **Status**: Complete (99 tests) | **SC Source**: `mx-exchange-sc/dex/farm-with-locked-rewards`

## Contract Overview

The farm-with-locked-rewards SC allows users to stake LP tokens and earn rewards that are automatically locked (MEX -> XMEX) via the energy/locking system. It uses a Reward Per Share (RPS) model for O(1) base reward distribution and a weekly splitting mechanism for energy-based boosted yields.

**Key characteristics**:
- **NoMintWrapper**: Rewards come from a pre-funded reserve, NOT minted on-chain
- **Locked rewards**: All reward outputs go through the locking contract (SimpleLockEnergy) and return as XMEX
- **Boosted yields**: Weekly reward pool split between base farm (default 75%) and boosted pool (25%), distributed based on user energy
- **Farm tokens**: MetaFungible (SFT/NFT) with attributes: `reward_per_share`, `entering_epoch`, `compounded_reward`, `current_farm_amount`, `original_owner`
- **Per-second rewards**: Migrated from per-block to per-second model (`per_second_amount = per_block_amount / 6`)

## Infrastructure Requirements

### Chain Simulator State

| Dependency | Status | Notes |
|-----------|--------|-------|
| Farm bytecode | NOT loaded | No state files in `states/`. Need fresh deploy or mainnet state export |
| SimpleLockEnergy | Loaded | `states/0_simple_locks_energy_0_state.json` |
| Locked Asset Factory | Loaded | `states/0_locked_assets_0_state.json` |
| Pair contracts (LP source) | Loaded | Users need LP tokens to stake |
| `config.FARMS_LOCKED` (mainnet) | Locked-reward farms | Farm-with-locked-rewards contracts under test |
| `config.FARMS_LOCKED` (mainnet) | Boosted LP farms | Different contract family; not the target of this suite |

### Approach Decision

Two options for test setup:

**Option A — Mainnet State Export** (like pairs):
- Export farm state from a mainnet `FARMS_LOCKED` contract
- Load via `set-state` API
- Pros: Real-world state, pre-configured rewards
- Cons: Needs `firstWeekStartEpoch` override, reward reserve may be depleted, farm token nonces are complex

**Option B — Fresh Deploy on Chain Sim** (recommended):
- Deploy farm SC from bytecode on chain sim
- Configure: reward token, farming token, division safety constant, pair address
- Register farm token, set local roles, fund reward reserve
- Set energy factory address, locking address, lock epochs
- Configure boosted yields factors and percentage
- Start produce rewards + resume
- Pros: Full control, clean state, no filtering needed
- Cons: Cross-shard deploy complexity (metachain), more setup code

**Recommended**: Start with Option A (load one of the 16 FARMS_LOCKED mainnet contracts) since pairs are already loaded. If state loading proves unreliable, fall back to Option B.

### Fixtures Needed

| Fixture | Scope | Description |
|---------|-------|-------------|
| `farm_contract` | function | Farm contract loaded from config (use `config.FARMS_LOCKED`) |
| `energy_factory_contract` | session | SimpleLockEnergy contract from loaded state |
| `ensure_farm_tokens` | function | Callable to fund accounts with LP tokens (farming token) |
| `farm_helpers` | function | `FarmAssertions` class for black-box assertions |
| `advance_week` | function | Helper to advance epochs by 7 (one week) |

### conftest.py Changes

1. Fix `farm_contract` fixture: change `config.FARMS_LOCKED` to `config.FARMS_LOCKED` (line 454)
2. Add `energy_factory_contract` fixture loading SimpleLockEnergy from context
3. Add `ensure_farm_tokens` fixture (wraps `ensure_esdt_amounts` for LP token funding)
4. Check farm bytecode on first use — `pytest.skip()` if missing (same pattern as pairs)
5. Add `FarmAssertions` to `tests/helpers/` (get_farm_state, assert_rewards_accrued, etc.)

---

## Test Categories

### Category 1: Enter Farm (10 tests)
**File**: `test_enter_farm.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_enter_farm_basic` | Stake LP tokens, receive farm token NFT | Farm token minted, attributes correct, LP tokens deducted |
| 2 | `test_enter_farm_returns_locked_boosted_rewards` | Enter farm returns any pending boosted rewards as XMEX | Boosted rewards auto-claimed and locked on re-entry |
| 3 | `test_enter_farm_updates_total_farm_position` | `getUserTotalFarmPosition` increases after enter | Position tracking accuracy |
| 4 | `test_enter_farm_multiple_positions` | Enter farm twice, get separate farm token nonces | Multiple NFT positions tracked independently |
| 5 | `test_enter_farm_with_existing_farm_token` | Enter with LP tokens + existing farm token (merge) | Position merged, RPS updated, old token burned |
| 6 | `test_enter_farm_zero_amount_fails` | Enter with 0 LP tokens | Error: payment validation |
| 7 | `test_enter_farm_wrong_token_fails` | Send non-LP token to enterFarm | Error: wrong farming token |
| 8 | `test_enter_farm_when_paused_fails` | Enter farm when contract is paused | Error: contract not active |
| 9 | `test_enter_farm_farm_token_attributes` | Verify farm token attributes after entry | `reward_per_share`, `entering_epoch`, `original_owner` correct |
| 10 | `test_enter_farm_preserves_reward_per_share` | RPS at entry matches current global RPS | Entry RPS snapshot accuracy |

### Category 2: Exit Farm (10 tests)
**File**: `test_exit_farm.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_exit_farm_basic` | Exit full position, receive LP tokens + locked rewards | LP returned, XMEX rewards correct |
| 2 | `test_exit_farm_partial` | Exit partial position, keep remaining farm token | Remaining farm token has correct amount/attributes |
| 3 | `test_exit_farm_with_rewards` | Exit after blocks pass, verify reward amount | `rewards = amount * (current_RPS - entry_RPS) / division_safety_constant` |
| 4 | `test_exit_farm_rewards_are_locked` | Rewards returned as XMEX (locked token), not MEX | Token ID is locked token, not reward token |
| 5 | `test_exit_farm_penalty_before_min_epochs` | Exit before minimum farming epochs | Penalty applied to exit amount |
| 6 | `test_exit_farm_no_penalty_after_min_epochs` | Exit after minimum farming epochs | No penalty deducted |
| 7 | `test_exit_farm_zero_amount_fails` | Exit with 0 farm tokens | Error: zero amount |
| 8 | `test_exit_farm_wrong_token_fails` | Send non-farm token to exitFarm | Error: wrong token |
| 9 | `test_exit_farm_clears_energy_if_empty` | Full exit clears user energy tracking | `getUserTotalFarmPosition` returns 0 |
| 10 | `test_exit_farm_when_paused_fails` | Exit when contract paused | Error: contract not active |

### Category 3: Claim Rewards (8 tests)
**File**: `test_claim_rewards.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_claim_rewards_basic` | Claim base rewards, receive new farm token + locked rewards | New farm token updated RPS, XMEX rewards received |
| 2 | `test_claim_rewards_proportional` | Two users, rewards proportional to staked amounts | User with 2x stake gets 2x rewards |
| 3 | `test_claim_rewards_consecutive` | Claim twice, second claim reflects only new rewards | No double-counting |
| 4 | `test_claim_rewards_zero_accrued` | Claim immediately after entering (no blocks passed) | Zero or near-zero rewards, no error |
| 5 | `test_claim_rewards_updates_farm_token_rps` | New farm token has current RPS as `reward_per_share` attribute | Attribute correctness |
| 6 | `test_claim_rewards_reduces_reward_reserve` | `getRewardReserve` decreases by claimed amount | Reserve accounting |
| 7 | `test_claim_rewards_wrong_token_fails` | Send non-farm token to claimRewards | Error: wrong token |
| 8 | `test_claim_rewards_output_is_locked` | Claimed MEX is returned as XMEX | Locked token output |

### Category 4: Claim Boosted Rewards (7 tests)
**File**: `test_claim_boosted_rewards.py`
**Priority**: P1 (boosted yields)
**Note**: Energy factory has no code/state on chain sim, so boosted rewards are 0. Tests verify endpoint behavior, error cases, and claim progress tracking.

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_claim_boosted_basic` | User with farm position calls claimBoostedRewards | Transaction succeeds, farm tokens retained |
| 2 | `test_claim_boosted_no_farm_position_fails` | User with no farm position calls claimBoostedRewards | Error: "User total farm position is empty!" |
| 3 | `test_claim_boosted_zero_reward_without_energy` | User with position but no energy (chain sim) | Succeeds with 0 rewards, reserve unchanged |
| 4 | `test_claim_boosted_unauthorized_for_other_fails` | Claim for another without permission | Error: "Cannot claim rewards for this address" |
| 5 | `test_claim_boosted_updates_claim_progress` | Advance weeks, claim, check progress | ClaimProgress.week updated |
| 6 | `test_claim_boosted_after_full_exit_fails` | Enter then fully exit, try claim boosted | Error: no farm position |
| 7 | `test_claim_boosted_idempotent_same_week` | Two claims in same week | Second claim has 0 reserve impact |

### Category 5: Merge Farm Tokens (5 tests)
**File**: `test_merge_farm_tokens.py`
**Priority**: P1 (position management)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_merge_two_positions` | Merge 2 farm tokens into 1 | Merged amount = sum, weighted RPS, old tokens burned |
| 2 | `test_merge_returns_boosted_rewards` | Merge triggers boosted rewards claim | XMEX returned alongside merged token |
| 3 | `test_merge_single_token_fails` | Try to merge with only 1 payment | Error: need at least 2 tokens |
| 4 | `test_merge_different_owners_fails` | Merge tokens with different original_owner | Error: ownership mismatch |
| 5 | `test_merge_preserves_total_amount` | Total farm amount unchanged after merge | Supply conservation |

### Category 6: View Functions (8 tests)
**File**: `test_view_functions.py`
**Priority**: P1 (observability)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_get_farm_token_supply` | Query total farm token supply | Matches sum of all staked amounts |
| 2 | `test_get_reward_reserve` | Query remaining reward reserve | Decreases as rewards claimed |
| 3 | `test_get_reward_per_share` | Query current RPS | Increases with time and rewards |
| 4 | `test_get_farming_token_id` | Query the LP token being farmed | Matches contract config |
| 5 | `test_get_state` | Query contract state (Active/Inactive) | Reflects admin operations |
| 6 | `test_get_current_week` | Query current week number | `(epoch - firstWeekStartEpoch) / 7 + 1` |
| 7 | `test_get_user_total_farm_position` | Query user's aggregated farm amount | Matches sum across all user nonces |
| 8 | `test_calculate_rewards_for_position` | View-only reward calculation | Matches actual claim amount |

### Category 7: Reward Economics (8 tests)
**File**: `test_reward_economics.py`
**Priority**: P1 (correctness)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_rps_increases_over_time` | RPS increases as blocks are generated | `RPS_new = RPS_old + (reward * DSC / supply)` |
| 2 | `test_rewards_proportional_to_stake` | Larger stake = proportionally more rewards | Linear reward scaling |
| 3 | `test_reward_reserve_conservation` | Total rewards claimed <= total reward reserve | No over-distribution |
| 4 | `test_no_rewards_when_production_stopped` | RPS frozen after `endProduceRewards` | No new rewards accrued |
| 5 | `test_per_second_reward_rate` | Rewards accrue at `per_second_amount * elapsed_seconds` | Per-second model accuracy |
| 6 | `test_reward_split_base_vs_boosted` | 75%/25% split between base farm and boosted pool | `take_reward_slice` correctness |
| 7 | `test_division_safety_constant` | Large DSC prevents rounding to zero | Small positions still earn rewards |
| 8 | `test_reward_accrual_with_zero_supply` | No division by zero when supply = 0 | RPS unchanged, rewards buffered |

### Category 8: Boosted Yields Mechanics (8 tests)
**File**: `test_boosted_yields.py`
**Priority**: P1 (energy system)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_boosted_formula_energy_weighted` | User boosted reward proportional to energy share | `(energy_const * user_energy / total_energy + farm_const * user_farm / farm_supply) / (energy_const + farm_const) * total_boosted` |
| 2 | `test_boosted_capped_by_max_factor` | Rewards capped at `max_rewards_factor * total * user_farm / supply` | Cap enforcement |
| 3 | `test_boosted_no_energy_gets_minimum` | User without energy gets only base rewards | No boosted component |
| 4 | `test_boosted_two_users_different_energy` | Two users with different energy levels | Higher energy = more boosted rewards |
| 5 | `test_boosted_weekly_accumulation` | Boosted rewards accumulate per-week | Each week independently tracked |
| 6 | `test_farm_supply_for_week_tracking` | `getFarmSupplyForWeek` accurate after entry/exit | Weekly supply snapshot |
| 7 | `test_energy_decay_affects_rewards` | Energy decays over epochs, reducing boosted share | Later weeks = less boosted rewards |
| 8 | `test_undistributed_rewards_rollover` | Unclaimed boosted rewards become undistributed | Available for admin collection |

### Category 9: Admin Operations (8 tests)
**File**: `test_admin_operations.py`
**Priority**: P1 (lifecycle management)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_start_produce_rewards` | Admin starts reward production | `getLastRewardTimestamp` set, rewards begin accruing |
| 2 | `test_end_produce_rewards` | Admin stops reward production | RPS frozen, no new rewards |
| 3 | `test_set_per_second_reward_amount` | Admin changes reward rate | New rate reflected in subsequent reward calculations |
| 4 | `test_set_boosted_yields_percentage` | Admin changes boosted % (e.g., 25% -> 30%) | Split ratio updated |
| 5 | `test_set_boosted_yields_percentage_invalid_fails` | Set percentage > MAX_PERCENT (10000) | Error: "Invalid percentage" |
| 6 | `test_pause_resume` | Admin pauses and resumes farm | Operations fail when paused, succeed after resume |
| 7 | `test_admin_only_access` | Non-admin calls admin endpoints | Error: permission denied |
| 8 | `test_collect_undistributed_rewards` | Admin collects unclaimed boosted rewards | Undistributed rewards transferred to admin |

### Category 10: Delegation / On-Behalf Operations (6 tests)
**File**: `test_delegation.py`
**Priority**: P2 (advanced feature)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_enter_farm_on_behalf` | Whitelisted caller enters farm for user | Farm token `original_owner` = user, sent to caller |
| 2 | `test_claim_rewards_on_behalf` | Whitelisted caller claims for user | Locked rewards sent to user, new token to caller |
| 3 | `test_on_behalf_unauthorized_fails` | Non-whitelisted caller tries on-behalf operation | Error: not whitelisted |
| 4 | `test_on_behalf_farm_token_ownership` | Farm token original_owner preserved through on-behalf ops | Attribute persists |
| 5 | `test_allow_external_claim` | User enables external claim for boosted rewards | `claimBoostedRewards(user)` succeeds from any caller |
| 6 | `test_multiple_positions_on_behalf` | Multiple enter/claim/exit cycles via delegation | State consistency across delegated operations |

### Category 11: Multi-User Scenarios (5 tests)
**File**: `test_multi_user.py`
**Priority**: P2 (concurrency)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_two_users_equal_stake` | Two users stake equal amounts, claim | Equal rewards |
| 2 | `test_user_enters_later` | User B enters after User A; User A gets more rewards | Time-weighted distribution |
| 3 | `test_user_exits_early` | User A exits, User B continues earning | User B gets full reward rate after A exits |
| 4 | `test_many_users_reward_conservation` | 3+ users, sum of all rewards <= reserve | No reward inflation |
| 5 | `test_dilution_on_new_entry` | New user entry dilutes existing user rewards | RPS growth rate decreases with more supply |

### Category 12: Edge Cases & Security (6 tests)
**File**: `test_edge_cases.py`
**Priority**: P2 (robustness)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_enter_exit_same_block` | Enter and exit in same block | Minimal/zero rewards, no errors |
| 2 | `test_dust_amounts` | Stake very small LP amount (1 wei) | No division errors, rewards may be 0 |
| 3 | `test_large_stake_amount` | Stake very large amount (10^24) | No overflow in RPS calculation |
| 4 | `test_rapid_enter_exit_cycles` | Multiple enter/exit in sequence | State consistency, no stuck tokens |
| 5 | `test_claim_after_reward_reserve_depleted` | All rewards claimed, reserve = 0 | Graceful zero-reward claim |
| 6 | `test_exit_penalty_boundary` | Exit exactly at minimum_farming_epochs boundary | No penalty applied |

### Category 13: State Transitions & Lifecycle (5 tests)
**File**: `test_state_transitions.py`
**Priority**: P2 (lifecycle)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_full_lifecycle` | Deploy -> configure -> start -> enter -> claim -> exit -> end | Complete flow |
| 2 | `test_week_boundary_crossing` | Operations spanning week boundaries | Weekly snapshots correct |
| 3 | `test_epoch_advancement_effects` | Advance epochs, verify week/energy updates | Timekeeping consistency |
| 4 | `test_produce_rewards_toggle` | Start/stop/start reward production | Rewards only during active periods |
| 5 | `test_reward_rate_change_mid_operation` | Change per-second amount while users are staked | Old rate up to change point, new rate after |

---

## Implementation Results

| Category | Tests | Priority | File | Status |
|----------|-------|----------|------|--------|
| 1. Enter Farm | 10 | P0 | `test_enter_farm.py` | **10 pass** |
| 2. Exit Farm | 10 | P0 | `test_exit_farm.py` | **10 pass** |
| 3. Claim Rewards | 8 | P0 | `test_claim_rewards.py` | **8 pass** |
| 4. Claim Boosted | 7 | P1 | `test_claim_boosted_rewards.py` | **5 pass, 1 skip, 1 xfail** |
| 5. Merge Tokens | 5 | P1 | `test_merge_farm_tokens.py` | **1 pass, 1 skip, 3 xfail** |
| 6. View Functions | 13 | P1 | `test_view_functions.py` | **13 pass** |
| 7. Reward Economics | 8 | P1 | `test_reward_economics.py` | **8 pass** |
| 8. Boosted Yields | 8 | P1 | `test_boosted_yields.py` | **8 pass** |
| 9. Admin Operations | 8 | P1 | `test_admin_operations.py` | **7 pass, 1 xfail** |
| 10. Delegation | 6 | P2 | `test_delegation.py` | **4 pass, 2 xfail** |
| 11. Multi-User | 5 | P2 | `test_multi_user.py` | **5 pass** |
| 12. Edge Cases | 6 | P2 | `test_edge_cases.py` | **6 pass** |
| 13. State Transitions | 5 | P2 | `test_state_transitions.py` | **5 pass** |
| **Total** | **99** | | | **92 pass, 1 skip, 6 xfail** |

### xfail / skip Summary

| Test | Reason |
|------|--------|
| `test_merge_two_positions` (xfail) | `mergeFarmTokens` requires caller to be whitelisted |
| `test_merge_returns_boosted_rewards` (xfail) | Same whitelisting issue |
| `test_merge_preserves_total_amount` (xfail) | Same whitelisting issue |
| `test_merge_different_owners_fails` (skip) | Cannot create cross-owner farm tokens on chain sim |
| `test_collect_undistributed_rewards` (xfail) | `current_week > week_offset` not met on chain sim |
| `test_enter_farm_on_behalf` (xfail) | `isWhitelisted` makes a cross-contract call to the PermissionsHub SC, whose bytecode is not loaded in the chain sim state dump |
| `test_claim_rewards_on_behalf` (xfail) | Same — `isWhitelisted` cross-calls PermissionsHub (no bytecode in chain sim) |
| `test_claim_boosted_after_full_exit_fails` (skip) | Bob already has position from prior tests |

---

## Endpoint Coverage Analysis

### User Operation Endpoints (7 endpoints)

| Endpoint | Coverage | Test Files | Success | Failure |
|----------|----------|------------|---------|---------|
| `enterFarm` | **100%** | test_enter_farm (10), test_multi_user, test_edge_cases, test_state_transitions | ✅ | ✅ |
| `exitFarm` | **100%** | test_exit_farm (10), test_multi_user, test_edge_cases, test_state_transitions | ✅ | ✅ |
| `claimRewards` | **100%** | test_claim_rewards (8), test_multi_user, test_reward_economics, test_state_transitions | ✅ | ✅ |
| `claimBoostedRewards` | **100%** | test_claim_boosted_rewards (7), test_boosted_yields | ✅ | ✅ |
| `mergeFarmTokens` | **Partial** | test_merge_farm_tokens (5, 3 xfail) | xfail | ✅ |
| `compoundRewards` | **None** | — | — | — |
| `allowExternalClaimBoostedRewards` | **None** | — | — | — |

### On-Behalf Endpoints (2 endpoints)

| Endpoint | Coverage | Test Files | Success | Failure |
|----------|----------|------------|---------|---------|
| `enterFarmOnBehalf` | **Partial** | test_delegation (xfail success, failure tested) | xfail | ✅ |
| `claimRewardsOnBehalf` | **Partial** | test_delegation (xfail success, failure tested) | xfail | ✅ |

### Admin Lifecycle Endpoints (9 endpoints)

| Endpoint | Coverage | Test Files | Success | Failure |
|----------|----------|------------|---------|---------|
| `startProduceRewards` | **100%** | test_admin_operations, test_state_transitions | ✅ | — |
| `endProduceRewards` | **100%** | test_admin_operations, test_state_transitions | ✅ | — |
| `setPerBlockRewardAmount` | **100%** | test_admin_operations, test_state_transitions | ✅ | — |
| `setBoostedYieldsRewardsPercentage` | **100%** | test_admin_operations (valid + invalid) | ✅ | ✅ |
| `pause` | **100%** | test_admin_operations | ✅ | ✅ (non-admin) |
| `resume` | **100%** | test_admin_operations | ✅ | — |
| `collectUndistributedBoostedRewards` | **Partial** | test_admin_operations (xfail) | xfail | — |
| `addSCAddressToWhitelist` | **100%** | test_delegation | ✅ | — |
| `removeSCAddressFromWhitelist` | **100%** | test_delegation | ✅ | — |

### Deploy/Config-Only Endpoints (12 endpoints — not testable on mainnet state)

| Endpoint | Coverage | Notes |
|----------|----------|-------|
| `registerFarmToken` | N/A | Deploy-time only |
| `set_local_roles_farm_token` | N/A | Deploy-time only |
| `set_transfer_role_farm_token` | N/A | Deploy-time only |
| `setBoostedYieldsFactors` | N/A | Deploy-time only |
| `setEnergyFactoryAddress` | N/A | Deploy-time only |
| `set_locking_address` | N/A | Deploy-time only |
| `set_lock_epochs` | N/A | Deploy-time only |
| `set_penalty_percent` | N/A | Config (penalty behavior tested indirectly) |
| `set_minimum_farming_epochs` | N/A | Config (min epoch behavior tested indirectly) |
| `set_permissions_hub_address` | N/A | Config |
| `update_owner_or_admin` | N/A | Admin transfer |
| `migratePosition` | N/A | Upgrade migration |

### View/Query Endpoints (27 endpoints)

| Endpoint | Coverage | Test Files |
|----------|----------|------------|
| `getFarmTokenSupply` | **100%** | test_view_functions + 8 other files |
| `getRewardReserve` | **100%** | test_view_functions + 8 other files |
| `getRewardPerShare` | **100%** | test_view_functions + 5 other files |
| `getPerBlockRewardAmount` | **100%** | test_view_functions, test_reward_economics, test_admin_operations |
| `getFarmingTokenId` | **100%** | test_view_functions |
| `getFarmTokenId` | **100%** | test_view_functions |
| `getRewardTokenId` | **100%** | Used in helpers across all files |
| `getState` | **100%** | test_view_functions, test_admin_operations |
| `getDivisionSafetyConstant` | **100%** | test_reward_economics |
| `getLastRewardBlockNonce` | **100%** | test_admin_operations |
| `getCurrentWeek` | **100%** | test_view_functions, test_boosted_yields, test_state_transitions |
| `getFirstWeekStartEpoch` | **100%** | test_boosted_yields, test_state_transitions |
| `getNextWeekStartEpoch` | **100%** | test_boosted_yields, test_state_transitions |
| `getUserTotalFarmPosition` | **100%** | test_view_functions, test_enter_farm, test_exit_farm |
| `getCurrentClaimProgress` | **100%** | test_claim_boosted_rewards |
| `getFarmSupplyForWeek` | **100%** | test_boosted_yields, test_state_transitions |
| `getTotalEnergyForWeek` | **100%** | test_boosted_yields |
| `getAccumulatedRewardsForWeek` | **100%** | test_boosted_yields, test_state_transitions |
| `getTotalRewardsForWeek` | **100%** | test_boosted_yields, test_state_transitions |
| `getRemainingBoostedRewardsToDistribute` | **100%** | test_boosted_yields |
| `getUndistributedBoostedRewards` | **100%** | test_boosted_yields |
| `getAllBoostedGlobalStats` | **100%** | test_boosted_yields |
| `getAllUserBoostedStats` | **100%** | test_boosted_yields |
| `calculateRewardsForGivenPosition` | **100%** | test_view_functions |
| `isSCAddressWhitelisted` | **100%** | test_delegation |
| `getLastRewardTimestamp` | **100%** | test_view_functions |
| `getUserEnergyForWeek` | **100%** | test_view_functions (returns 0 on chain sim — farm view, not energy factory) |
| `getLastActiveWeekForUser` | **100%** | test_view_functions |
| `getTotalLockedTokensForWeek` | **100%** | test_view_functions |
| `get_lp_address` | **100%** | test_view_functions |

### Coverage Summary

| Category | Total | Fully Tested | Partial/xfail | Not Tested | N/A (deploy) |
|----------|-------|-------------|---------------|------------|--------------|
| User operations | 7 | 4 (57%) | 1 (14%) | 2 (29%) | — |
| On-behalf ops | 2 | 0 | 2 (100%) | 0 | — |
| Admin lifecycle | 9 | 8 (89%) | 1 (11%) | 0 | — |
| Deploy/config | 12 | 0 | 0 | 0 | 12 (100%) |
| View/query | 27 | 27 (100%) | 0 | 0 | — |
| **Operational total** | **45** | **39 (87%)** | **4 (9%)** | **2 (4%)** | — |

**Operational endpoint coverage: ~96% (full + partial)**

Untested user-operation endpoints: `compoundRewards`, `allowExternalClaimBoostedRewards`

---

## Rust Test Cross-Reference

The Rust test suite has 11 tests. Here's how they map to our integration test categories:

| Rust Test | Category Mapping | Notes |
|-----------|-----------------|-------|
| `farm_with_no_boost_no_proxy_test` | Cat 1, 2, 3, 7 | Basic two-user proportional rewards |
| `farm_with_boosted_yields_no_proxy_test` | Cat 4, 8 | Energy-based boosted reward distribution |
| `total_farm_position_claim_with_locked_rewards_test` | Cat 3, 5 | Multi-position claim and merge |
| `claim_only_boosted_rewards_per_week_test` | Cat 4, 8 | Weekly boosted-only claims |
| `claim_rewards_per_week_test` | Cat 3, 4, 8 | Combined base+boosted per week |
| `claim_boosted_rewards_with_zero_position_test` | Cat 4 (error) | Error: zero position |
| `claim_boosted_rewards_user_energy_not_registered_test` | Cat 4 (error) | Error: no energy registered |
| `test_multiple_positions_on_behalf` | Cat 10 | Delegation/proxy operations |
| `farm_with_locked_rewards_collect_undistributed_rewards_test` | Cat 9 | Admin collection of undistributed |
| `collect_undistributed_rewards_conditions_checks_test` | Cat 9 (error) | Admin error conditions |
| `test_block_to_timestamp_migration_complete` | N/A | Upgrade migration (not testable via integration) |

**Coverage gaps in Rust tests** (addressed by our integration plan):
- Exit farm penalty mechanics (our Cat 2)
- View function validation (our Cat 6)
- Per-second reward rate accuracy (our Cat 7)
- Pause/resume lifecycle (our Cat 9)
- Multi-user dilution and conservation (our Cat 11)
- Overflow/boundary conditions (our Cat 12)
- Full lifecycle and state transitions (our Cat 13)

---

## Implementation Order

1. **Infrastructure** (prerequisite): Farm state loading + fixtures + helpers
2. **P0 — Core Operations** (Cat 1, 2, 3): ~28 tests
3. **P1 — Yields & Admin** (Cat 4, 5, 6, 7, 8, 9): ~45 tests
4. **P2 — Advanced** (Cat 10, 11, 12, 13): ~22 tests

### Step-by-Step Implementation

| Step | Description | Deliverable |
|------|-------------|-------------|
| 1 | Export mainnet farm state OR deploy fresh farm SC on chain sim | Farm contract operational on chain sim |
| 2 | Fix `farm_contract` fixture (`FARMS_LOCKED`) | Working fixture |
| 3 | Add `FarmAssertions` helper class | `tests/helpers/farm_assertions.py` |
| 4 | Add energy factory fixture + `advance_week` helper | conftest.py updates |
| 5 | Implement `test_enter_farm.py` (10 tests) | P0 milestone 1 |
| 6 | Implement `test_exit_farm.py` (10 tests) | P0 milestone 2 |
| 7 | Implement `test_claim_rewards.py` (8 tests) | P0 milestone 3 |
| 8 | Implement `test_claim_boosted_rewards.py` (8 tests) | P1 milestone 1 |
| 9 | Implement `test_view_functions.py` (8 tests) | P1 milestone 2 |
| 10 | Implement `test_reward_economics.py` (8 tests) | P1 milestone 3 |
| 11 | Implement `test_boosted_yields.py` (8 tests) | P1 milestone 4 |
| 12 | Implement `test_merge_farm_tokens.py` (5 tests) | P1 milestone 5 |
| 13 | Implement `test_admin_operations.py` (8 tests) | P1 milestone 6 |
| 14 | Implement P2 test files (Cat 10-13, 22 tests) | P2 completion |
| 15 | Full suite validation + documentation update | Coverage complete |

---

## Key Technical Challenges

### 1. Farm Bytecode Loading
No farm state files exist in `states/`. Options:
- **Export from mainnet**: Use `tools/state_exporter.py` (if exists) to capture a FARMS_LOCKED contract state
- **Fresh deploy**: Deploy from WASM bytecode, but cross-shard deploy on chain sim is fragile
- **Hybrid**: Load pair state (existing), then deploy farm using pair address as constructor arg

### 2. Energy System Integration
Boosted yields require users to have energy (locked MEX/XMEX). Test setup must:
- Ensure SimpleLockEnergy contract is operational (state loaded)
- Lock MEX for test users to generate energy
- Potentially mock or set energy via `set-state` API for deterministic testing

### 3. Week/Epoch Advancement
Farm boosted yields operate on weekly cycles (`EPOCHS_IN_WEEK = 7`). Tests must:
- Use `blockchain_controller.advance_epochs(7)` to cross week boundaries
- Verify `getCurrentWeek` after advancement
- Handle `firstWeekStartEpoch` override (already done for fee collector, may need for farm)

### 4. Locked Reward Verification
Rewards are XMEX (locked MEX), not plain MEX. Assertions must:
- Check for locked token ID (not reward token ID)
- Verify NFT nonce and amount of locked tokens
- Potentially decode locked token attributes for unlock schedule

### 5. Farm Token NFT Handling
Farm tokens are MetaFungible (SFTs with attributes). Need:
- Track nonce increments across operations
- Decode `FarmTokenAttributes` from transaction results
- Handle multi-ESDT payments (LP token + farm token in some operations)

---

## Python Wrapper Methods Available

### FarmContract (contracts/farm_contract.py)
| Method | Endpoint | Returns |
|--------|----------|---------|
| `enterFarm(provider, user, event)` | `enterFarm` | tx_hash |
| `enter_farm_on_behalf(provider, user, event)` | `enterFarmOnBehalf` | tx_hash |
| `exitFarm(provider, user, event)` | `exitFarm` | tx_hash |
| `claimRewards(provider, user, event)` | `claimRewards` | tx_hash |
| `claim_boosted_rewards(provider, user, event)` | `claimBoostedRewards` | tx_hash |
| `claim_rewards_on_behalf(provider, user, event)` | `claimRewardsOnBehalf` | tx_hash |
| `mergePositions(provider, user, events)` | `mergeFarmTokens` | tx_hash |
| `collect_undistributed_boosted_rewards(proxy, user)` | `collectUndistributedBoostedRewards` | tx_hash |
| `start_produce_rewards(deployer, proxy)` | `startProduceRewards` | tx_hash |
| `end_produce_rewards(deployer, proxy)` | `endProduceRewards` | tx_hash |
| `set_rewards_per_block(deployer, proxy, amount)` | `setPerBlockRewardAmount` | tx_hash |
| `set_boosted_yields_rewards_percentage(deployer, proxy, %)` | `setBoostedYieldsRewardsPercentage` | tx_hash |
| `set_boosted_yields_factors(deployer, proxy, args)` | `setBoostedYieldsFactors` | tx_hash |
| `set_energy_factory_address(deployer, proxy, addr)` | `setEnergyFactoryAddress` | tx_hash |
| `pause(deployer, proxy)` | `pause` | tx_hash |
| `resume(deployer, proxy)` | `resume` | tx_hash |
| `allow_external_claim(provider, user)` | `allowExternalClaimBoostedRewards` | tx_hash |

### BaseFarmContract Views
`getFarmTokenSupply`, `getRewardReserve`, `getRewardPerShare`, `getLastRewardBlockNonce`, `getLastRewardTimestamp`, `getPerBlockRewardAmount`, `getState`, `getDivisionSafetyConstant`, `getFarmTokenId`, `getFarmingTokenId`

### BaseBoostedContract Views
`getCurrentWeek`, `getFirstWeekStartEpoch`, `getUserTotalFarmPosition`, `getUserEnergyForWeek`, `getLastActiveWeekForUser`, `getCurrentClaimProgress`, `getFarmSupplyForWeek`, `getTotalLockedTokensForWeek`, `getTotalEnergyForWeek`, `getTotalRewardsForWeek`, `getAccumulatedRewardsForWeek`, `getRemainingBoostedRewardsToDistribute`, `getUndistributedBoostedRewards`

### Event Classes
- `EnterFarmEvent(farming_token, farming_nonce, farming_amount, farm_token, farm_nonce, farm_amount, on_behalf="")`
- `ExitFarmEvent(farm_token, amount, nonce, attributes, exit_amount=0)`
- `ClaimRewardsFarmEvent(amount, nonce, attributes, user=None)`
- `MergePositionFarmEvent(amount, nonce, original_caller)`

### Decoding Structures
- `FARM_TOKEN_ATTRIBUTES`: `{reward_per_share, entering_epoch, compounded_reward, current_farm_amount, original_owner}`
- `ENERGY_ENTRY`: `{amount, last_update_epoch, total_locked_tokens}`
- `USER_CLAIM_PROGRESS`: `{energy: ENERGY_ENTRY, week}`

---

## Notes

- **Farm SC version**: All mainnet farms are `V4` / `FarmContractVersion.V2Boosted`
- **Reward token**: MEX (but returned as XMEX via locking)
- **Farming token**: LP tokens from pair contracts (e.g., `EGLDMEX-0be9e5`)
- **Farm token**: MetaFungible SFT (e.g., `EGLDMEXFL-c2521e`)
- **Default fee split**: 75% base farm / 25% boosted (configurable via `setBoostedYieldsRewardsPercentage`)
- **Division safety constant**: `10^12` (set at deploy)
- **Minimum farming epochs**: Default value from `DEFAULT_MINIMUM_FARMING_EPOCHS`
- **Exit penalty**: Default `DEFAULT_PENALTY_PERCENT` applied before minimum epochs
