from multiversx_sdk import Address
from utils.utils_tx import NetworkProviders
from trackers.concrete_observer import Observable
from trackers.rewards_economics_base import _RewardsEconomicsBase
from events.farm_events import EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import StakingContractDataFetcher, ChainDataFetcher
from utils.utils_generic import log_step_fail, log_step_pass, log_substep


class StakingEconomics(_RewardsEconomicsBase):

    _TRACKING_HEADER = "Staking contract address"

    _TRACKED_FIELDS = (
        ("Staking farm token supply", "token_supply"),
        ("Rewards per block", "rewards_per_block"),
        ("Last rewards block nonce", "last_rewards_block_nonce"),
        ("Annual percentage rewards", "annual_percentage_rewards"),
        ("Rewards capacity", "rewards_capacity"),
        ("Rewards per share", "rewards_per_share"),
    )

    def __init__(self, address: str, network_provider: NetworkProviders):
        self.contract_address = Address(address, "erd")
        self.network_provider = network_provider
        self.data_fetcher = StakingContractDataFetcher(self.contract_address, self.network_provider.proxy.url)
        self.chain_data_fetcher = ChainDataFetcher(self.network_provider.proxy.url)

        self.min_unbond_epochs = None
        self.division_safety_constant = None
        self.rewards_per_share = None
        self.rewards_capacity = None
        self.annual_percentage_rewards = None
        self.rewards_per_block = None
        self.last_rewards_block_nonce = None
        self.token_supply = None

        self.update_data()
        self.last_block_calculated_rewards = self.last_rewards_block_nonce

        self.report_current_tracking_data()

    def update_data(self):
        self.token_supply = self.data_fetcher.get_data('getFarmTokenSupply')
        self.last_rewards_block_nonce = self.data_fetcher.get_data('getLastRewardBlockNonce')
        self.rewards_per_block = self.data_fetcher.get_data('getPerBlockRewardAmount')
        self.annual_percentage_rewards = self.data_fetcher.get_data('getAnnualPercentageRewards')
        self.rewards_capacity = self.data_fetcher.get_data('getRewardCapacity')
        self.rewards_per_share = self.data_fetcher.get_data('getRewardPerShare')
        self.min_unbond_epochs = self.data_fetcher.get_data('getMinUnbondEpochs')
        self.division_safety_constant = self.data_fetcher.get_data('getDivisionSafetyConstant')

    @property
    def _rewards_data_fetcher(self):
        return self.data_fetcher

    def _refresh_tracking_data(self) -> None:
        self.update_data()
        self.report_current_tracking_data()

    def check_enter_staking_properties(self):
        new_token_supply = self.data_fetcher.get_data("getFarmTokenSupply")
        if self.token_supply >= new_token_supply:
            log_step_fail('Staking farm token supply did not increase')
            log_substep(f"Old token supply: {self.token_supply}")
            log_substep(f"New token supply: {new_token_supply}")

        log_step_pass('Checked enter staking properties!')

    def check_enter_staking_data(self, event: EnterFarmEvent, tx_hash: str):
        new_staking_token_supply = self.data_fetcher.get_data("getFarmTokenSupply")
        new_contract_rewards_per_share = self.data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(tx_hash)

        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block
        expected_token_supply = self.token_supply + event.farming_tk_amount

        if self.token_supply:
            new_exp_rewards_per_share = self.rewards_per_share + \
                                        (self.division_safety_constant * aggregated_rewards // self.token_supply)
        else:
            new_exp_rewards_per_share = 0

        if new_staking_token_supply != expected_token_supply:
            log_step_fail('TEST CHECK FAIL: Staking token supply not as expected!')
            log_substep(f"Old Staking token supply: {self.token_supply}")
            log_substep(f"New Staking token supply: {new_staking_token_supply}")
            log_substep(f"Expected Staking token supply: {expected_token_supply}")

        if new_contract_rewards_per_share != new_exp_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {new_exp_rewards_per_share}")

        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        self.last_block_calculated_rewards = tx_block
        log_step_pass('Checked enter staking data!')

    def check_exit_staking_properties(self):
        new_token_supply = self.data_fetcher.get_data('getFarmTokenSupply')
        if self.token_supply <= new_token_supply:
            log_step_fail('Staking farm token supply did not decrease')
            log_substep(f"Old token supply: {self.token_supply}")
            log_substep(f"New token supply: {new_token_supply}")

        log_step_pass('Checked exit staking properties')

    def check_exit_staking_data(self, event: ExitFarmEvent, tx_hash: str):
        new_token_supply = self.data_fetcher.get_data('getFarmTokenSupply')
        new_contract_rewards_per_share = self.data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(tx_hash)
        expected_token_supply = self.token_supply - event.amount

        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block

        expected_rewards_per_share = self.rewards_per_share +\
                                    (self.division_safety_constant * aggregated_rewards // self.token_supply)

        if new_token_supply != expected_token_supply:
            log_step_fail(f"TEST CHECK FAIL: Farm token supply not as expected!")
            log_substep(f"Farm token supply in contract: {new_token_supply}")
            log_substep(f"Expected Farm token supply: {expected_token_supply}")

        if new_contract_rewards_per_share != expected_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {expected_rewards_per_share}")

        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        self.last_block_calculated_rewards = tx_block
        log_step_pass('Checked exit staking data')

    def check_claim_rewards_properties(self):
        new_token_supply = self.data_fetcher.get_data('getFarmTokenSupply')
        if self.token_supply != new_token_supply:
            log_step_fail('Token supply modified!')
            log_substep(f"Old Farm token supply: {self.token_supply}")
            log_substep(f"New Farm token supply: {new_token_supply}")

        log_step_pass("Checked claim rewards properties!")

    def check_claim_rewards_data(self, tx_hash):
        new_token_supply = self.data_fetcher.get_data('getFarmTokenSupply')
        new_rewards_per_share = self.data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(tx_hash)
        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block

        new_exp_rewards_per_share = self.rewards_per_share + \
                                    (self.division_safety_constant * aggregated_rewards // self.token_supply)

        if new_token_supply != self.token_supply:
            log_step_fail(f"TEST CHECK FAIL: Token supply not as expected!")
            log_substep(f"Farm token supply in contract: {new_token_supply}")
            log_substep(f"Expected Farm token supply: {self.token_supply}")

        if new_rewards_per_share != new_exp_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {new_exp_rewards_per_share}")

        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        self.last_block_calculated_rewards = tx_block
        log_step_pass("Checked claim staking rewards data!")

    def enter_staking_event(self, event: EnterFarmEvent, tx_hash):
        self._track_event(self.check_enter_staking_properties, self.check_enter_staking_data, event, tx_hash)

    def exit_staking_event(self, event: ExitFarmEvent, tx_hash):
        self._track_event(self.check_exit_staking_properties, self.check_exit_staking_data, event, tx_hash)

    def claim_rewards_staking_event(self, tx_hash):
        self._track_event(self.check_claim_rewards_properties, self.check_claim_rewards_data, tx_hash)

    def update(self, publisher: Observable):
        if publisher.contract is not None:
            if self.contract_address.bech32() == publisher.contract.address:
                self.network_provider.wait_for_tx_executed(publisher.tx_hash)
                if type(publisher.event) == EnterFarmEvent:
                    self.enter_staking_event(publisher.event, publisher.tx_hash)
                elif type(publisher.event) == ExitFarmEvent:
                    self.exit_staking_event(publisher.event, publisher.tx_hash)
                elif type(publisher.event) == ClaimRewardsFarmEvent:
                    self.claim_rewards_staking_event(publisher.tx_hash)
