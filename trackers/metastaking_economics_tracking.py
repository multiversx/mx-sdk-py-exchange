from erdpy.accounts import Address
from utils.utils_tx import NetworkProviders
from utils.utils_chain import print_test_step_pass
from utils.contract_data_fetchers import MetaStakingContractDataFetcher, ChainDataFetcher
from events.metastake_events import (EnterMetastakeEvent,
                                                       ExitMetastakeEvent,
                                                       ClaimRewardsMetastakeEvent)
from trackers.abstract_observer import Subscriber
from trackers.concrete_observer import Observable
from contracts.farm_contract import FarmContract
from trackers.farm_economics_tracking import FarmEconomics
from trackers.pair_economics_tracking import PairEconomics
from trackers.staking_economics_tracking import StakingEconomics
from events.farm_events import EnterFarmEvent, ClaimRewardsFarmEvent, ExitFarmEvent
from utils.utils_chain import decode_merged_attributes, base64_to_hex
from contracts.pair_contract import PairContract, RemoveLiquidityEvent, SetCorrectReservesEvent


class MetastakingEconomics(Subscriber):
    def __init__(self, contract_address: str, staking_address: str, farm_contract: FarmContract,
                 pair_contract: PairContract, network_provider: NetworkProviders):
        self.contract_address = Address(contract_address)
        self.farm_contract = farm_contract
        self.pair_contract = pair_contract
        self.network_provider = network_provider
        self.data_fetcher = MetaStakingContractDataFetcher(self.contract_address, self.network_provider.proxy.url)
        self.chain_data_fetcher = ChainDataFetcher(self.network_provider.proxy.url)

        self.staking_tracker = StakingEconomics(staking_address, self.network_provider)
        self.farm_tracker = FarmEconomics(farm_contract.address, farm_contract.version, self.network_provider)
        self.pair_tracker = PairEconomics(pair_contract.address, pair_contract.firstToken, pair_contract.secondToken,
                                          self.network_provider)
        self.staking_tracker.report_current_tracking_data()

    def check_enter_metastaking_data(self, publisher: Observable):
        """Farm Token Supply check might fail, the fix should come in a later PR"""

        farm_tk_amount = publisher.event.metastaking_tk_amount
        lp_tokens_amount = self.pair_tracker.pair_data_fetcher.get_data(
            'updateAndGetTokensForGivenPositionWithSafePrice', [farm_tk_amount]
        )
        first_token, second_token = self.__get_tokens_for_lp_amount(lp_tokens_amount)

        if first_token['token_id'] == publisher.contract.staking_token:
            event = EnterFarmEvent(first_token['token_id'], first_token['token_nonce'], first_token['amount'],
                                   '', 0, 0)
        else:
            event = EnterFarmEvent(second_token['token_id'], second_token['token_nonce'], second_token['amount'],
                                   '', 0, 0)

        self.staking_tracker.check_enter_staking_data(event, publisher.tx_hash)

    def __get_lp_from_metastake_token_attributes(self, token_attributes):
        """LP amount is the same as FarmTokenAmount"""

        attributes_schema_proxy_staked_tokens = {
            'lp_farm_token_nonce': 'u64',
            'lp_farm_token_amount': 'biguint',
            'staking_farm_token_nonce': 'u64',
            'staking_farm_token_amount': 'biguint',
        }

        lp_position = decode_merged_attributes(token_attributes, attributes_schema_proxy_staked_tokens)
        return lp_position

    def __get_tokens_for_lp_amount(self, lp_amount: list):
        """Returns tokens from LP position"""

        attribute_schema_lp_tokens = {
            'token_id': 'string',
            'token_nonce': 'u64',
            'amount': 'biguint'
        }

        first_token = decode_merged_attributes(lp_amount[0], attribute_schema_lp_tokens)
        second_token = decode_merged_attributes(lp_amount[1], attribute_schema_lp_tokens)

        return first_token, second_token

    def check_claim_rewards_data(self, publisher: Observable):
        """Farm Token Supply check might fail, the fix should come in a later PR"""

        claim_farm_rewards_event = ClaimRewardsFarmEvent(
            int(publisher.event.farm_token_details['supply']), publisher.event.farm_token_details['nonce'],
            base64_to_hex(publisher.event.farm_token_details['attributes'])
        )

        self.staking_tracker.check_claim_rewards_data(publisher.tx_hash)
        self.farm_tracker.check_claim_rewards_farm_tx_data(claim_farm_rewards_event, publisher.tx_hash)

    def __rule_of_three(self, first_amount, first_equivalent, second_amount):
        return (second_amount * first_equivalent) // first_amount

    def __compute_tokens_slippage(self, first_token: dict, second_token: dict, slippage: float):
        """This function receives as the input parameters the two tokens from an LP position
            and the slippage and returns the amounts for each token"""
        first_token_amount = first_token['amount'] - int(first_token['amount'] * slippage)
        second_token_amount = second_token['amount'] - int(second_token['amount'] * slippage)
        return first_token_amount, second_token_amount

    def check_exit_metastaking_data(self, publisher: Observable):
        decoded_metastake_tk_attributes = self.__get_lp_from_metastake_token_attributes(
            publisher.event.metastake_token_attributes)

        exit_staking_event = ExitFarmEvent(publisher.contract.staking_token,
                                           publisher.event.amount,
                                           decoded_metastake_tk_attributes['staking_farm_token_nonce'], '')
        self.staking_tracker.check_exit_staking_data(exit_staking_event, publisher.tx_hash)

        farm_token_amount = self.__rule_of_three(publisher.event.whole_metastake_token_amount,
                                                 decoded_metastake_tk_attributes['lp_farm_token_amount'],
                                                 publisher.event.amount)

        exit_farm_event = ExitFarmEvent(publisher.contract.farm_token,
                                        farm_token_amount,
                                        publisher.event.farm_token_details['nonce'],
                                        base64_to_hex(publisher.event.farm_token_details['attributes']))
        self.farm_tracker.exit_farm_event_tracking(publisher.user, exit_farm_event, publisher.tx_hash)

        lp_amount = farm_token_amount
        token_amounts = self.pair_tracker.pair_data_fetcher.get_data("getTokensForGivenPosition", [lp_amount])

        decoding_schema = {
            'token_id': 'string',
            'token_nonce': 'u64',
            'amount': 'biguint'
        }

        first_token_deserialized = decode_merged_attributes(token_amounts[0], decoding_schema)
        second_token_deserialized = decode_merged_attributes(token_amounts[1], decoding_schema)

        first_tk_amount, second_tk_amount = self.__compute_tokens_slippage(first_token_deserialized,
                                                                           second_token_deserialized,
                                                                           0.05)

        remove_liquidity_event = RemoveLiquidityEvent(lp_amount, first_token_deserialized['token_id'], first_tk_amount,
                                                      second_token_deserialized['token_id'], second_tk_amount)
        self.pair_tracker.check_remove_liquidity(remove_liquidity_event)

    def check_enter_metastaking(self, publisher: Observable):
        self.staking_tracker.check_invariant_properties()
        self.staking_tracker.check_enter_staking_properties()
        self.check_enter_metastaking_data(publisher)
        print_test_step_pass('Checked enter metastaking event economics!')

    def check_exit_metastaking(self, publisher: Observable):
        self.staking_tracker.check_invariant_properties()
        self.staking_tracker.check_exit_staking_properties()
        self.check_exit_metastaking_data(publisher)
        print_test_step_pass('Checked exit metastaking event economics!')

    def check_claim_rewards(self, publisher: Observable):
        self.staking_tracker.check_invariant_properties()
        self.staking_tracker.check_claim_rewards_properties()
        self.check_claim_rewards_data(publisher)
        print_test_step_pass('Checked claim metastaking rewards event economics!')

    def update_trackers_data(self):
        self.staking_tracker.update_data()
        self.farm_tracker.update_tracking_data()
        self.pair_tracker._get_tokens_reserve_and_total_supply()

    def update(self, publisher: Observable):
        if publisher.contract is not None:
            if str(self.contract_address) == publisher.contract.address:
                if publisher.tx_hash:
                    self.network_provider.api.wait_for_tx_finalized(publisher.tx_hash)
                if isinstance(publisher.event, SetCorrectReservesEvent):
                    self.update_trackers_data()
                elif isinstance(publisher.event, EnterMetastakeEvent):
                    self.check_enter_metastaking(publisher)
                elif isinstance(publisher.event, ExitMetastakeEvent):
                    self.check_exit_metastaking(publisher)
                elif isinstance(publisher.event, ClaimRewardsMetastakeEvent):
                    self.check_claim_rewards(publisher)
