# Farm Staking SC — Integration Test Coverage Plan

**Target**: ~95 tests | **Status**: Complete | **SC Source**: `mx-exchange-sc/farm-staking/farm-staking`

## Contract Overview

The farm staking SC allows users to **single-stake tokens** (e.g., RIDE, UTK, ASH) and earn **the same token** as rewards. Unlike LP farming where users stake LP tokens and earn MEX/XMEX, here the farming token and reward token are identical. Rewards come from a pre-funded reserve (`rewardCapacity`), topped up by admin via `topUpRewards`.

**Key characteristics**:
- **Same-token staking**: `farming_token == reward_token` (e.g., stake RIDE, earn RIDE)
- **APR cap**: Rewards are bounded by `max_apr` — `min(per_second_rewards, apr_bounded_rewards)` prevents excessive distribution
- **Unbonding period**: Unstaking creates an unbond NFT with `unlock_epoch = current + min_unbond_epochs`; user must call `unbondFarm` after the unlock period
- **Reward capacity model**: Admin deposits rewards via `topUpRewards`; `withdrawRewards` claws back uncollected portion
- **Compound rewards**: Unique endpoint — claims rewards and reinvests them in the same position (since reward == farming token)
- **Boosted yields (V3)**: Weekly reward pool split between base farm and boosted pool, distributed based on user energy
- **Farm tokens**: MetaFungible (SFT/NFT) with attributes: `reward_per_share`, `compounded_reward`, `current_farm_amount`, `original_owner` (V2+)
- **Unbond tokens**: Separate NFT with attributes: `unlock_epoch`
- **Per-second rewards**: `per_second_amount` with APR cap: `amount_apr_bounded = DSC * stake * max_apr / MAX_PERCENT / SECONDS_IN_YEAR`

**Key formula (APR-capped rewards)**:
```
rewards_unbounded = elapsed_seconds * per_second_reward_amount * user_stake / total_supply
rewards_apr_bounded = elapsed_seconds * total_supply * max_apr / 10_000 / 31_536_000
actual_rewards = min(rewards_unbounded, rewards_apr_bounded) * user_stake / total_supply
```

## Infrastructure Requirements

### Chain Simulator State

| Dependency | Status | Notes |
|-----------|--------|-------|
| Staking SC bytecode | NOT loaded | No state files in `states/`. Need mainnet state export |
| `config.STAKINGS_V2` (mainnet) | 8 contracts | V2: RIDE, ZPAY, ITHEUM, BHAT, UTK, CRT, ASH, FOXSY |
| `config.STAKINGS_BOOSTED` (mainnet) | 3 contracts | V3Boosted: A1X, DRX, BOD |
| Pair contracts (LP source) | Loaded | Not needed — staking uses raw tokens, not LP tokens |
| Energy factory | Loaded (no code) | Needed for V3Boosted energy queries; returns 0 on chain sim |

### Approach: Mainnet State Export

Export state from one of the 11 mainnet staking contracts and load via `set-state` API, same approach as pairs and farms.

**Best candidate**: RIDE staking (`erd1qqqqqqqqqqqqqpgqmqq78c5htmdnws8hm5u4suvags36eq092jpsaxv3e7`)
- V2, well-established, `max_apr=2500` (25%), `unbond_epochs=10`
- RIDE token widely used across DEX

**Alternative**: A1X staking (`erd1qqqqqqqqqqqqqpgqv9h8yej6gdddmpdcad96fukxgutvr2sfkp2s7pe5gg`)
- V3Boosted, `max_apr=10000` (100%), boosted yields enabled

**Recommendation**: Export RIDE (V2) as primary test target. If V3Boosted-specific tests are needed, also export A1X. Start with one contract, add second if needed.

**State export steps**:
1. Export staking contract state + accounts from mainnet
2. Filter safe price keys (if any — staking may not have them)
3. Override `firstWeekStartEpoch` → 0 (for V3Boosted only)
4. Load via `set-state` API
5. Fund test accounts with farming token (RIDE) via `set-state`

### Fixtures Needed

