import random
import sys
import traceback

from multiversx_sdk.abi import BigUIntValue, TokenIdentifierValue

from context import Context
from contracts.farm_contract import FarmContract
from contracts.metastaking_contract import MetaStakingContract
from contracts.pair_contract import (
    AddLiquidityEvent,
    PairContract,
    SetCorrectReservesEvent,
    SwapFixedInputEvent,
)
from contracts.price_discovery_contract import PriceDiscoveryContract
from events.farm_events import (
    ClaimRewardsFarmEvent,
    EnterFarmEvent,
    ExitFarmEvent,
    MigratePositionFarmEvent,
    SetTokenBalanceEvent,
)
from events.metastake_events import (
    ClaimRewardsMetastakeEvent,
    EnterMetastakeEvent,
    ExitMetastakeEvent,
)
from events.price_discovery_events import (
    DepositPDLiquidityEvent,
    RedeemPDLPTokensEvent,
    WithdrawPDLiquidityEvent,
)
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.logger import get_logger
from utils.results_logger import FarmEventResultLogData
from utils.utils_chain import (
    Account,
    decode_merged_attributes,
    get_all_token_nonces_details_for_account,
    get_token_details_for_address,
)
from utils.utils_chain import WrapperAddress as Address
from utils.utils_generic import log_step_fail

logger = get_logger(__name__)


