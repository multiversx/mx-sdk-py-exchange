from multiversx_sdk_cli.accounts import Address
from utils.utils_tx import NetworkProviders
from trackers.abstract_observer import Subscriber
from trackers.concrete_observer import Observable
from events.farm_events import EnterFarmEvent, ExitFarmEvent, ClaimRewardsFarmEvent
from utils.contract_data_fetchers import StakingContractDataFetcher, ChainDataFetcher
from utils.utils_generic import log_step_fail, log_step_pass, log_substep


class StakingEconomics(Subscriber):
    def __init__(self, address: str, network_provider: NetworkProviders):
        self.contract_address = Address(address)
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

    def report_current_tracking_data(self):
        print(f"Staking contract address: {self.contract_address.bech32()}")
        print(f"Staking farm token supply: {self.token_supply}")
        print(f"Rewards per block: {self.rewards_per_block}")
        print(f"Last rewards block nonce: {self.last_rewards_block_nonce}")
        print(f"Annual percentage rewards: {self.annual_percentage_rewards}")
        print(f"Rewards capacity: {self.rewards_capacity}")
        print(f"Rewards per share: {self.rewards_per_share}")

    def check_invariant_properties(self):
        new_rewards_per_share = self.data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.data_fetcher.get_data("getLastRewardBlockNonce")
        chain_rewards_per_block = self.data_fetcher.get_data("getPerBlockRewardAmount")
        chain_division_safety_constant = self.data_fetcher.get_data("getDivisionSafetyConstant")

        if self.rewards_per_share > new_rewards_per_share:
            log_step_fail("TEST CHECK FAIL: Rewards per share decreased!")
            log_substep(f"Old rewards per share: {self.rewards_per_share}")
            log_substep(f"New rewards per share: {new_rewards_per_share}")
        if self.last_rewards_block_nonce > new_last_rewards_block_nonce:
            log_step_fail("TEST CHECK FAIL: Last rewards block nonce decreased!")
            log_substep(f"Old rewards block nonce: {self.last_rewards_block_nonce}")
            log_substep(f"New rewards block nonce: {new_last_rewards_block_nonce}")
        if self.rewards_per_block != chain_rewards_per_block:
            log_step_fail("TEST CHECK FAIL: Rewards per block has changed!")
            log_substep(f"Old rewards per block: {self.rewards_per_block}")
            log_substep(f"New rewards per block: {chain_rewards_per_block}")
        if self.division_safety_constant != chain_division_safety_constant:
            log_step_fail("TEST CHECK FAIL: Division safety constant has changed!")
            log_substep(f"Old division safety constant: {self.division_safety_constant}")
            log_substep(f"New division safety constant: {chain_division_safety_constant}")

        log_step_pass("Checked invariant properties!")

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
        self.check_invariant_properties()
        self.check_enter_staking_properties()
        self.check_enter_staking_data(event, tx_hash)
        self.update_data()
        self.report_current_tracking_data()

    def exit_staking_event(self, event: ExitFarmEvent, tx_hash):
        self.check_invariant_properties()
        self.check_exit_staking_properties()
        self.check_exit_staking_data(event, tx_hash)
        self.update_data()
        self.report_current_tracking_data()

    def claim_rewards_staking_event(self, tx_hash):
        self.check_invariant_properties()
        self.check_claim_rewards_properties()
        self.check_claim_rewards_data(tx_hash)
        self.update_data()
        self.report_current_tracking_data()

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