| Fixture | Scope | Description |
|---------|-------|-------------|
| `staking_contract` | session | StakingContract loaded from `config.STAKINGS_V2` (or `STAKINGS_BOOSTED`) |
| `all_staking_contracts` | session | All staking contracts from config |
| `ensure_staking_tokens` | function | Fund accounts with farming token (RIDE/A1X) |
| `deployer_account` | session | Reuse existing — for admin operations (pause/resume/topup) |

### conftest.py Changes

1. Add `staking_contract` fixture loading first contract from `config.STAKINGS_V2`
2. Add bytecode check — `pytest.skip()` if staking contract has no code on chain sim
3. Add `ensure_staking_tokens` fixture — fund accounts with farming token via `set-state`
4. Reuse existing `deployer_account`, `blockchain_controller`, `network_providers` fixtures

---

## Test Categories

### Category 1: Stake Farm (10 tests)
**File**: `test_stake_farm.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_stake_farm_basic` | Stake farming tokens, receive farm token NFT | Farm token minted, amount correct, farming tokens deducted |
| 2 | `test_stake_farm_updates_total_position` | `getUserTotalFarmPosition` increases after staking | Position tracking accuracy |
| 3 | `test_stake_farm_multiple_positions` | Stake twice without merging, get separate nonces | Multiple NFT positions tracked independently |
| 4 | `test_stake_farm_with_existing_farm_token` | Stake with farming tokens + existing farm token (merge) | Position merged, weighted RPS, old token burned |
| 5 | `test_stake_farm_token_attributes` | Verify farm token attributes after entry | `reward_per_share`, `compounded_reward`, `current_farm_amount`, `original_owner` correct |
| 6 | `test_stake_farm_preserves_reward_per_share` | RPS at entry matches current global RPS | Entry RPS snapshot accuracy |
| 7 | `test_stake_farm_increases_supply` | `getFarmTokenSupply` increases by staked amount | Supply tracking |
| 8 | `test_stake_farm_zero_amount_fails` | Stake 0 tokens | Error: payment validation |
| 9 | `test_stake_farm_wrong_token_fails` | Send non-farming token to stakeFarm | Error: wrong farming token |
| 10 | `test_stake_farm_when_paused_fails` | Stake when contract is paused | Error: contract not active |

### Category 2: Unstake Farm (10 tests)
**File**: `test_unstake_farm.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_unstake_farm_basic` | Unstake full position, receive rewards + unbond token | Rewards correct, unbond NFT created with `unlock_epoch` |
| 2 | `test_unstake_farm_partial` | Unstake partial amount | Remaining farm token has correct amount, unbond token for partial |
| 3 | `test_unstake_farm_rewards_returned_immediately` | Rewards sent as farming token on unstake | Reward token == farming token, amount > 0 |
| 4 | `test_unstake_farm_creates_unbond_token` | Verify unbond token attributes | `unlock_epoch = current_epoch + min_unbond_epochs` |
| 5 | `test_unstake_farm_apr_capped_rewards` | Verify rewards don't exceed APR cap | `actual_rewards <= apr_bounded_amount` |
| 6 | `test_unstake_farm_zero_amount_fails` | Unstake with 0 farm tokens | Error: zero amount |
| 7 | `test_unstake_farm_wrong_token_fails` | Send non-farm token to unstakeFarm | Error: wrong token |
| 8 | `test_unstake_farm_when_paused_fails` | Unstake when contract paused | Error: contract not active |
| 9 | `test_unstake_farm_clears_position_on_full_exit` | Full unstake sets `getUserTotalFarmPosition` to 0 | Position cleanup |
| 10 | `test_unstake_farm_supply_decreases` | `getFarmTokenSupply` decreases by unstaked amount | Supply tracking |