def generate_add_liquidity_event(context: Context, user_account: Account, pair_contract: PairContract):
    logger.info(f'Attempt addLiquidityEvent for {user_account.address.bech32()} on {pair_contract.address}')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.network_provider.proxy.url)

        tokens = [pair_contract.firstToken, pair_contract.secondToken]

        _, amount_token_a, _ = get_token_details_for_address(tokens[0], user_account.address.bech32(), context.network_provider.proxy)
        _, amount_token_b, _ = get_token_details_for_address(tokens[1], user_account.address.bech32(), context.network_provider.proxy)

        if amount_token_a <= 0 or amount_token_b <= 0:
            log_step_fail(f"Skipped add liquidity because needed tokens "
                          f"NOT found in account {user_account.address.bech32()}.")
            return None

        max_amount_a = int(amount_token_a * context.add_liquidity_max_amount)
        # should do a try except block on get equivalent
        equivalent_amount_b = contract_data_fetcher.get_data("getEquivalent",
                                                             [TokenIdentifierValue(tokens[0]),
                                                              BigUIntValue(max_amount_a)])

        if equivalent_amount_b <= 0 or equivalent_amount_b > amount_token_b:
            log_step_fail('Minimum token equivalent amount not satisfied.')
            return None

        amount_token_b_min = context.get_slippaged_below_value(equivalent_amount_b)
        amount_token_a_min = context.get_slippaged_below_value(max_amount_a)

        event = AddLiquidityEvent(
            tokens[0], max_amount_a, amount_token_a_min,
            tokens[1], equivalent_amount_b, amount_token_b_min
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.add_liquidity(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        print(f'Exception encountered: {ex}')

    return txhash


def generate_add_initial_liquidity_event(context: Context, user_account: Account, pair_contract: PairContract):
    tokens = [pair_contract.firstToken, pair_contract.secondToken]

    event = AddLiquidityEvent(
        tokens[0], 2000, 1,
        tokens[1], 2000, 1
    )
    pair_contract.add_initial_liquidity(context.network_provider, user_account, event)


def generate_swap_fixed_input(context: Context, user_account: Account, pair_contract: PairContract):
    logger.info(f'Attempt swapFixedInputEvent for {user_account.address.bech32()} on {pair_contract.address}')
    txhash = ''
    try:
        contract_data_fetcher = PairContractDataFetcher(Address(pair_contract.address), context.network_provider.proxy.url)

        tokens = [pair_contract.firstToken, pair_contract.secondToken]
        random.shuffle(tokens)

        _, amount_token_a, _ = get_token_details_for_address(tokens[0], user_account.address.bech32(), context.network_provider.proxy)
        if amount_token_a <= 0:
            logger.warning(f"Skipped swap because no {tokens[0]} "
                           f"found in account {user_account.address.bech32()}.")
            return None
        amount_token_a_swapped = random.randrange(int(amount_token_a * context.swap_min_tokens_to_spend),
                                                  int(amount_token_a * context.swap_max_tokens_to_spend))

        equivalent_amount_token_b = contract_data_fetcher.get_data("getAmountOut",
                                                                   [TokenIdentifierValue(tokens[0]),
                                                                    BigUIntValue(amount_token_a_swapped)])

        if equivalent_amount_token_b <= 0:
            log_step_fail(f'Minimum token equivalent amount not satisfied. Token amount: {equivalent_amount_token_b}')
            return None

        amount_token_b_min = context.get_slippaged_below_value(equivalent_amount_token_b)

        event = SwapFixedInputEvent(
            tokens[0], amount_token_a_swapped, tokens[1], amount_token_b_min
        )

        set_reserves_event = SetCorrectReservesEvent()
        context.observable.set_event(pair_contract, user_account, set_reserves_event, '')

        txhash = pair_contract.swap_fixed_input(context.network_provider, user_account, event)
        context.observable.set_event(pair_contract, user_account, event, txhash)

    except Exception as ex:
        logger.error(f'Exception encountered: {ex}')

    return txhash


def generateEnterFarmEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    logger.info(f"Attempt generateEnterFarmEvent for {userAccount.address.bech32()} on {farmContract.address}")
    tx_hash = ""
    try:
        farmToken = farmContract.farmToken
        farming_token = farmContract.farmingToken

        farmingTkNonce, farmingTkAmount, _ = get_token_details_for_address(farming_token, userAccount.address, context.network_provider.proxy)
        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farmToken, userAccount.address, context.network_provider.proxy)

        if farmingTkNonce == 0 and farmingTkAmount == 0:
            logger.warning(f"SKIPPED: No {farming_token} found for {userAccount.address.bech32()}!")
            return None

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
        event_log.set_pre_event_data(context.network_provider.proxy)

        tx_hash = farmContract.enterFarm(context.network_provider, userAccount, event)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.network_provider.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        logger.error("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateEnterMetastakeEvent(context: Context, user: Account, metastake_contract: MetaStakingContract):
    logger.info(f'Attempt generateEnterMetastakeEvent for {user.address.bech32()} on {metastake_contract.address}')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        staking_token = metastake_contract.farm_token

        staking_token_nonce, staking_token_amount, _ = get_token_details_for_address(staking_token,
                                                                                     user.address,
                                                                                     context.network_provider.proxy)
        metastake_token_nonce, metastake_token_amount, _ = get_token_details_for_address(metastake_token,
                                                                                         user.address,
                                                                                         context.network_provider.proxy)

        if staking_token_nonce == 0 and staking_token_amount == 0:
            logger.warning(f"SKIPPED: No {staking_token} found on {user.address.bech32()}!")
            return None

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
        logger.error('Exception encountered: ', ex)

    return tx_hash


def generateEnterFarmv12Event(context: Context, userAccount: Account, farmContract: FarmContract):
    lockRewards = random.randint(0, 1)
    generateEnterFarmEvent(context, userAccount, farmContract, lockRewards)


def generateExitFarmEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    logger.info(f"Attempt generateExitFarmEvent for {userAccount.address.bech32()} on {farmContract.address}")
    tx_hash = ""
    try:
        farmTkNonce, farmTkAmount, farmTkAttr = get_token_details_for_address(farmContract.farmToken,
                                                                              userAccount.address, context.network_provider.proxy)
        if farmTkNonce == 0:
            logger.warning(f"Skipped exit farm event. No {farmContract.farmToken} "
                           f"found on {userAccount.address.bech32()}!")
            return None

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(farmContract.farmToken, farmTkAmount, farmTkNonce)
        context.observable.set_event(None, userAccount, set_token_balance_event, '')

        # amount to exit from farm
        farmTkAmount = random.randrange(int(farmTkAmount * context.exit_farm_max_amount))
        event = ExitFarmEvent(farmContract.farmToken, farmTkAmount, farmTkNonce, farmTkAttr)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.network_provider.proxy)

        tx_hash = farmContract.exitFarm(context.network_provider, userAccount, event)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.network_provider.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        logger.error("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

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
    logger.info(f'Attempt generateExitMetastakeEvent for {user.address.bech32()} on {metastake_contract.address}')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        metastake_token_nonce, metastake_token_amount, metastake_token_attributes = get_token_details_for_address(
            metastake_token, user.address, context.network_provider.proxy
        )
        if metastake_token_nonce == 0:
            logger.warning(f"SKIPPED: No {metastake_token} found on {user.address.bech32()}!")
            return None

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(metastake_token, metastake_token_amount, metastake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        # update data for staking, farm and pair trackers inside metastaking tracker
        update_data_event = SetCorrectReservesEvent()
        context.observable.set_event(metastake_contract, user, update_data_event, '')

        decoded_metastake_tk_attributes = get_lp_from_metastake_token_attributes(metastake_token_attributes)

        farm_tk_details = context.network_provider.proxy.get_nonfungible_token_of_account(
            Address(metastake_contract.address), metastake_contract.farm_token, decoded_metastake_tk_attributes['lp_farm_token_nonce']
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
        logger.error('Exception encountered: ', ex)

    return tx_hash


def generateClaimRewardsEvent(context: Context, userAccount: Account, farmContract: FarmContract):
    logger.info(f"Attempt generateClaimRewardsEvent for {userAccount.address.bech32()} on {farmContract.address}")
    tx_hash = ""
    try:
        farmTkNonce, farmTkAmount, farmTkAttributes = get_token_details_for_address(farmContract.farmToken,
                                                                                    userAccount.address,
                                                                                    context.network_provider.proxy)
        if farmTkNonce == 0:
            logger.warning(f"Skipped claim rewards farm event. No {farmContract.farmToken} "
                           f"found on {userAccount.address.bech32()}.")
            return None

        farmedTkNonce, farmedTkAmount, _ = get_token_details_for_address(farmContract.farmedToken,
                                                                         userAccount.address, context.network_provider.proxy)

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(farmContract.farmedToken, farmedTkAmount, farmedTkNonce)
        context.observable.set_event(None, userAccount, set_token_balance_event, '')

        event = ClaimRewardsFarmEvent(farmTkAmount, farmTkNonce, farmTkAttributes)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.network_provider.proxy)

        tx_hash = farmContract.claimRewards(context.network_provider, userAccount, event)
        context.observable.set_event(farmContract, userAccount, event, tx_hash)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.network_provider.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        logger.error("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())

    return tx_hash


def generateClaimMetastakeRewardsEvent(context: Context, user: Account, metastake_contract: MetaStakingContract):
    logger.info(f'Attempt generateClaimMetastakeRewardsEvent for {user.address.bech32()} on {metastake_contract.address}')
    tx_hash = ""
    try:
        metastake_token = metastake_contract.metastake_token
        metastake_token_nonce, metastake_token_amount, metastake_token_attributes = get_token_details_for_address(
                                                                                    metastake_token,
                                                                                    user.address,
                                                                                    context.network_provider.proxy
                                                                                    )
        if metastake_token_nonce == 0:
            logger.warning(f"SKIPPED: No {metastake_token} found on {user.address.bech32()}!")
            return None

        # set correct token balance in case it has been changed since the init of observers
        set_token_balance_event = SetTokenBalanceEvent(metastake_token, metastake_token_amount, metastake_token_nonce)
        context.observable.set_event(None, user, set_token_balance_event, '')

        farm_position = get_lp_from_metastake_token_attributes(metastake_token_attributes)

        farm_token_details = context.network_provider.proxy.get_nonfungible_token_of_account(
            Address(metastake_contract.address), metastake_contract.farm_token, farm_position['lp_farm_token_nonce']
        )

        # update data for staking, farm and pair trackers inside metastaking tracker
        update_data_event = SetCorrectReservesEvent()
        context.observable.set_event(metastake_contract, user, update_data_event, '')

        event = ClaimRewardsMetastakeEvent(metastake_token_amount, metastake_token_nonce, farm_token_details)

        tx_hash = metastake_contract.claim_rewards_metastaking(context.network_provider, user, event)
        context.observable.set_event(metastake_contract, user, event, tx_hash)

    except Exception as ex:
        logger.error('Exception encountered: ', ex)

    return tx_hash


def generate_migrate_farm_event(context: Context, userAccount: Account, farmContract: FarmContract):
    logger.info("Attempt generateMigrateFarmEvent")
    try:
        farmTkNonce, farmTkAmount, _ = get_token_details_for_address(farmContract.farmToken,
                                                                     userAccount.address,
                                                                     context.network_provider.proxy)
        if farmTkNonce == 0:
            logger.warning("Skipped migrate farm event. No token retrieved.")
            return

        event = MigratePositionFarmEvent(farmTkAmount, farmTkNonce)

        # pre-event logging
        event_log = FarmEventResultLogData()
        event_log.set_generic_event_data(event, userAccount.address.bech32(), farmContract)
        event_log.set_pre_event_data(context.network_provider.proxy)

        tx_hash = farmContract.migratePosition(context.network_provider, userAccount, event)

        # post-event logging
        event_log.set_post_event_data(tx_hash, context.network_provider.proxy)
        context.results_logger.add_event_log(event_log)

    except Exception as ex:
        logger.error("Exception encountered:", ex)
        traceback.print_exception(*sys.exc_info())


def generate_deposit_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    tokens = [pd_contract.launched_token_id, pd_contract.accepted_token]
    # TODO: find a smarter/more configurable method of choosing which token to use
    # Option1: Based on account balance (after smart funds distribution e.g. 10% tokenA, 80% tokenB, 10%, mixed tokens)
    random.shuffle(tokens)
    deposited_token = tokens[0]

    _, amount, _ = get_token_details_for_address(deposited_token, user_account.address, context.network_provider.proxy)
    amount = random.randrange(amount)

    event = DepositPDLiquidityEvent(deposited_token, amount)
    tx_hash = pd_contract.deposit_liquidity(context.network_provider, user_account, event)

    # track and check event results
    # TODO: has to be reworked
    # if hasattr(context, 'price_discovery_trackers'):
    #     index = context.get_contract_index(config.PRICE_DISCOVERIES, pd_contract)
    #     context.price_discovery_trackers[index].deposit_event_tracking(
    #         event, user_account.address, tx_hash
    #     )


def generate_random_deposit_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_deposit_pd_liquidity_event(context, user_account, pd_contract)


def _generate_pd_redeem_token_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract,
                                    action: str, event_class, submit):
    """Spend a randomly chosen redeem token holding on a price discovery contract.

    Withdrawing and redeeming walk the user's redeem tokens identically; they differ only in what
    they are called in a failure report, the event they build, and the endpoint they submit through.
    """
    # TODO: find a smarter/more configurable method of choosing which token to use and how much
    tokens = get_all_token_nonces_details_for_account(pd_contract.redeem_token, user_account.address, context.network_provider.proxy)
    if len(tokens) == 0:
        log_step_fail(f"Generate {action} price discovery liquidity failed! No redeem tokens available.")
        return

    random.shuffle(tokens)
    deposit_token = tokens[0]
    nonce = int(deposit_token['nonce'])
    amount = random.randrange(int(deposit_token['balance']))

    event = event_class(pd_contract.redeem_token, nonce, amount)
    tx_hash = submit(context.network_provider, user_account, event)

    # track and check event results
    # TODO: has to be reworked
    # if hasattr(context, 'price_discovery_trackers'):
    #     index = context.get_contract_index(config.PRICE_DISCOVERIES, pd_contract)
    #     context.price_discovery_trackers[index].{action}_event_tracking(
    #         event, user_account.address, tx_hash
    #     )


def generate_withdraw_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    _generate_pd_redeem_token_event(context, user_account, pd_contract,
                                    "withdraw", WithdrawPDLiquidityEvent, pd_contract.withdraw_liquidity)


def generate_random_withdraw_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_withdraw_pd_liquidity_event(context, user_account, pd_contract)


def generate_redeem_pd_liquidity_event(context: Context, user_account: Account, pd_contract: PriceDiscoveryContract):
    _generate_pd_redeem_token_event(context, user_account, pd_contract,
                                    "redeem", RedeemPDLPTokensEvent, pd_contract.redeem_liquidity_position)


def generate_random_redeem_pd_liquidity_event(context: Context):
    user_account = context.get_random_user_account()
    pd_contract = context.get_random_price_discovery_contract()
    generate_redeem_pd_liquidity_event(context, user_account, pd_contract)
