from erdpy.accounts import Address
from utils.utils_tx import NetworkProviders
from trackers.abstract_observer import Subscriber
from trackers.concrete_observer import Observable
from utils.contract_data_fetchers import PairContractDataFetcher
from utils.utils_generic import log_step_fail, log_step_pass, log_substep
from contracts.pair_contract import (AddLiquidityEvent,
                                                       RemoveLiquidityEvent,
                                                       SwapFixedInputEvent,
                                                       SwapFixedOutputEvent,
                                                       SetCorrectReservesEvent)


class PairEconomics(Subscriber):

    def __init__(self, contract_address: str, first_token: str, second_token: str, network_provider: NetworkProviders):
        self.contract_address = Address(contract_address)
        self.network_provider = network_provider
        self.pair_data_fetcher = PairContractDataFetcher(self.contract_address, self.network_provider.proxy.url)
        self._get_tokens_reserve_and_total_supply()
        self.fee = 0
        self.report_current_tracking_data()
        self.first_token = first_token
        self.second_token = second_token

    def _get_tokens_reserve_and_total_supply(self):
        reserves_and_total_supply = self.pair_data_fetcher.get_data("getReservesAndTotalSupply")
        if reserves_and_total_supply:
            self.first_token_reserve = reserves_and_total_supply[0]
            self.second_token_reserve = reserves_and_total_supply[1]
            self.total_supply = reserves_and_total_supply[2]
        else:
            self.first_token_reserve = 0
            self.second_token_reserve = 0
            self.total_supply = 0

    def report_current_tracking_data(self):
        print(f'Pair contract address: {self.contract_address.bech32()}')
        print(f'First token reserve: {self.first_token_reserve}')
        print(f'Second token reserve: {self.second_token_reserve}')
        print(f'Total supply: {self.total_supply}')

    def check_add_liquidity(self, event: AddLiquidityEvent):
        old_first_token_reserve = self.first_token_reserve
        old_second_token_reserve = self.second_token_reserve
        old_total_supply = self.total_supply

        self._get_tokens_reserve_and_total_supply()

        new_first_token_reserve = self.first_token_reserve
        new_second_token_reserve = self.second_token_reserve
        new_total_supply = self.total_supply

        if event.tokenA == self.first_token:
            expected_first_token_reserve = old_first_token_reserve + event.amountAmin
            expected_second_token_reserve = old_second_token_reserve + event.amountBmin
        else:
            expected_first_token_reserve = old_first_token_reserve + event.amountBmin
            expected_second_token_reserve = old_second_token_reserve + event.amountAmin

        if old_first_token_reserve >= new_first_token_reserve:
            log_step_fail(f'First token reserve did not increase for pair {self.contract_address.bech32()}')
            log_substep(f'Old first token reserve: {old_first_token_reserve}')
            log_substep(f'New first token reserve: {new_first_token_reserve}')
            log_substep(f'Minimum first token reserve expected: {expected_first_token_reserve}')

        if old_second_token_reserve >= new_second_token_reserve:
            log_step_fail(f'Second token reserve did not increase for pair {self.contract_address.bech32()}')
            log_substep(f'Old second token reserve: {old_second_token_reserve}')
            log_substep(f'New second token reserve: {new_second_token_reserve}')
            log_substep(f'Minimum second token reserve expected: {expected_second_token_reserve}')

        if old_total_supply >= new_total_supply:
            log_step_fail(f'Total supply did not increase for pair {self.contract_address.bech32()}')
            log_substep(f'Old supply: {old_total_supply}')
            log_substep(f'New supply: {new_total_supply}')

        log_step_pass('Checked addLiquidityEvent economics!')

    def check_remove_liquidity(self, event: RemoveLiquidityEvent):
        old_first_token_reserve = self.first_token_reserve
        old_second_token_reserve = self.second_token_reserve
        old_total_supply = self.total_supply

        self._get_tokens_reserve_and_total_supply()

        new_first_token_reserve = self.first_token_reserve
        new_second_token_reserve = self.second_token_reserve
        new_total_supply = self.total_supply

        if event.tokenA == self.first_token:
            expected_first_token_reserve = old_first_token_reserve - event.amountA
            expected_second_token_reserve = old_second_token_reserve - event.amountB
        else:
            expected_first_token_reserve = old_first_token_reserve - event.amountB
            expected_second_token_reserve = old_second_token_reserve - event.amountA

        if old_first_token_reserve <= new_first_token_reserve:
            log_step_fail(f'First token reserve did not decrease for pair {self.contract_address.bech32()}')
            log_substep(f'Old first token reserve: {old_first_token_reserve}')
            log_substep(f'New first token reserve: {new_first_token_reserve}')
            log_substep(f'Maximum first token reserve expected: {expected_first_token_reserve}')

        if old_second_token_reserve <= new_second_token_reserve:
            log_step_fail(f'Second token reserve did not decrease for pair {self.contract_address.bech32()}')
            log_substep(f'Old second token reserve: {old_second_token_reserve}')
            log_substep(f'New second token reserve: {new_second_token_reserve}')
            log_substep(f'Maximum second token reserve expected: {expected_second_token_reserve}')

        if old_total_supply <= new_total_supply:
            log_step_fail(f'Total supply did not decrease for pair {self.contract_address.bech32()}')
            log_substep(f'Old supply: {old_total_supply}')
            log_substep(f'New supply: {new_total_supply}')

        log_step_pass('Checked removeLiquidityEvent economics!')

    def check_swap_fixed_input(self, event: SwapFixedInputEvent):
        old_first_token_reserve = self.first_token_reserve
        old_second_token_reserve = self.second_token_reserve

        self._get_tokens_reserve_and_total_supply()

        new_first_token_reserve = self.first_token_reserve
        new_second_token_reserve = self.second_token_reserve

        if event.tokenA == self.first_token:
            expected_first_token_reserve = old_first_token_reserve + event.amountA
            expected_second_token_reserve = old_second_token_reserve - event.amountBmin

            if old_first_token_reserve >= new_first_token_reserve:
                log_step_fail(f'First token reserve did not increase for pair {self.contract_address.bech32()}')
                log_substep(f'Old first token reserve: {old_first_token_reserve}')
                log_substep(f'New first token reserve: {new_first_token_reserve}')
                log_substep(f'Expected first token reserve: {expected_first_token_reserve}')

            if old_second_token_reserve <= new_second_token_reserve:
                log_step_fail(f'Second token reserve did not decrease for pair {self.contract_address.bech32()}')
                log_substep(f'Old second token reserve: {old_second_token_reserve}')
                log_substep(f'New second token reserve: {new_second_token_reserve}')
                log_substep(f'Maximum expected second token reserve: {expected_second_token_reserve}')
        else:
            expected_first_token_reserve = old_first_token_reserve - event.amountBmin
            expected_second_token_reserve = old_second_token_reserve + event.amountA

            if old_first_token_reserve <= new_first_token_reserve:
                log_step_fail(f'First token reserve did not decrease for pair {self.contract_address.bech32()}')
                log_substep(f'Old first token reserve: {old_first_token_reserve}')
                log_substep(f'New first token reserve: {new_first_token_reserve}')
                log_substep(f'Expected first token reserve: {expected_first_token_reserve}')

            if old_second_token_reserve >= new_second_token_reserve:
                log_step_fail(f'Second token reserve did not increase for pair {self.contract_address.bech32()}')
                log_substep(f'Old second token reserve: {old_second_token_reserve}')
                log_substep(f'New second token reserve: {new_second_token_reserve}')
                log_substep(f'Maximum expected second token reserve: {expected_second_token_reserve}')

        log_step_pass(f'Checked swapFixedInputEvent economics')

    def check_swap_fixed_output(self, event: SwapFixedOutputEvent):
        old_first_token_reserve = self.first_token_reserve
        old_second_token_reserve = self.second_token_reserve

        self._get_tokens_reserve_and_total_supply()

        new_first_token_reserve = self.first_token_reserve
        new_second_token_reserve = self.second_token_reserve

        if event.tokenA == self.first_token:
            expected_first_token_reserve = old_first_token_reserve + event.amountAmax
            expected_second_token_reserve = old_second_token_reserve - event.amountB

            if old_first_token_reserve >= new_first_token_reserve:
                log_step_fail(f'First token reserve did not increase for pair {self.contract_address.bech32()}')
                log_substep(f'Old first token reserve: {old_first_token_reserve}')
                log_substep(f'New first token reserve: {new_first_token_reserve}')
                log_substep(f'Maximum expected first token reserve: {expected_first_token_reserve}')

            if old_second_token_reserve <= new_second_token_reserve:
                log_step_fail(f'Second token reserve did not decrease for pair {self.contract_address.bech32()}')
                log_substep(f'Old second token reserve: {old_second_token_reserve}')
                log_substep(f'New second token reserve: {new_second_token_reserve}')
                log_substep(f'Expected second token reserve: {expected_second_token_reserve}')
        else:
            expected_first_token_reserve = old_first_token_reserve - event.amountB
            expected_second_token_reserve = old_second_token_reserve + event.amountAmax

            if old_first_token_reserve <= new_first_token_reserve:
                log_step_fail(f'First token reserve did not decrease for pair {self.contract_address.bech32()}')
                log_substep(f'Old first token reserve: {old_first_token_reserve}')
                log_substep(f'New first token reserve: {new_first_token_reserve}')
                log_substep(f'Maximum expected first token reserve: {expected_first_token_reserve}')

            if old_second_token_reserve >= new_second_token_reserve:
                log_step_fail(f'Second token reserve did not increase for pair {self.contract_address.bech32()}')
                log_substep(f'Old second token reserve: {old_second_token_reserve}')
                log_substep(f'New second token reserve: {new_second_token_reserve}')
                log_substep(f'Expected second token reserve: {expected_second_token_reserve}')

        log_step_pass(f'Checked swapFixedOutputEvent economics')

    def update(self, publisher: Observable):
        if publisher.contract is not None:
            if self.contract_address.bech32() == publisher.contract.address:
                if publisher.tx_hash:
                    self.network_provider.wait_for_tx_executed(publisher.tx_hash)
                if type(publisher.event) == AddLiquidityEvent:
                    self.check_add_liquidity(publisher.event)
                elif type(publisher.event) == RemoveLiquidityEvent:
                    self.check_remove_liquidity(publisher.event)
                elif type(publisher.event) == SwapFixedInputEvent:
                    self.check_swap_fixed_input(publisher.event)
                elif type(publisher.event) == SwapFixedOutputEvent:
                    self.check_swap_fixed_output(publisher.event)
                elif type(publisher.event) == SetCorrectReservesEvent:
                    self._get_tokens_reserve_and_total_supply()