### Category 3: Unbond Farm (6 tests)
**File**: `test_unbond_farm.py`
**Priority**: P0 (critical path — unique to staking)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_unbond_farm_basic` | Unbond after unlock period, receive farming tokens | Farming tokens returned, unbond token burned |
| 2 | `test_unbond_farm_before_unlock_fails` | Unbond before `unlock_epoch` reached | Error: "Unbond period not reached" |
| 3 | `test_unbond_farm_exact_unlock_epoch` | Unbond at exactly `unlock_epoch` | Succeeds — boundary condition |
| 4 | `test_unbond_farm_after_unlock_epoch` | Unbond well after unlock period | Succeeds — no additional penalty |
| 5 | `test_unbond_farm_wrong_token_fails` | Send non-unbond token to unbondFarm | Error: wrong token |
| 6 | `test_unbond_full_flow` | Stake → unstake → wait epochs → unbond | Complete lifecycle, token conservation |

### Category 4: Claim Rewards (8 tests)
**File**: `test_claim_rewards.py`
**Priority**: P0 (critical path)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_claim_rewards_basic` | Claim base rewards, receive farming token + new farm token | New farm token updated RPS, rewards as farming token |
| 2 | `test_claim_rewards_proportional` | Two users, rewards proportional to staked amounts | User with 2x stake gets ~2x rewards |
| 3 | `test_claim_rewards_consecutive` | Claim twice, second claim reflects only new rewards | No double-counting |
| 4 | `test_claim_rewards_zero_accrued` | Claim immediately after staking (no time passed) | Zero or near-zero rewards, no error |
| 5 | `test_claim_rewards_updates_farm_token_rps` | New farm token has current RPS as attribute | Attribute correctness |
| 6 | `test_claim_rewards_reduces_accumulated` | `getAccumulatedRewards` increases after claim | Accounting consistency |
| 7 | `test_claim_rewards_wrong_token_fails` | Send non-farm token to claimRewards | Error: wrong token |
| 8 | `test_claim_rewards_apr_bounded` | Claimed amount respects APR cap | `rewards <= apr_cap_amount` |

### Category 5: Compound Rewards (6 tests)
**File**: `test_compound_rewards.py`
**Priority**: P1 (unique to staking — farming_token == reward_token)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_compound_basic` | Compound rewards, new farm token amount = old + rewards | Farm token amount increased, no separate reward output |
| 2 | `test_compound_updates_compounded_reward_attr` | `compounded_reward` attribute tracks total compounded | Attribute accuracy |
| 3 | `test_compound_increases_total_position` | `getUserTotalFarmPosition` increases by compounded amount | Position tracking |
| 4 | `test_compound_increases_farm_supply` | `getFarmTokenSupply` increases by compounded amount | Supply increases since compounded rewards become staked |
| 5 | `test_compound_consecutive` | Compound twice, verify cumulative effect | Second compound builds on first |
| 6 | `test_compound_zero_rewards` | Compound with no rewards accrued | No error, amount unchanged |

### Category 6: Claim Boosted Rewards (6 tests)
**File**: `test_claim_boosted_rewards.py`
**Priority**: P1 (V3Boosted only)
**Note**: Energy factory has no code on chain sim, so boosted rewards are 0. Tests verify endpoint behavior and error handling.

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_claim_boosted_basic` | User with position calls claimBoostedRewards | Transaction succeeds, farm tokens retained |
| 2 | `test_claim_boosted_no_position_fails` | User without position calls claimBoostedRewards | Error: "User total farm position is empty!" |
| 3 | `test_claim_boosted_zero_without_energy` | User with position but no energy (chain sim) | Succeeds with 0 rewards |
| 4 | `test_claim_boosted_unauthorized_for_other_fails` | Claim for another without permission | Error: "Cannot claim rewards for this address" |
| 5 | `test_claim_boosted_updates_claim_progress` | Advance weeks, claim, check progress | ClaimProgress.week updated |
| 6 | `test_claim_boosted_idempotent_same_week` | Two claims in same week | Second claim has 0 additional impact |

