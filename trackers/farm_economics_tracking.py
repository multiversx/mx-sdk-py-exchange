from typing import Dict
from multiversx_sdk import Address
from utils.utils_chain import Account
from utils.contract_data_fetchers import FarmContractDataFetcher, ChainDataFetcher
from utils.utils_tx import NetworkProviders
from utils.utils_generic import log_step_fail, log_step_pass, log_substep
from events.farm_events import (EnterFarmEvent, ExitFarmEvent,
                                ClaimRewardsFarmEvent, SetTokenBalanceEvent)
from trackers.abstract_observer import Subscriber
from trackers.concrete_observer import Observable
from utils.utils_chain import get_current_tokens_for_address
from contracts.contract_identities import FarmContractVersion


class DecodedTokenAttributes:
    rewards_per_share: int
    original_entering_epoch: int
    entering_epoch: int
    apr_multiplier: int
    locked_rewards: bool
    initial_farming_amount: int
    compounded_rewards: int
    current_farm_amount: int

    def __init__(self, attributes_hex: str, attr_version: FarmContractVersion = None):
        # TODO: implement it using the new decoders
        pass


class FarmAccountEconomics(Subscriber):

    def __init__(self, address: Address, network_provider: NetworkProviders):
        self.address = address
        self.network_provider = network_provider
        self.tokens = get_current_tokens_for_address(self.address, self.network_provider.proxy)
        self.report_current_tokens()

    def enter_farm(self, event: EnterFarmEvent) -> None:
        old_farming_token_balance = int(self.tokens[event.farming_tk]['balance'])
        farm_token = self.tokens.get(event.farm_tk, None)
        old_farm_token_balance = farm_token['balance'] if farm_token else 0
        old_farm_token_nonce = farm_token['nonce'] if farm_token else 0

        self.tokens = get_current_tokens_for_address(self.address, self.network_provider.proxy)

        new_farming_token_balance = int(self.tokens[event.farming_tk]['balance'])
        new_farm_token_balance = int(self.tokens[event.farm_tk]['balance'])
        new_farm_token_nonce = int(self.tokens[event.farm_tk]['nonce'])

        expected_farming_token_balance = int(old_farming_token_balance) - event.farming_tk_amount
        expected_farm_token_balance = int(old_farm_token_balance) + event.farming_tk_amount

        if old_farm_token_nonce >= new_farm_token_nonce:
            log_step_fail(f'Farm token nonce did not increase for {self.address.bech32()}')
            log_substep(f'Old farm token nonce: {old_farm_token_nonce}')
            log_substep(f'New farm token nonce: {new_farm_token_nonce}')

        if new_farming_token_balance != expected_farming_token_balance:
            log_step_fail(f'Farming token balance did not decrease for account {self.address.bech32()}')
            log_substep(f'Old farming token amount: {old_farming_token_balance}')
            log_substep(f'New farming token amount: {new_farming_token_balance}')
            log_substep(f'Expected farming token amount: {expected_farming_token_balance}')

        if farm_token is not None:
            if new_farm_token_balance != expected_farm_token_balance:
                log_step_fail(f'Farm token balance did not increase for account {self.address.bech32()}')
                log_substep(f'Old farm token amount: {old_farm_token_balance}')
                log_substep(f'New farm token amount: {new_farm_token_balance}')
                log_substep(f'Expected farm token amount: {expected_farm_token_balance}')

        log_step_pass('Checked enter farm event economics for account')

    def exit_farm(self, contract, event: ExitFarmEvent) -> None:
        farm_token = self.tokens.get(event.farm_token, None)
        old_farm_token_balance = farm_token['balance'] if farm_token else 0

        farming_token = self.tokens.get(contract.farmingToken, None)
        old_farming_token_balance = farming_token['balance'] if farming_token else 0

        farmed_token = self.tokens.get(contract.farmedToken, None)
        old_farmed_token_balance = farmed_token['balance'] if farmed_token else 0

        self.tokens = get_current_tokens_for_address(self.address, self.network_provider.proxy)

        new_farm_token_balance = int(self.tokens[event.farm_token]['balance'])
        expected_farm_token_balance = int(old_farm_token_balance) - event.amount

        new_farming_token_balance = int(self.tokens[contract.farmingToken]['balance'])
        expected_farming_token_balance = old_farming_token_balance + event.amount

        new_farmed_token_balance = int(self.tokens[contract.farmedToken]['balance'])

        if new_farm_token_balance != expected_farm_token_balance:
            log_step_fail(f'Farm token amount did not decrease for account {self.address.bech32()}')
            log_substep(f'Old farm token amount: {old_farm_token_balance}')
            log_substep(f'New farm token amount: {new_farm_token_balance}')
            log_substep(f'Expected farm token amount: {expected_farm_token_balance}')

        if new_farming_token_balance != expected_farming_token_balance:
            log_step_fail(f'Farming token amount did not increase for account {self.address.bech32()}')
            log_substep(f'Old farming token amount {old_farming_token_balance}')
            log_substep(f'New farming token amount {new_farming_token_balance}')
            log_substep(f'Expected farming token amount {expected_farming_token_balance}')

        if old_farmed_token_balance >= new_farmed_token_balance:
            log_step_fail(f'Farmed token amount did not increase for account {self.address.bech32()}')
            log_substep(f'Old farmed token amount {old_farmed_token_balance}')
            log_substep(f'New farmed token amount {new_farmed_token_balance}')

        log_step_pass('Checked exit farm event economics for account')

    def claim_rewards(self, contract, event: ClaimRewardsFarmEvent) -> None:
        farmed_token = self.tokens.get(contract.farmedToken, None)
        old_farmed_token_balance = farmed_token['balance'] if farmed_token else 0

        self.tokens = get_current_tokens_for_address(self.address, self.network_provider.proxy)

        new_farmed_token_balance = int(self.tokens[contract.farmedToken]['balance'])
        expected_farmed_token_balance = int(old_farmed_token_balance) + event.amount

        if new_farmed_token_balance != expected_farmed_token_balance:
            log_step_fail(f'Farmed token amount did not increase for account {self.address.bech32()}')
            log_substep(f'Old farm token amount: {old_farmed_token_balance}')
            log_substep(f'New farm token amount: {new_farmed_token_balance}')
            log_substep(f'Expected farm token amount: {expected_farmed_token_balance}')

        log_step_pass('Checked claim rewards event economics for account')

    def report_current_tokens(self):
        log_step_pass(f'All tokens for account {self.address}')
        for key in self.tokens:
            log_substep(f'{key}: {self.tokens[key]["balance"]}')

    def set_token_balance(self, event: SetTokenBalanceEvent):
        if event.token not in self.tokens:
            token = {event.token: {'nonce': event.nonce, 'balance': event.balance}}

            self.tokens.update(token)
        else:
            self.tokens[event.token]['nonce'] = event.nonce
            self.tokens[event.token]['balance'] = event.balance

        log_step_pass(f'Updated token balance for account {self.address.bech32()}')

    def update(self, publisher: Observable):
        if publisher.user.address == self.address:
            if publisher.tx_hash:
                self.network_provider.wait_for_tx_executed(publisher.tx_hash)
            if type(publisher.event) == EnterFarmEvent:
                self.enter_farm(publisher.event)
            elif type(publisher.event) == ExitFarmEvent:
                self.exit_farm(publisher.contract, publisher.event)
            elif type(publisher.event) == ClaimRewardsFarmEvent:
                self.claim_rewards(publisher.contract, publisher.event)
            elif type(publisher.event) == SetTokenBalanceEvent:
                self.set_token_balance(publisher.event)


