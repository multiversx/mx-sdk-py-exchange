import random
import sys
import traceback

import config
from context import Context
from contracts.dex_proxy_contract import (DexProxyAddLiquidityEvent, DexProxyClaimRewardsEvent,
                                                            DexProxyCompoundRewardsEvent, DexProxyEnterFarmEvent,
                                                            DexProxyExitFarmEvent, DexProxyRemoveLiquidityEvent)
from contracts.farm_contract import FarmContract

from contracts.metastaking_contract import MetaStakingContract
from contracts.staking_contract import StakingContract
from contracts.pair_contract import (AddLiquidityEvent, RemoveLiquidityEvent, SwapFixedInputEvent,
                                                       SwapFixedOutputEvent, PairContract, SetCorrectReservesEvent)
from contracts.price_discovery_contract import PriceDiscoveryContract
from events.farm_events import (ClaimRewardsFarmEvent, CompoundRewardsFarmEvent, SetTokenBalanceEvent,
                                                  EnterFarmEvent, ExitFarmEvent, MigratePositionFarmEvent)
from events.metastake_events import (EnterMetastakeEvent, ExitMetastakeEvent,
                                                       ClaimRewardsMetastakeEvent)
from events.price_discovery_events import (DepositPDLiquidityEvent, RedeemPDLPTokensEvent,
                                                             WithdrawPDLiquidityEvent)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.results_logger import FarmEventResultLogData
from utils.utils_chain import (prevent_spam_crash_elrond_proxy_go,
                               get_token_details_for_address, get_all_token_nonces_details_for_account,
                               print_test_step_fail, decode_merged_attributes, dec_to_padded_hex)
from erdpy.accounts import Account, Address