### Category 7: View Functions (13 tests)
**File**: `test_view_functions.py`
**Priority**: P1 (observability)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_get_farm_token_supply` | Query total farm token supply | >= 0, changes with stake/unstake |
| 2 | `test_get_reward_reserve` | Query remaining reward reserve | Decreases as rewards claimed |
| 3 | `test_get_reward_per_share` | Query current RPS | Increases with time and rewards |
| 4 | `test_get_farming_token_id` | Query the token being staked | Matches contract config (e.g., RIDE) |
| 5 | `test_get_farm_token_id` | Query the staking receipt token | Matches contract config (e.g., SRIDE) |
| 6 | `test_get_state` | Query contract state (Active/Inactive) | Reflects admin operations |
| 7 | `test_get_reward_capacity` | Query total reward capacity | Staking-specific: `reward_capacity >= accumulated_rewards` |
| 8 | `test_get_accumulated_rewards` | Query accumulated rewards distributed so far | Increases over time |
| 9 | `test_get_max_apr` | Query annual percentage rewards (APR cap) | Matches config (e.g., 2500 = 25%) |
| 10 | `test_get_min_unbond_epochs` | Query unbonding period | Matches config (e.g., 10 epochs) |
| 11 | `test_get_user_total_farm_position` | Query user's aggregated stake amount | Matches sum across all user nonces |
| 12 | `test_calculate_rewards_for_position` | View-only reward calculation | Consistent with actual claim amount |
| 13 | `test_get_current_week` | Query current week number | Correct week calculation |

### Category 8: Reward Economics (8 tests)
**File**: `test_reward_economics.py`
**Priority**: P1 (correctness)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_rps_increases_over_time` | RPS increases as time passes (per-second model) | `RPS_new > RPS_old` after elapsed time |
| 2 | `test_rewards_proportional_to_stake` | Larger stake = proportionally more rewards | Linear reward scaling |
| 3 | `test_reward_capacity_conservation` | `accumulated_rewards <= reward_capacity` always | No over-distribution |
| 4 | `test_apr_cap_limits_rewards` | Per-second rate capped by APR formula | `min(per_second_rewards, apr_bounded_rewards)` |
| 5 | `test_no_rewards_when_production_stopped` | RPS frozen after `endProduceRewards` | No new rewards accrued |
| 6 | `test_rewards_same_token_as_staked` | Claimed rewards are same token as farming token | Token identity check |
| 7 | `test_reward_reserve_tracks_capacity_minus_accumulated` | capacity >= accumulated >= 0, reserve >= 0 | Basic sanity checks — reserve and accumulated are tracked independently; `reserve == capacity - accumulated` is NOT a guaranteed invariant |
| 8 | `test_division_safety_constant` | Large DSC prevents rounding to zero | Small positions still earn rewards |

### Category 9: Admin Operations (10 tests)
**File**: `test_admin_operations.py`
**Priority**: P1 (lifecycle management)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_start_produce_rewards` | Admin starts reward production | Rewards begin accruing |
| 2 | `test_end_produce_rewards` | Admin stops reward production | RPS frozen, no new rewards |
| 3 | `test_set_per_second_reward_amount` | Admin changes reward rate | New rate reflected in subsequent calculations |
| 4 | `test_set_max_apr` | Admin changes APR cap | New cap applied to future reward calculations |
| 5 | `test_set_min_unbond_epochs` | Admin changes unbonding period | New period applied to future unstakes |
| 6 | `test_set_min_unbond_epochs_exceeds_max_fails` | Set unbond epochs > 30 | Error: "Invalid min unbond epochs" |
| 7 | `test_topup_rewards` | Admin deposits more rewards | `getRewardCapacity` increases by deposit amount |
| 8 | `test_withdraw_rewards` | Admin withdraws uncollected rewards | Capacity reduced, excess returned |
| 9 | `test_withdraw_exceeds_remaining_fails` | Withdraw more than remaining | Error: "Withdraw amount is higher than the remaining uncollected rewards!" |
| 10 | `test_pause_resume` | Admin pauses and resumes contract | Operations fail when paused, succeed after resume |

### Category 10: Delegation / On-Behalf Operations (5 tests)
**File**: `test_delegation.py`
**Priority**: P2 (advanced feature)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_stake_on_behalf` | Whitelisted caller stakes for user | Farm token `original_owner` = user, sent to caller |
| 2 | `test_claim_rewards_on_behalf` | Whitelisted caller claims for user | Rewards sent to original owner, new token to caller |
| 3 | `test_on_behalf_unauthorized_fails` | Non-whitelisted caller tries on-behalf operation | Error: not whitelisted |
| 4 | `test_allow_external_claim_boosted` | User enables external claim for boosted rewards | `claimBoostedRewards(user)` succeeds from any caller — **xfail**: endpoint not available on V2 staking contracts |
| 5 | `test_on_behalf_farm_token_ownership` | Farm token `original_owner` preserved through on-behalf ops | Attribute persists |