class FarmEconomics(Subscriber):

    def __init__(self, contract_address: str, version: FarmContractVersion, network_provider: NetworkProviders):
        self.contract_address = Address(contract_address, "erd")
        self.version = version
        self.network_provider = network_provider
        self.farm_data_fetcher = FarmContractDataFetcher(self.contract_address, network_provider.proxy.url)
        self.chain_data_fetcher = ChainDataFetcher(network_provider.proxy.url)
        self.accounts: Dict[str, FarmAccountEconomics] = {}

        self.rewards_per_block = self.farm_data_fetcher.get_data("getPerBlockRewardAmount")
        self.farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        self.rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")
        self.rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        self.last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        self.last_block_calculated_rewards = self.last_rewards_block_nonce  # initialize with the last one from contract
        self.division_safety_constant = self.farm_data_fetcher.get_data("getDivisionSafetyConstant")
        self.rewards_per_share_wout_division = 0

        # only v1.2 farms
        self.farm_token_supply_locked = 0
        self.farm_token_supply_unlocked = 0

        self.report_current_tracking_data()

    def report_current_tracking_data(self):
        print(f"Farm: {self.contract_address.bech32()}")
        print(f"Farm token supply: {self.farm_token_supply}")
        print(f"Rewards per block: {self.rewards_per_block}")
        print(f"Rewards reserve: {self.rewards_reserve}")
        print(f"Rewards per share: {self.rewards_per_share}")
        print(f"Last rewards block nonce: {self.last_rewards_block_nonce}")
        print(f"Last block offline calculated rewards: {self.last_block_calculated_rewards}")

    # checks and updates the farm contract invariant properties
    def check_invariant_properties(self):
        # TODO: replace test reporting with logger
        new_rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        chain_rewards_per_block = self.farm_data_fetcher.get_data("getPerBlockRewardAmount")
        chain_division_safety_constant = self.farm_data_fetcher.get_data("getDivisionSafetyConstant")

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

    def check_enter_farm_properties(self):
        # track event dependent properties
        new_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        new_rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")

        ENTER_FARM_FARM_TK_SUPPLY_FAIL = "TEST CHECK FAIL: Farm token supply did not increase!"
        ENTER_FARM_REWARDS_RESERVE_FAIL = "TEST CHECK FAIL: Rewards reserve decreased!"

        if self.farm_token_supply >= new_farm_token_supply:
            log_step_fail(ENTER_FARM_FARM_TK_SUPPLY_FAIL)
            log_substep(f"Old Farm token supply: {self.farm_token_supply}")
            log_substep(f"New Farm token supply: {new_farm_token_supply}")
        if self.rewards_reserve >= new_rewards_reserve:
            log_step_fail(ENTER_FARM_REWARDS_RESERVE_FAIL)
            log_substep(f"Old Rewards reserve: {self.rewards_reserve}")
            log_substep(f"New Rewards reserve: {new_rewards_reserve}")

        log_step_pass("Checked enter farm properties!")

    def check_enter_farm_tx_data(self, event: EnterFarmEvent, txhash: str):
        new_contract_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        new_contract_rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")
        new_contract_rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(txhash)
        new_exp_farm_token_supply = self.farm_token_supply + event.farming_tk_amount  # farming token amount is converted to farm token amount

        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block
        new_exp_rewards_reserve = self.rewards_reserve + aggregated_rewards
        # NOTE: rewards per share value applies a division safety constant in calculus which is later taken out when actual rewards are calculated
        if self.farm_token_supply != 0:
            new_exp_rewards_per_share = self.rewards_per_share + \
                                        (self.division_safety_constant * aggregated_rewards // self.farm_token_supply)
            self.rewards_per_share_wout_division = new_exp_rewards_reserve // self.farm_token_supply
            # todo: clarify if rewards per share should not consider the new farm tokens
        else:
            new_exp_rewards_per_share = 0

        def report_generic_fails():
            log_substep(f"Old Rewards reserve: {self.rewards_reserve}")
            log_substep(f"New Rewards reserve in contract: {new_contract_rewards_reserve}")
            log_substep(f"Expected Rewards reserve: {new_exp_rewards_reserve}")
            log_substep(f"Aggregated rewards: {aggregated_rewards}")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            log_substep(f"Rewards per block: {self.rewards_per_block}")
            log_substep(f"TX hash: {txhash}")
            log_substep(f"TX block nonce: {tx_block}")
            log_substep(f"Last calculated rewards at block nonce:{self.last_block_calculated_rewards}")

        # check for FARM TOKEN SUPPLY integrity
        if new_contract_farm_token_supply != new_exp_farm_token_supply:
            log_step_fail(f"TEST CHECK FAIL: Farm token supply not as expected!")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            report_generic_fails()

        # check for REWARDS PER SHARE integrity
        if new_contract_rewards_per_share != new_exp_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {new_exp_rewards_per_share}")
            report_generic_fails()

        # check for REWARDS RESERVE integrity
        if new_contract_rewards_reserve != new_exp_rewards_reserve:
            log_step_fail(f"TEST CHECK FAIL: Rewards reserve not as expected!")
            report_generic_fails()

        # check for LAST REWARD BLOCK integrity
        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        # TODO: decide afterwards if this is a good place for this update, or whether it should be moved with the others
        self.last_block_calculated_rewards = tx_block

        log_step_pass("Checked enter farm tx data!")

    def check_exit_farm_properties(self):
        # track event dependent properties
        new_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")

        EXIT_FARM_FARM_TK_SUPPLY_FAIL = "TEST CHECK FAIL: Farm token supply did not decrease!"

        if self.farm_token_supply <= new_farm_token_supply:
            log_step_fail(f"{EXIT_FARM_FARM_TK_SUPPLY_FAIL}")
            log_substep(f"Old Farm token supply: {self.farm_token_supply}")
            log_substep(f"New Farm token supply: {new_farm_token_supply}")

        """moved into exit farm check as it can differ from case to case based on side of exit position
        if self.rewards_reserve < new_rewards_reserve:  # TODO: have to check whether rewards should be given and if it increased
            print_test_step_fail(f"{EXIT_FARM_REWARDS_RESERVE_FAIL}")
            print_test_substep(f"Old Rewards reserve: {self.rewards_reserve}")
            print_test_substep(f"New Rewards reserve: {new_rewards_reserve}")
            """

        log_step_pass(f"Checked exit farm properties!")

    def check_exit_farm_tx_data(self, event: ExitFarmEvent, txhash: str):
        # TODO: check burned tokens if penalty applies
        # TODO: care for compounding as well when calculating penalty
        new_contract_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        new_contract_rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")
        new_contract_rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(txhash)
        new_exp_farm_token_supply = self.farm_token_supply - event.amount

        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block
        # NOTE: rewards per share value applies a division safety constant in calculus which is later taken out when actual rewards are calculated
        new_exp_rewards_per_share = self.rewards_per_share + \
                                    (self.division_safety_constant * aggregated_rewards // self.farm_token_supply)

        # TODO: store a snapshot of farm tokens amounts at event creation and use it to compare afterwards for results

        decoded_attrs = DecodedTokenAttributes(event.attributes, self.version)
        # TODO: check what's the correct variant of calculating the drop in Rewards reserve and Rewards for exit position
        exp_rewards = (new_exp_rewards_per_share - decoded_attrs.rewards_per_share) // self.division_safety_constant * event.amount
        new_exp_rewards_reserve = self.rewards_reserve + aggregated_rewards - exp_rewards
        self.rewards_per_share_wout_division = new_exp_rewards_reserve // self.farm_token_supply

        # todo: clarify if rewards per share should not consider the new farm tokens

        def report_generic_fails():
            log_substep(f"Old Rewards reserve: {self.rewards_reserve}")
            log_substep(f"New Rewards reserve in contract: {new_contract_rewards_reserve}")
            log_substep(f"Expected Rewards reserve: {new_exp_rewards_reserve}")
            log_substep(f"Aggregated rewards: {aggregated_rewards}")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            log_substep(f"Rewards per block: {self.rewards_per_block}")
            log_substep(f"TX hash: {txhash}")
            log_substep(f"TX block nonce: {tx_block}")
            log_substep(f"Last calculated rewards at block nonce:{self.last_block_calculated_rewards}")

        # check for FARM TOKEN SUPPLY integrity
        if new_contract_farm_token_supply != new_exp_farm_token_supply:
            log_step_fail(f"TEST CHECK FAIL: Farm token supply not as expected!")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            report_generic_fails()

        # check for REWARDS PER SHARE integrity
        if new_contract_rewards_per_share != new_exp_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {new_exp_rewards_per_share}")
            report_generic_fails()

        # check for REWARDS RESERVE integrity
        if new_contract_rewards_reserve != new_exp_rewards_reserve:
            log_step_fail(f"TEST CHECK FAIL: Rewards reserve not as expected!")
            log_substep(f"Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Rewards per share in exit position: {decoded_attrs.rewards_per_share}")
            log_substep(f"Exit position amount: {event.amount}")
            log_substep(f"Expected rewards per position: {exp_rewards}")
            report_generic_fails()

        # check for LAST REWARD BLOCK integrity
        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        # TODO: decide afterwards if this is a good place for this update, or whether it should be moved with the others
        self.last_block_calculated_rewards = tx_block

        log_step_pass("Checked exit farm tx data!")

    def check_claim_rewards_properties(self):
        # track event dependent properties
        new_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")

        CLAIM_REWARDS_FARM_TK_SUPPLY_FAIL = "TEST CHECK FAIL: Farm token supply modified!"

        if self.farm_token_supply != new_farm_token_supply:
            log_step_fail(CLAIM_REWARDS_FARM_TK_SUPPLY_FAIL)
            log_substep(f"Old Farm token supply: {self.farm_token_supply}")
            log_substep(f"New Farm token supply: {new_farm_token_supply}")

        log_step_pass("Checked claim rewards properties!")

    def check_claim_rewards_farm_tx_data(self, event: ClaimRewardsFarmEvent, txhash: str):
        # TODO: check burned tokens if penalty applies
        # TODO: care for compounding as well when calculating penalty
        new_contract_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        new_contract_rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")
        new_contract_rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        tx_block = self.chain_data_fetcher.get_tx_block_nonce(txhash)
        new_exp_farm_token_supply = self.farm_token_supply

        aggregated_rewards = (tx_block - self.last_block_calculated_rewards) * self.rewards_per_block
        # NOTE: rewards per share value applies a division safety constant in calculus which is later taken out when actual rewards are calculated
        new_exp_rewards_per_share = self.rewards_per_share + \
                                    (self.division_safety_constant * aggregated_rewards // self.farm_token_supply)

        # TODO: store a snapshot of farm tokens amounts at event creation and use it to compare afterwards for results

        decoded_attrs = DecodedTokenAttributes(event.attributes, self.version)
        # TODO: check what's the correct variant of calculating the drop in Rewards reserve and Rewards for exit position
        exp_rewards = (new_exp_rewards_per_share - decoded_attrs.rewards_per_share) // self.division_safety_constant * event.amount
        new_exp_rewards_reserve = self.rewards_reserve + aggregated_rewards - exp_rewards
        self.rewards_per_share_wout_division = new_exp_rewards_reserve // self.farm_token_supply

        # todo: clarify if rewards per share should not consider the new farm tokens

        def report_generic_fails():
            log_substep(f"Old Rewards reserve: {self.rewards_reserve}")
            log_substep(f"New Rewards reserve in contract: {new_contract_rewards_reserve}")
            log_substep(f"Expected Rewards reserve: {new_exp_rewards_reserve}")
            log_substep(f"Aggregated rewards: {aggregated_rewards}")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            log_substep(f"Rewards per block: {self.rewards_per_block}")
            log_substep(f"TX hash: {txhash}")
            log_substep(f"TX block nonce: {tx_block}")
            log_substep(f"Last calculated rewards at block nonce:{self.last_block_calculated_rewards}")

        # check for FARM TOKEN SUPPLY integrity
        if new_contract_farm_token_supply != new_exp_farm_token_supply:
            log_step_fail(f"TEST CHECK FAIL: Farm token supply not as expected!")
            log_substep(f"Farm token supply in contract: {new_contract_farm_token_supply}")
            log_substep(f"Expected Farm token supply: {new_exp_farm_token_supply}")
            report_generic_fails()

        # check for REWARDS PER SHARE integrity
        if new_contract_rewards_per_share != new_exp_rewards_per_share:
            log_step_fail(f"TEST CHECK FAIL: Rewards per share not as expected!")
            log_substep(f"Old Rewards per share in contract: {self.rewards_per_share}")
            log_substep(f"New Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Expected Rewards per share: {new_exp_rewards_per_share}")
            report_generic_fails()

        # check for REWARDS RESERVE integrity
        if new_contract_rewards_reserve != new_exp_rewards_reserve:
            log_step_fail(f"TEST CHECK FAIL: Rewards reserve not as expected!")
            log_substep(f"Rewards per share in contract: {new_contract_rewards_per_share}")
            log_substep(f"Rewards per share in exit position: {decoded_attrs.rewards_per_share}")
            log_substep(f"Exit position amount: {event.amount}")
            log_substep(f"Expected rewards per position: {exp_rewards}")
            report_generic_fails()

        # check for LAST REWARD BLOCK integrity
        if tx_block != new_last_rewards_block_nonce:
            log_step_fail(f"TEST CHECK FAIL: Last rewards block nonce not as expected!")
            log_substep(f"Last reward block nonce in contract: {new_last_rewards_block_nonce}")
            log_substep(f"Expected last reward block nonce: {tx_block}")

        # TODO: decide afterwards if this is a good place for this update, or whether it should be moved with the others
        self.last_block_calculated_rewards = tx_block

        log_step_pass("Checked claim rewards tx data!")

    def __enter_farm_event_for_account(self, account: Account, block: int, lp_staked: int):
        if account.address.to_bech32() not in self.accounts:
            self.accounts[account.address.to_bech32()] = FarmAccountEconomics(account.address)
        self.accounts[account.address.to_bech32()].enter_farm(self.rewards_per_share, block, lp_staked)
        # TODO: integrate this tracker in the enter farm event and care for the proper initialization of LP staked when
        # there are already existing positions in farm

    def update_tracking_data(self):
        new_rewards_per_share = self.farm_data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = self.farm_data_fetcher.get_data("getLastRewardBlockNonce")
        chain_rewards_per_block = self.farm_data_fetcher.get_data("getPerBlockRewardAmount")
        new_farm_token_supply = self.farm_data_fetcher.get_data("getFarmTokenSupply")
        new_rewards_reserve = self.farm_data_fetcher.get_data("getRewardReserve")
        new_division_safety_constant = self.farm_data_fetcher.get_data("getDivisionSafetyConstant")

        # TODO: update only the data that doesn't match
        self.last_rewards_block_nonce = new_last_rewards_block_nonce
        self.rewards_per_share = new_rewards_per_share
        self.rewards_per_block = chain_rewards_per_block
        self.farm_token_supply = new_farm_token_supply
        self.rewards_reserve = new_rewards_reserve
        self.division_safety_constant = new_division_safety_constant

        log_step_pass("Updated farm tracking data!")

    def enter_farm_event_tracking(self, account: Account, event: EnterFarmEvent, txhash: str, lock: int = 0):
        # TODO: replace error reporting with logger
        # track invariant properties
        self.check_invariant_properties()
        self.check_enter_farm_properties()
        self.check_enter_farm_tx_data(event, txhash)
        self.update_tracking_data()

    def exit_farm_event_tracking(self, account: Account, event: ExitFarmEvent, txhash: str):
        # TODO: replace error reporting with logger
        # track invariant properties
        self.check_invariant_properties()
        self.check_exit_farm_properties()
        self.check_exit_farm_tx_data(event, txhash)
        self.update_tracking_data()

    def claim_rewards_farm_event_tracking(self, account: Account, event: ExitFarmEvent, txhash: str):
        self.check_invariant_properties()
        self.check_claim_rewards_properties()
        self.check_claim_rewards_farm_tx_data(event, txhash)
        self.update_tracking_data()

    def update(self, publisher: Observable):
        if publisher.contract is not None:
            if str(self.contract_address) == publisher.contract.address:
                self.network_provider.wait_for_tx_executed(publisher.tx_hash)
                if type(publisher.event) == EnterFarmEvent:
                    self.enter_farm_event_tracking(publisher.user, publisher.event, publisher.tx_hash)
                elif type(publisher.event) == ExitFarmEvent:
                    self.exit_farm_event_tracking(publisher.user, publisher.event, publisher.tx_hash)
                elif type(publisher.event) == ClaimRewardsFarmEvent:
                    self.claim_rewards_farm_event_tracking(publisher.user, publisher.event, publisher.tx_hash)