def generate_add_liquidity_event(context: Context, user_account: Account, pair_contract: PairContract):
    print('Attempt addLiquidityEvent')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.proxy.url)

        tokens = [pair_contract.firstToken, pair_contract.secondToken]

        _, amount_token_a, _ = get_token_details_for_address(tokens[0], user_account.address.bech32(), context.proxy)
        _, amount_token_b, _ = get_token_details_for_address(tokens[1], user_account.address.bech32(), context.proxy)

        if amount_token_a <= 0 or amount_token_b <= 0:
            print_test_step_fail(f"Skipped add liquidity because needed tokens NOT found in account.")
            return

        max_amount_a = int(amount_token_a * context.add_liquidity_max_amount)
        # should do a try except block on get equivalent
        equivalent_amount_b = contract_data_fetcher.get_data("getEquivalent",
                                                             ["0x" + tokens[0].encode('utf-8').hex(),
                                                              max_amount_a])

        if equivalent_amount_b <= 0 or equivalent_amount_b > amount_token_b:
            print_test_step_fail(f'Minimum token equivalent amount not satisfied.')
            return

        amount_token_b_min = context.get_slippaged_below_value(equivalent_amount_b)
        amount_token_a_min = context.get_slippaged_below_value(max_amount_a)

        event = AddLiquidityEvent(
            tokens[0], max_amount_a, amount_token_a_min,
            tokens[1], equivalent_amount_b, amount_token_b_min
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.addLiquidity(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return txhash


def generateRandomAddLiquidityEvent(context: Context):
    userAccount = context.get_random_user_account()
    pairContract = context.get_random_pair_contract()
    generate_add_liquidity_event(context, userAccount, pairContract)


def generate_add_initial_liquidity_event(context: Context, user_account: Account, pair_contract: PairContract):
    tokens = [pair_contract.firstToken, pair_contract.secondToken]

    event = AddLiquidityEvent(
        tokens[0], 2000, 1,
        tokens[1], 2000, 1
    )
    pair_contract.addInitialLiquidity(context.network_provider, user_account, event)


def generate_remove_liquidity_event(context: Context, user_account: Account, pair_contract: PairContract):
    print('Attempt removeLiquidityEvent')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.proxy.url)
        # userAccount = context.get_random_user_account()
        # pairContract = context.get_random_pair_contract()

        _, amount_lp_token, _ = get_token_details_for_address(pair_contract.lpToken, user_account.address.bech32(), context.proxy)
        if amount_lp_token <= 0:
            print(f"Skipped swap because no {pair_contract.lpToken} found in account.")
            return

        amount = random.randrange(int(amount_lp_token * context.remove_liquidity_max_amount))
        token_amounts = contract_data_fetcher.get_data("getTokensForGivenPosition",
                                                       [amount])
        decoding_schema = {
            'token_id': 'string',
            'token_nonce': 'u64',
            'amount': 'biguint'
        }

        first_token_deserialized = decode_merged_attributes(token_amounts[0], decoding_schema)
        second_token_deserialized = decode_merged_attributes(token_amounts[1], decoding_schema)

        event = RemoveLiquidityEvent(
            amount,
            pair_contract.firstToken,
            context.get_slippaged_below_value(first_token_deserialized['amount']),
            pair_contract.secondToken,
            context.get_slippaged_below_value(second_token_deserialized['amount'])
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.removeLiquidity(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return txhash


def generate_swap_fixed_input(context: Context, user_account: Account, pair_contract: PairContract):
    print('Attempt swapFixedInputEvent')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.proxy.url)

        tokens = [pair_contract.firstToken, pair_contract.secondToken]
        random.shuffle(tokens)

        _, amount_token_a, _ = get_token_details_for_address(tokens[0], user_account.address.bech32(), context.proxy)
        if amount_token_a <= 0:
            print(f"Skipped swap because no {tokens[0]} found in account.")
            return
        amount_token_a_swapped = random.randrange(int(amount_token_a * context.swap_min_tokens_to_spend),
                                                  int(amount_token_a * context.swap_max_tokens_to_spend))

        equivalent_amount_token_b = contract_data_fetcher.get_data("getAmountOut",
                                                                   ["0x"+tokens[0].encode('utf-8').hex(),
                                                                    amount_token_a_swapped])

        if equivalent_amount_token_b <= 0:
            print_test_step_fail(f'Minimum token equivalent amount not satisfied. Token amount: {equivalent_amount_token_b}')
            return

        amount_token_b_min = context.get_slippaged_below_value(equivalent_amount_token_b)

        event = SwapFixedInputEvent(
            tokens[0], amount_token_a_swapped, tokens[1], amount_token_b_min
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.swapFixedInput(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return txhash


def generate_random_swap_fixed_input(context: Context):
    userAccount = context.get_random_user_account()
    pairContract = context.get_random_pair_contract()
    generate_swap_fixed_input(context, userAccount, pairContract)


def generate_swap_fixed_output(context: Context, user_account: Account, pair_contract: PairContract):
    print('Attempt swapFixedOutputEvent')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.proxy.url)

        tokens = [pair_contract.firstToken, pair_contract.secondToken]
        random.shuffle(tokens)

        _, amount_token_a, _ = get_token_details_for_address(tokens[0], user_account.address.bech32(), context.proxy)
        if amount_token_a <= 0:
            print(f"Skipped swap because no {tokens[0]} found in account.")
            return
        amount_token_a_max = random.randrange(int(amount_token_a * context.swap_max_tokens_to_spend))

        # TODO: switch to getAmountIn
        equivalent_amount_token_b = contract_data_fetcher.get_data("getAmountOut",
                                                                   ["0x"+tokens[0].encode('utf-8').hex(),
                                                                    amount_token_a_max])
        # TODO: apply slippage on token A
        event = SwapFixedOutputEvent(
            tokens[0], amount_token_a_max, tokens[1], context.get_slippaged_below_value(equivalent_amount_token_b)
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.swapFixedOutput(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return txhash


def generate_random_swap_fixed_output(context: Context):
    userAccount = context.get_random_user_account()
    pairContract = context.get_random_pair_contract()
    generate_swap_fixed_output(context, userAccount, pairContract)


def generateEnterFarmEvent(context: Context, userAccount: Account, farmContract: FarmContract, lockRewards: int = 0):
    """lockRewards: -1 - random; 0 - unlocked rewards; 1 - locked rewards;"""
    print("Attempt generateEnterFarmEvent")
    tx_hash = ""
    try:
        farmToken = farmContract.farmToken
        farming_token = farmContract.farmingToken

        farmingTkNonce, farmingTkAmount, _ = get_token_details_for_address(farming_token, userAccount.address, context.proxy)
        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farmToken, userAccount.address, context.proxy)

        if farmingTkNonce == 0 and farmingTkAmount == 0:
            print_test_step_fail(f"SKIPPED: No tokens found!")
            return

        initial = True if farmTkNonce == 0 else False

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(farming_token, farmingTkAmount, farmingTkNonce)
        context.observable.set_event(None, userAccount, set_token_balance_event, '')

        # amount to add into farm
        farmingTkAmount = random.randrange(int(farmingTkAmount * context.enter_farm_max_amount))
        event = EnterFarmEvent(
            farming_token, farmingTkNonce, farmingTkAmount, farmToken, farmTkNonce, farmTkAmount
        )

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.proxy)

        tx_hash = farmContract.enterFarm(context.network_provider, userAccount, event, lockRewards, initial)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        print("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateEnterStakingEvent(context: Context, user: Account, staking_contract: StakingContract):
    print('Attempt generateEnterStakingEvent')
    tx_hash = ''
    try:
        staking_token = staking_contract.farming_token
        farm_token = staking_contract.farm_token

        staking_token_nonce, staking_token_amount, _ = get_token_details_for_address(staking_token,
                                                                                     user.address,
                                                                                     context.proxy)
        farm_token_nonce, farm_token_amount, _ = get_token_details_for_address(farm_token,
                                                                               user.address,
                                                                               context.proxy)
        if not staking_token_amount:
            print_test_step_fail('SKIPPED enterStakingEvent: No tokens found!')
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(staking_token, staking_token_amount, staking_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        staking_token_amount = random.randrange(int(staking_token_amount * context.enter_metastake_max_amount))

        event = EnterFarmEvent(
            staking_token, staking_token_nonce, staking_token_amount,
            farm_token, farm_token_nonce, farm_token_amount
        )

        tx_hash = staking_contract.stake_farm(context.network_provider, user, event, True)
        context.observable.set_event(staking_contract, user, event, tx_hash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return tx_hash


def generateEnterMetastakeEvent(context: Context, user: Account, metastake_contract: MetaStakingContract):
    print('Attempt generateEnterMetastakeEvent')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        staking_token = metastake_contract.farm_token

        staking_token_nonce, staking_token_amount, _ = get_token_details_for_address(staking_token,
                                                                                     user.address,
                                                                                     context.proxy)
        metastake_token_nonce, metastake_token_amount, _ = get_token_details_for_address(metastake_token,
                                                                                         user.address,
                                                                                         context.proxy)

        if staking_token_nonce == 0 and staking_token_amount == 0:
            print_test_step_fail(f"SKIPPED: No tokens found!")
            return

        initial = True if metastake_token_nonce == 0 else False

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(staking_token, staking_token_amount, staking_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        # update data for staking, farm and pair trackers inside metastaking tracker
        update_data_event = SetCorrectReservesEvent()
        context.observable.set_event(metastake_contract, user, update_data_event, '')

        # amount to enter metastake
        staking_token_amount = random.randrange(int(staking_token_amount * context.enter_metastake_max_amount))

        event = EnterMetastakeEvent(staking_token, staking_token_nonce, staking_token_amount,
                                    metastake_token, metastake_token_nonce, metastake_token_amount)

        tx_hash = metastake_contract.enter_metastake(context.network_provider, user, event, initial)
        context.observable.set_event(metastake_contract, user, event, tx_hash)

    except Exception as ex:
        print('Exception encountered: ', ex)

    return tx_hash


def generateEnterFarmv12Event(context: Context, userAccount: Account, farmContract: FarmContract):
    lockRewards = random.randint(0, 1)
    generateEnterFarmEvent(context, userAccount, farmContract, lockRewards)


def generateRandomEnterFarmEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateEnterFarmEvent(context, userAccount, farmContract)


def generateExitFarmEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    print("Attempt generateExitFarmEvent")
    tx_hash = ""
    try:
        farmTkNonce, farmTkAmount, farmTkAttr = get_token_details_for_address(farmContract.farmToken,
                                                                              userAccount.address, context.proxy)
        if farmTkNonce == 0:
            print(f"Skipped exit farm event. No token retrieved.")
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(farmContract.farmToken, farmTkAmount, farmTkNonce)
        context.observable.set_event(None, userAccount, set_token_balance_event, '')

        # amount to exit from farm
        farmTkAmount = random.randrange(int(farmTkAmount * context.exit_farm_max_amount))
        event = ExitFarmEvent(farmContract.farmToken, farmTkAmount, farmTkNonce, farmTkAttr)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.proxy)

        tx_hash = farmContract.exitFarm(context.network_provider, userAccount, event)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        print("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateUnstakeEvent(context: Context, user: Account, staking_contract: StakingContract):
    print('Attempt unstakingEvent')
    tx_hash = ''
    try:
        stake_token = staking_contract.farm_token
        stake_token_nonce, stake_token_amount, stake_token_attr = get_token_details_for_address(stake_token,
                                                                                                user.address,
                                                                                                context.proxy)
        if not stake_token_nonce:
            print_test_step_fail('SKIPPED unstakingEvent: No tokens to unstake!')
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(stake_token, stake_token_amount, stake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        unstake_token_amount = random.randrange(int(stake_token_amount * context.exit_metastake_max_amount))

        event = ExitFarmEvent(
            stake_token, unstake_token_amount, stake_token_nonce, stake_token_attr
        )

        tx_hash = staking_contract.unstake_farm(context.network_provider, user, event)
        context.observable.set_event(staking_contract, user, event, tx_hash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return tx_hash


def get_lp_from_metastake_token_attributes(token_attributes):
    """LP amount is the same as FarmTokenAmount"""

    attributes_schema_proxy_staked_tokens = {
        'lp_farm_token_nonce': 'u64',
        'lp_farm_token_amount': 'biguint',
        'staking_farm_token_nonce': 'u64',
        'staking_farm_token_amount': 'biguint',
    }

    lp_position = decode_merged_attributes(token_attributes, attributes_schema_proxy_staked_tokens)
    return lp_position


def generateExitMetastakeEvent(context: Context, user: Account, metastake_contract: MetaStakingContract):
    print('Attempt generateExitMetastakeEvent')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        metastake_token_nonce, metastake_token_amount, metastake_token_attributes = get_token_details_for_address(
            metastake_token, user.address, context.proxy
        )
        if metastake_token_nonce == 0:
            print_test_step_fail(f"SKIPPED: No tokens found!")
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(metastake_token, metastake_token_amount, metastake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        # update data for staking, farm and pair trackers inside metastaking tracker
        update_data_event = SetCorrectReservesEvent()
        context.observable.set_event(metastake_contract, user, update_data_event, '')

        decoded_metastake_tk_attributes = get_lp_from_metastake_token_attributes(metastake_token_attributes)

        farm_tk_details = context.api.get_nft_data(
            metastake_contract.farm_token + '-' +
            dec_to_padded_hex(decoded_metastake_tk_attributes['lp_farm_token_nonce'])
        )

        full_metastake_amount = metastake_token_amount
        # amount to exit metastake
        metastake_token_amount = random.randrange(int(metastake_token_amount * context.exit_metastake_max_amount))

        event = ExitMetastakeEvent(metastake_contract.metastake_token, metastake_token_amount,
                                   metastake_token_nonce, metastake_token_attributes, full_metastake_amount,
                                   farm_tk_details)

        tx_hash = metastake_contract.exit_metastake(context.network_provider, user, event)
        context.observable.set_event(metastake_contract, user, event, tx_hash)

    except Exception as ex:
        print('Exception encountered: ', ex)

    return tx_hash


def generateRandomExitFarmEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateExitFarmEvent(context, userAccount, farmContract)


def generateClaimRewardsEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    print("Attempt generateClaimRewardsEvent")
    tx_hash = ""
    try:
        farmTkNonce, farmTkAmount, farmTkAttributes = get_token_details_for_address(farmContract.farmToken,
                                                                                    userAccount.address,
                                                                                    context.proxy)
        if farmTkNonce == 0:
            print(f"Skipped claim rewards farm event. No token retrieved.")
            return

        farmedTkNonce, farmedTkAmount, _ = get_token_details_for_address(farmContract.farmedToken,
                                                                         userAccount.address, context.proxy)

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(farmContract.farmedToken, farmedTkAmount, farmedTkNonce)
        context.observable.set_event(None, userAccount, set_token_balance_event, '')

        event = ClaimRewardsFarmEvent(farmTkAmount, farmTkNonce, farmTkAttributes)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.proxy)

        tx_hash = farmContract.claimRewards(context.network_provider, userAccount, event)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        print("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateClaimStakingRewardsEvent(context: Context, user: Account, staking_contract: StakingContract):
    print('Attemp claimStakingRewardsEvent')
    tx_hash = ''
    try:
        stake_token = staking_contract.farm_token
        stake_token_nonce, stake_token_amount, attributes = get_token_details_for_address(stake_token,
                                                                                          user.address,
                                                                                          context.proxy)
        if not stake_token_nonce:
            print('SKIPPED claimStakingRewardsEvent: No token retrieved!')
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(stake_token, stake_token_amount, stake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        event = ClaimRewardsFarmEvent(stake_token_amount, stake_token_nonce, attributes)

        tx_hash = staking_contract.claimRewards(context.network_provider, user, event)
        context.observable.set_event(staking_contract, user, event, tx_hash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return tx_hash


def generateClaimMetastakeRewardsEvent(context: Context, user: Account, metastake_contract: MetaStakingContract):
    print('Attempt generateClaimMetastakeRewardsEvent')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        metastake_token_nonce, metastake_token_amount, metastake_token_attributes = get_token_details_for_address(
                                                                                    metastake_token,
                                                                                    user.address,
                                                                                    context.proxy
                                                                                    )
        if metastake_token_nonce == 0:
            print_test_step_fail(f"SKIPPED: No tokens found!")
            return

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(metastake_token, metastake_token_amount, metastake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        farm_position = get_lp_from_metastake_token_attributes(metastake_token_attributes)
        farm_token_details = context.api.get_nft_data(
            metastake_contract.farm_token + '-' + dec_to_padded_hex(farm_position['lp_farm_token_nonce'])
        )

        # update data for staking, farm and pair trackers inside metastaking tracker
        update_data_event = SetCorrectReservesEvent()
        context.observable.set_event(metastake_contract, user, update_data_event, '')

        event = ClaimRewardsMetastakeEvent(metastake_token_amount, metastake_token_nonce, farm_token_details)

        tx_hash = metastake_contract.claim_rewards_metastaking(context.network_provider, user, event)
        context.observable.set_event(metastake_contract, user, event, tx_hash)

    except Exception as ex:
        print('Exception encountered: ', ex)

    return tx_hash


def generateRandomClaimRewardsEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateClaimRewardsEvent(context, userAccount, farmContract)


def generateCompoundRewardsEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    print("Attempt generateCompoundRewardsEvent")
    tx_hash = ""
    try:
        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farmContract.farmToken,
                                                                     userAccount.address, context.proxy)
        if farmTkNonce == 0:
            print(f"Skipped compound rewards farm event. No token retrieved.")
            return

        event = CompoundRewardsFarmEvent(farmTkAmount, farmTkNonce)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.proxy)

        tx_hash = farmContract.compoundRewards(context.network_provider, userAccount, event)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        print("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateRandomCompoundRewardsEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateCompoundRewardsEvent(context, userAccount, farmContract)


def generate_migrate_farm_event(context: Context, userAccount: Account, farmContract: FarmContract):
    print("Attempt generateMigrateFarmEvent")
    try:
        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farmContract.farmToken,
                                                                     userAccount.address,
                                                                     context.proxy)
        if farmTkNonce == 0:
            return

        event = MigratePositionFarmEvent(farmTkAmount, farmTkNonce)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.proxy)

        tx_hash = farmContract.migratePosition(context.network_provider, userAccount, event)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        print("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())


def generateAddLiquidityProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    pairContract = context.pairs[0]

    tokenA = context.wrapped_egld_tkid
    tokenB = context.lkmex_tkid

    amount = random.randrange(context.addLiquidityMaxValue)
    amountMin = int(amount / 100) + 1

    nonce = 0
    try:
        tokens = context.proxy.get_account_tokens(userAccount.address)
        prevent_spam_crash_elrond_proxy_go()

        for token in tokens['esdts'].keys():
            if tokenB in token:
                nonce = int(tokens['esdts'][token]['nonce'])
                break

        if nonce == 0:
            return

    except Exception as ex:
        ex = ex

    event = DexProxyAddLiquidityEvent(
        pairContract, tokenA, 0, amount, amountMin,
        tokenB, nonce, amount, amountMin
    )
    context.dexProxyContract.addLiquidityProxy(context, userAccount, event)


def generateRemoveLiquidityProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    pairContract = context.pairs[0]

    amount = random.randrange(context.removeLiquidityMaxValue)
    amountA = int(amount / 100) + 1
    amountB = amountA

    nonce = 0
    try:
        tokens = context.proxy.get_account_tokens(userAccount.address)
        prevent_spam_crash_elrond_proxy_go()

        for token in tokens['esdts'].keys():
            if context.wrappedLpTokenId in token:
                nonce = int(tokens['esdts'][token]['nonce'])
                break

        if nonce == 0:
            return

    except Exception as ex:
        ex = ex

    event = DexProxyRemoveLiquidityEvent(
        pairContract, amount, nonce, amountA, amountB
    )
    context.dexProxyContract.removeLiquidityProxy(context, userAccount, event)


def generateEnterFarmProxyEvent(context: Context, user_account: Account, farm_contract: FarmContract, lock_rewards: int = 0):

    try:
        farm_token = farm_contract.proxyContract.farm_token
        underlying_farm_token = farm_contract.farmToken
        farming_token = farm_contract.proxyContract.farming_token

        farming_tk_nonce, farming_tk_amount, _ = get_token_details_for_address(farming_token, user_account.address, context.proxy)
        farm_tk_nonce, farm_tk_amount, _ = get_token_details_for_address(farm_token, user_account.address, context.proxy, underlying_farm_token)

        if farming_tk_nonce == 0:
            return

        initial_enter_farm = True if farm_tk_nonce == 0 else False

        # amount to add into farm
        farming_tk_amount = random.randrange(min(farming_tk_amount, context.enterFarmMaxValue))

        event = DexProxyEnterFarmEvent(
            farm_contract, farming_token, farming_tk_nonce, farming_tk_amount, farm_token, farm_tk_nonce, farm_tk_amount
        )

        context.dexProxyContract.enterFarmProxy(context, user_account, event, lock_rewards, initial_enter_farm)

    except Exception as ex:
        print("Exception encountered:", ex)


def generateRandomEnterFarmProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateEnterFarmProxyEvent(context, userAccount, farmContract, -1)


def generateExitFarmProxyEvent(context: Context, userAccount: Account, farmContract: FarmContract):

    try:
        farm_token = farmContract.proxyContract.farm_token
        underlying_token = farmContract.farmToken

        farm_tk_nonce, farm_tk_amount, _ = get_token_details_for_address(farm_token, userAccount.address,
                                                                         context.proxy, underlying_token)
        if farm_tk_nonce == 0:
            return

        # amount to exit from farm
        farm_tk_amount = random.randrange(farm_tk_amount)

        event = DexProxyExitFarmEvent(
            farmContract, farm_token, farm_tk_nonce, farm_tk_amount
        )
        context.dexProxyContract.exitFarmProxy(context, userAccount, event)

    except Exception as ex:
        print(ex)


def generateRandomExitFarmProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateExitFarmProxyEvent(context, userAccount, farmContract)


def generateClaimRewardsProxyEvent(context: Context, userAccount: Account, farmContract: FarmContract):

    try:
        farm_token = farmContract.proxyContract.farm_token
        underlying_token = farmContract.farmToken

        farm_tk_nonce, farm_tk_amount, _ = get_token_details_for_address(farm_token, userAccount.address,
                                                                         context.proxy, underlying_token)
        if farm_tk_nonce == 0:
            return

        event = DexProxyClaimRewardsEvent(
            farmContract, farm_token, farm_tk_nonce, farm_tk_amount
        )
        context.dexProxyContract.claimRewardsProxy(context, userAccount, event)

    except Exception as ex:
        print(ex)


def generateRandomClaimRewardsProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.get_random_farm_contract()
    generateClaimRewardsProxyEvent(context, userAccount, farmContract)


def generateCompoundRewardsProxyEvent(context: Context, userAccount: Account, farmContract: FarmContract):

    try:
        farm_token = farmContract.proxyContract.farm_token
        underlying_token = farmContract.farmToken

        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farm_token, userAccount.address,
                                                                     context.proxy, underlying_token)
        if farmTkNonce == 0:
            return

        event = DexProxyCompoundRewardsEvent(
            farmContract, farm_token, farmTkNonce, farmTkAmount
        )
        context.dexProxyContract.claimRewardsProxy(context, userAccount, event)

    except Exception as ex:
        print(ex)


def generateRandomCompoundRewardsProxyEvent(context: Context):
    userAccount = context.get_random_user_account()
    farmContract = context.farms[len(context.farms) - 1]
    generateCompoundRewardsProxyEvent(context, userAccount, farmContract)


def generate_deposit_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    tokens = [pd_contract.launched_token_id, pd_contract.accepted_token]
    # TODO: find a smarter/more configurable method of choosing which token to use
    # Option1: Based on account balance (after smart funds distribution e.g. 10% tokenA, 80% tokenB, 10%, mixed tokens)
    random.shuffle(tokens)
    deposited_token = tokens[0]

    _, amount, _ = get_token_details_for_address(deposited_token, user_account.address, context.proxy)
    amount = random.randrange(amount)

    event = DepositPDLiquidityEvent(deposited_token, amount)
    tx_hash = pd_contract.deposit_liquidity(context.network_provider, user_account, event)

    # track and check event results
    if hasattr(context, 'price_discovery_trackers'):
        index = context.get_contract_index(config.PRICE_DISCOVERIES, pd_contract)
        context.price_discovery_trackers[index].deposit_event_tracking(
            event, user_account.address, tx_hash
        )


def generate_random_deposit_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_deposit_pd_liquidity_event(context, user_account, pd_contract)


def generate_withdraw_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    # TODO: find a smarter/more configurable method of choosing which token to use
    tokens = get_all_token_nonces_details_for_account(pd_contract.redeem_token, user_account.address, context.proxy)
    if len(tokens) == 0:
        print_test_step_fail(f"Generate withdraw price discovery liquidity failed! No redeem tokens available.")
        return

    random.shuffle(tokens)
    deposit_token = tokens[0]
    nonce = int(deposit_token['nonce'])
    amount = random.randrange(int(deposit_token['balance']))

    event = WithdrawPDLiquidityEvent(pd_contract.redeem_token, nonce, amount)
    tx_hash = pd_contract.withdraw_liquidity(context.network_provider, user_account, event)

    # track and check event results
    if hasattr(context, 'price_discovery_trackers'):
        index = context.get_contract_index(config.PRICE_DISCOVERIES, pd_contract)
        context.price_discovery_trackers[index].withdraw_event_tracking(
            event, user_account.address, tx_hash
        )


def generate_random_withdraw_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_withdraw_pd_liquidity_event(context, user_account, pd_contract)


def generate_redeem_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    # TODO: find a smarter/more configurable method of choosing which token to use and how much
    tokens = get_all_token_nonces_details_for_account(pd_contract.redeem_token, user_account.address, context.proxy)
    if len(tokens) == 0:
        print_test_step_fail(f"Generate redeem price discovery liquidity failed! No redeem tokens available.")
        return

    random.shuffle(tokens)
    deposit_token = tokens[0]
    nonce = int(deposit_token['nonce'])
    amount = random.randrange(int(deposit_token['balance']))

    event = RedeemPDLPTokensEvent(pd_contract.redeem_token, nonce, amount)
    tx_hash = pd_contract.redeem_liquidity_position(context.network_provider, user_account, event)

    # track and check event results
    if hasattr(context, 'price_discovery_trackers'):
        index = context.get_contract_index(config.PRICE_DISCOVERIES, pd_contract)
        context.price_discovery_trackers[index].redeem_event_tracking(
            event, user_account.address, tx_hash
        )


def generate_random_redeem_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_redeem_pd_liquidity_event(context, user_account, pd_contract)