**Note**: `test_stake_on_behalf` may xfail on chain sim if `isWhitelisted` cross-calls the PermissionsHub SC (no bytecode loaded). `test_allow_external_claim_boosted` is xfail — the endpoint is V3Boosted only.

### Category 11: Multi-User Scenarios (5 tests)
**File**: `test_multi_user.py`
**Priority**: P2 (concurrency)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_two_users_equal_stake` | Two users stake equal amounts, claim rewards | Equal rewards |
| 2 | `test_user_enters_later` | User B enters after User A; User A gets more rewards | Time-weighted distribution |
| 3 | `test_user_exits_early` | User A unstakes, User B continues earning | User B gets full reward rate after A exits |
| 4 | `test_many_users_reward_conservation` | 3+ users, sum of all rewards <= reward capacity | No reward inflation |
| 5 | `test_dilution_on_new_entry` | New user entry dilutes existing user rewards | RPS growth rate decreases with more supply |

### Category 12: Edge Cases & Security (6 tests)
**File**: `test_edge_cases.py`
**Priority**: P2 (robustness)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_stake_unstake_same_block` | Stake and unstake in same block | Minimal/zero rewards, no errors |
| 2 | `test_dust_amounts` | Stake very small amount (1 wei) | No division errors, rewards may be 0 |
| 3 | `test_large_stake_amount` | Stake very large amount (10^24) | No overflow in RPS calculation |
| 4 | `test_rapid_stake_unstake_cycles` | Multiple stake/unstake in sequence | State consistency, no stuck tokens |
| 5 | `test_claim_after_reward_capacity_depleted` | All rewards claimed, capacity exhausted | Graceful zero-reward claim |
| 6 | `test_compound_then_unstake` | Compound rewards then unstake full amount | Total = original + compounded, no loss |

### Category 13: State Transitions & Lifecycle (5 tests)
**File**: `test_state_transitions.py`
**Priority**: P2 (lifecycle)

| # | Test Name | Description | Validates |
|---|-----------|-------------|-----------|
| 1 | `test_full_lifecycle` | Stake → claim → compound → unstake → unbond | Complete flow, token conservation |
| 2 | `test_week_boundary_crossing` | Operations spanning week boundaries | Weekly snapshots correct (V3Boosted) |
| 3 | `test_epoch_advancement_effects` | Advance epochs, verify week/unbond updates | Timekeeping consistency |
| 4 | `test_produce_rewards_toggle` | Start/stop/start reward production | Rewards only during active periods |
| 5 | `test_reward_rate_change_mid_operation` | Change per-second amount while users are staked | Old rate up to change point, new rate after |

---

## Endpoint Coverage Analysis

### User Operation Endpoints (10 endpoints)

| Endpoint | Coverage | Test Categories |
|----------|----------|-----------------|
| `stakeFarm` | Cat 1 (10 tests) | stake, merge, attributes, errors |
| `unstakeFarm` | Cat 2 (10 tests) | unstake, partial, rewards, errors |
| `unbondFarm` | Cat 3 (6 tests) | unbond lifecycle, timing, errors |
| `claimRewards` | Cat 4 (8 tests) | claim, proportional, consecutive |
| `compoundRewards` | Cat 5 (6 tests) | compound, attributes, supply |
| `claimBoostedRewards` | Cat 6 (6 tests) | boosted claims, errors |
| `mergeFarmTokens` | Cat 1.4 | Tested via stake-with-existing |
| `stakeFarmOnBehalf` | Cat 10 (1 test) | delegation |
| `claimRewardsOnBehalf` | Cat 10 (1 test) | delegation |
| `allowExternalClaimBoostedRewards` | Cat 10 (1 test) | delegation |

### Admin Endpoints (10 endpoints)

| Endpoint | Coverage | Test Categories |
|----------|----------|-----------------|
| `startProduceRewards` | Cat 9 | start production |
| `endProduceRewards` | Cat 9 | stop production |
| `setPerSecondRewardAmount` | Cat 9 | rate change |
| `setMaxApr` | Cat 9 | APR cap change |
| `setMinUnbondEpochs` | Cat 9 | unbond period change |
| `topUpRewards` | Cat 9 | reward deposit |
| `withdrawRewards` | Cat 9 | reward withdrawal |
| `pause` / `resume` | Cat 9 | lifecycle control |
| `setBoostedYieldsRewardsPercentage` | Not tested | V3Boosted admin only |
| `setBurnRoleForAddress` | Not tested | Token management |

### Deploy/Config-Only Endpoints (8 endpoints — N/A)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `init` / `upgrade` | N/A | Deploy-time only |
| `registerFarmToken` | N/A | Deploy-time token registration |
| `setLocalRolesFarmToken` | N/A | Deploy-time role setup |
| `setEnergyFactoryAddress` | N/A | Deploy-time config |
| `setBoostedYieldsFactors` | N/A | Deploy-time config |
| `addSCAddressToWhitelist` | Cat 10 | Whitelist management tested in delegation tests |
| `setPermissionsHubAddress` | N/A | Deploy-time config |

### View/Query Endpoints (27 endpoints)

| Endpoint | Coverage | Test Categories |
|----------|----------|-----------------|
| `getFarmTokenSupply` | Cat 7 + throughout | Supply tracking |
| `getRewardReserve` | Cat 7 + Cat 8 | Reserve accounting |
| `getRewardPerShare` | Cat 7 + Cat 8 | RPS progression |
| `getPerBlockRewardAmount` | Cat 7 | Rate query |
| `getFarmingTokenId` | Cat 7 | Token identity |
| `getFarmTokenId` | Cat 7 | Token identity |
| `getState` | Cat 7 + Cat 9 | Contract state |
| `getRewardCapacity` | Cat 7 + Cat 9 | Staking-specific |
| `getAccumulatedRewards` | Cat 7 + Cat 8 | Staking-specific |
| `getAnnualPercentageRewards` | Cat 7 + Cat 9 | APR cap |
| `getMinUnbondEpochs` | Cat 7 + Cat 9 | Unbond config |
| `getDivisionSafetyConstant` | Cat 8 | Precision check |
| `getUserTotalFarmPosition` | Cat 7 + throughout | Position tracking |
| `calculateRewardsForGivenPosition` | Cat 7 | Reward preview |
| `getCurrentWeek` | Cat 7 + Cat 13 | Week timekeeping |
| `getFirstWeekStartEpoch` | Cat 13 | Week config |
| `getLastRewardBlockNonce` | Cat 9 | Block tracking |
| `getLastRewardTimestamp` | Cat 7 | Timestamp tracking |
| `getLastGlobalUpdateWeek` | Cat 13 | Boosted tracking |
| `getUserEnergyForWeek` | Cat 7 | User energy (0 on chain sim) |
| `getLastActiveWeekForUser` | Cat 7 | User activity |
| `getCurrentClaimProgress` | Cat 6 | Claim progress |
| `getFarmSupplyForWeek` | Cat 13 | Weekly supply |
| `getTotalLockedTokensForWeek` | Cat 7 | Weekly locked (0 on chain sim) |
| `getTotalEnergyForWeek` | Cat 13 | Weekly energy |
| `getTotalRewardsForWeek` | Cat 13 | Weekly rewards |
| `getRemainingBoostedRewardsToDistribute` | Cat 6 | Boosted tracking |

### Coverage Summary (Projected)

| Category | Total | Covered | N/A (deploy) |
|----------|-------|---------|--------------|
| User operations | 10 | 10 (100%) | — |
| Admin endpoints | 10 | 8 (80%) | — |
| Deploy/config | 8 | 0 | 8 (100%) |
| View/query | 27 | 27 (100%) | — |
| **Operational total** | **47** | **45 (96%)** | — |

---

## Differences from Farm-with-Locked-Rewards

| Feature | Farm (Locked Rewards) | Farm Staking |
|---------|----------------------|--------------|
| Staking token | LP tokens | Raw tokens (RIDE, UTK, etc.) |
| Reward token | XMEX (locked MEX) | Same as farming token |
| Reward source | Pre-funded reserve (NoMintWrapper) | Pre-funded capacity (`topUpRewards`) |
| APR cap | No | Yes — `max_apr` bounds reward generation |
| Unbonding | No — instant exit | Yes — `unbondFarm` after `min_unbond_epochs` |
| Compound | No (reward ≠ staking token) | Yes — `compoundRewards` reinvests |
| Withdraw rewards | No | Yes — admin `withdrawRewards` claws back |
| Penalty on exit | Yes — penalty before min epochs | No penalty — unbond period instead |
| Reward capacity | `rewardReserve` only | `rewardCapacity` + `accumulatedRewards` |
| Token attributes | +`entering_epoch` | +`compounded_reward`, no `entering_epoch` (V2) |

These differences drive 3 new test categories not present in the farm tests:
- **Category 3: Unbond Farm** — unique unbonding lifecycle
- **Category 5: Compound Rewards** — unique reinvestment mechanic
- **Category 9: Admin Operations** — `topUpRewards`, `withdrawRewards`, `setMaxApr`, `setMinUnbondEpochs`

---

## Rust Test Cross-Reference

The Rust test suite has 22 tests across 3 files. Here's how they map to our integration test categories:

### `farm_staking_test.rs` (10 tests)

| Rust Test | Category Mapping | Notes |
|-----------|-----------------|-------|
| `test_farm_setup` | N/A | Setup validation only |
| `test_enter_farm` | Cat 1 | Basic stake |
| `test_unstake_farm` | Cat 2 | Unstake with APR-capped rewards |
| `test_claim_rewards` | Cat 4 | Claim with RPS validation |
| `test_enter_farm_twice` | Cat 1 | Merge on second entry |
| `test_exit_farm_after_enter_twice` | Cat 2 | Exit after merge |
| `test_unbond` | Cat 3 | Full unbond flow |
| `test_withdraw_rewards` | Cat 9 | Admin withdraw full |
| `test_withdraw_after_produced_rewards` | Cat 9 | Admin withdraw partial (error + success) |

### `farm_staking_energy_test.rs` (9 tests)

| Rust Test | Category Mapping | Notes |
|-----------|-----------------|-------|
| `farm_staking_with_energy_setup_test` | N/A | Setup validation |
| `farm_staking_boosted_rewards_no_energy_test` | Cat 6 | Boosted with 0 energy |
| `farm_staking_other_user_enter_negative_test` | Cat 10 | Unauthorized on-behalf error |
| `farm_staking_boosted_rewards_with_energy_test` | Cat 6, 8 | Boosted with energy |
| `farm_staking_partial_position_handling_test` | Cat 2, 4 | Partial unstake/claim |
| `farm_staking_claim_boosted_rewards_for_user_test` | Cat 10 | External claim |
| `farm_staking_full_position_boosted_rewards_test` | Cat 6, 11 | Multi-user boosted |
| `farm_staking_farm_position_migration_test` | N/A | Migration (not integration-testable) |
| `test_multiple_positions_on_behalf` | Cat 10 | Delegation multi-position |

### `farm_staking_migration_test.rs` (4 tests)

| Rust Test | Category Mapping | Notes |
|-----------|-----------------|-------|
| `test_basic_migration_functionality` | N/A | Block→timestamp migration |
| `test_migration_reward_continuity` | N/A | Migration continuity |
| `test_migration_precision_and_apr_bounds` | Cat 8 | APR precision |
| `test_migration_compound_rewards` | Cat 5 | Compound after migration |

**Coverage gaps in Rust tests** (addressed by our integration plan):
- Unbond timing boundary conditions (Cat 3)
- Compound rewards in detail (Cat 5)
- View function validation (Cat 7)
- Multi-user reward conservation (Cat 11)
- Edge cases: dust amounts, large stakes, rapid cycles (Cat 12)
- State transitions lifecycle (Cat 13)
