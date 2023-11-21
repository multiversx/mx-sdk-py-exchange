from typing import Dict
from multiversx_sdk_core import Address
from utils.contract_data_fetchers import PriceDiscoveryContractDataFetcher
from events.price_discovery_events import DepositPDLiquidityEvent, WithdrawPDLiquidityEvent, \
    RedeemPDLPTokensEvent
from contracts.contract_identities import PriceDiscoveryContractIdentity
from utils.utils_chain import get_all_token_nonces_details_for_account, get_token_details_for_address
from utils.utils_generic import log_step_fail, log_step_pass, log_substep
from multiversx_sdk_network_providers.proxy_network_provider import ProxyNetworkProvider


class PriceDiscoveryAccountEconomics:
    def __init__(self, address: Address):
        self.address = address
        self.first_token_deposited = 0
        self.second_token_deposited = 0
        self.first_redeem_tokens_owned = 0
        self.second_redeem_tokens_owned = 0
        self.lp_tokens_redeemed = 0

        # these can be retrieved at init to compare against them afterwards
        # e.g. first_token_owned_init - first_token_deposited == current account balance on first token
        self.first_token_owned_init = 0
        self.second_token_owned_init = 0


class PriceDiscoveryEconomics:
    def __init__(self, contract_identity: PriceDiscoveryContractIdentity, proxy_url: str):
        self.proxy = ProxyNetworkProvider(proxy_url)
        self.pd_contract_identity = contract_identity
        self.contract_data_fetcher = PriceDiscoveryContractDataFetcher(Address(contract_identity.address, "erd"), proxy_url)

        self.first_token_reserve = 0
        self.second_token_reserve = 0
        self.first_redeem_tokens_reserve = 0
        self.second_redeem_tokens_reserve = 0
        self.lp_tokens_reserve = 0
        # after sending tokens to pool, this will be equal to lp_tokens_reserve. Will be kept fixed for calculations.
        self.total_lp_tokens_received = 0
        # after sending tokens to pool, these will be kept fixed as final token reserves for further calculations of LPs
        self.final_first_token_reserve = 0
        self.final_second_token_reserve = 0

        self.account_tracker: Dict[str, PriceDiscoveryAccountEconomics] = {}

    def __check_deposit_event(self, event: DepositPDLiquidityEvent):
        chain_first_token_reserve = self.contract_data_fetcher.get_token_reserve(self.pd_contract_identity.launched_token_id)
        chain_second_token_reserve = self.contract_data_fetcher.get_token_reserve(self.pd_contract_identity.accepted_token)

        if event.deposit_token == self.pd_contract_identity.launched_token_id:
            new_first_token_reserve = self.first_token_reserve + event.amount
            new_second_token_reserve = self.second_token_reserve
        else:
            new_first_token_reserve = self.first_token_reserve
            new_second_token_reserve = self.second_token_reserve + event.amount

        if chain_first_token_reserve != new_first_token_reserve:
            log_step_fail("TEST CHECK FAIL: First token reserve not as expected!")
            log_substep(f"Chain first token reserve: {chain_first_token_reserve}")
            log_substep(f"Expected first token reserve: {new_first_token_reserve}")

        if chain_second_token_reserve != new_second_token_reserve:
            log_step_fail("TEST CHECK FAIL: Second token reserve not as expected!")
            log_substep(f"Chain second token reserve: {chain_second_token_reserve}")
            log_substep(f"Expected second token reserve: {new_second_token_reserve}")

        log_step_pass("Checked deposit event data!")

    def __deposit_event_account_tracking(self, event: DepositPDLiquidityEvent, user_address: Address):
        if user_address.bech32() not in self.account_tracker.keys():
            self.account_tracker[user_address.bech32()] = PriceDiscoveryAccountEconomics(user_address)

        # TODO: check first/second_token_deposited conformity starting from an account init
        if event.deposit_token == self.pd_contract_identity.launched_token_id:
            self.account_tracker[user_address.bech32()].first_token_deposited += event.amount
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned + event.amount
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned
        else:
            self.account_tracker[user_address.bech32()].second_token_deposited += event.amount
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned + event.amount

        chain_tokens_on_account = get_all_token_nonces_details_for_account(self.pd_contract_identity.redeem_token,
                                                                           user_address.bech32(),
                                                                           self.proxy
                                                                           )
        # check for redeem tokens conformity
        first_redeem_token_found = False
        second_redeem_token_found = False
        chain_first_redeem_tokens = 0
        chain_second_redeem_tokens = 0
        for chain_token in chain_tokens_on_account:
            if chain_token['nonce'] == self.pd_contract_identity.first_redeem_token_nonce:
                chain_first_redeem_tokens = int(chain_token['balance'])
                if chain_first_redeem_tokens != exp_first_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
                    log_substep(f"Chain first redeem tokens: {chain_first_redeem_tokens}")
                    log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
                    first_redeem_token_found = True
            if chain_token['nonce'] == self.pd_contract_identity.second_redeem_token_nonce:
                chain_second_redeem_tokens = int(chain_token['balance'])
                if chain_second_redeem_tokens != exp_second_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
                    log_substep(f"Chain second redeem tokens: {chain_second_redeem_tokens}")
                    log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")
                    second_redeem_token_found = True

        if not first_redeem_token_found and exp_first_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
            log_substep(f"Chain first redeem tokens: 0")
            log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
        if not second_redeem_token_found and exp_second_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
            log_substep(f"Chain second redeem tokens: 0")
            log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")


        # update redeem tokens data on account
        self.account_tracker[user_address.bech32()].first_redeem_tokens_owned = chain_first_redeem_tokens
        self.account_tracker[user_address.bech32()].second_redeem_tokens_owned = chain_second_redeem_tokens

        log_step_pass("Tracked and checked deposit account data!")

    def deposit_event_tracking(self, event: DepositPDLiquidityEvent, user_address: Address, tx_hash: str):
        # TODO: check state based on tx_hash success
        self.__check_deposit_event(event)
        self.__deposit_event_account_tracking(event, user_address)

        if event.deposit_token == self.pd_contract_identity.launched_token_id:
            self.first_token_reserve += event.amount
            self.first_redeem_tokens_reserve += event.amount
        else:
            self.second_token_reserve += event.amount
            self.second_redeem_tokens_reserve += event.amount

        log_step_pass("Tracked deposit data!")

    def __check_withdraw_event(self, event: WithdrawPDLiquidityEvent):
        chain_first_token_reserve = self.contract_data_fetcher.get_token_reserve(self.pd_contract_identity.launched_token_id)
        chain_second_token_reserve = self.contract_data_fetcher.get_token_reserve(self.pd_contract_identity.accepted_token)

        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            new_first_token_reserve = self.first_token_reserve - event.amount
            new_second_token_reserve = self.second_token_reserve
        else:
            new_first_token_reserve = self.first_token_reserve
            new_second_token_reserve = self.second_token_reserve - event.amount

        if chain_first_token_reserve != new_first_token_reserve:
            log_step_fail("TEST CHECK FAIL: First token reserve not as expected!")
            log_substep(f"Chain first token reserve: {chain_first_token_reserve}")
            log_substep(f"Expected first token reserve: {new_first_token_reserve}")

        if chain_second_token_reserve != new_second_token_reserve:
            log_step_fail("TEST CHECK FAIL: Second token reserve not as expected!")
            log_substep(f"Chain second token reserve: {chain_second_token_reserve}")
            log_substep(f"Expected second token reserve: {new_second_token_reserve}")

        log_step_pass("Checked withdraw event data!")

    def __withdraw_event_account_tracking(self, event: WithdrawPDLiquidityEvent, user_address: Address):
        if user_address.bech32() not in self.account_tracker.keys():
            self.account_tracker[user_address.bech32()] = PriceDiscoveryAccountEconomics(user_address)

        # TODO: check first/second_token_deposited conformity starting from an account init
        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            self.account_tracker[user_address.bech32()].first_token_deposited -= event.amount
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned - event.amount
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned
        else:
            self.account_tracker[user_address.bech32()].second_token_deposited -= event.amount
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned - event.amount

        chain_tokens_on_account = get_all_token_nonces_details_for_account(self.pd_contract_identity.redeem_token,
                                                                           user_address.bech32(),
                                                                           self.proxy
                                                                           )
        # check for redeem tokens match
        first_redeem_token_found = False
        second_redeem_token_found = False
        chain_first_redeem_tokens = 0
        chain_second_redeem_tokens = 0
        for chain_token in chain_tokens_on_account:
            if chain_token['nonce'] == self.pd_contract_identity.first_redeem_token_nonce:
                chain_first_redeem_tokens = int(chain_token['balance'])
                if chain_first_redeem_tokens != exp_first_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
                    log_substep(f"Chain first redeem tokens: {chain_first_redeem_tokens}")
                    log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
                    first_redeem_token_found = True
            if chain_token['nonce'] == self.pd_contract_identity.second_redeem_token_nonce:
                chain_second_redeem_tokens = int(chain_token['balance'])
                if chain_second_redeem_tokens != exp_second_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
                    log_substep(f"Chain second redeem tokens: {chain_second_redeem_tokens}")
                    log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")
                    second_redeem_token_found = True

        if not first_redeem_token_found and exp_first_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
            log_substep(f"Chain first redeem tokens: 0")
            log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
        if not second_redeem_token_found and exp_second_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
            log_substep(f"Chain second redeem tokens: 0")
            log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")


        # update redeem tokens data on account
        self.account_tracker[user_address.bech32()].first_redeem_tokens_owned = chain_first_redeem_tokens
        self.account_tracker[user_address.bech32()].second_redeem_tokens_owned = chain_second_redeem_tokens

        log_step_pass("Tracked and checked withdraw account data!")

    def withdraw_event_tracking(self, event: WithdrawPDLiquidityEvent, user_address: Address, tx_hash: str):
        # TODO: check state based on tx_hash success
        self.__check_withdraw_event(event)
        self.__withdraw_event_account_tracking(event, user_address)

        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            self.first_token_reserve -= event.amount
            self.first_redeem_tokens_reserve -= event.amount
        else:
            self.second_token_reserve -= event.amount
            self.second_redeem_tokens_reserve -= event.amount

    # TODO: method to check deposit of initial liquidity and amount of LPs received

    def __get_exp_lp_tokens_redeemed(self, redeem_tk_amount: int, final_token_reserve: int) -> int:
        exp_lp_tokens_redeemed = redeem_tk_amount * self.total_lp_tokens_received // final_token_reserve // 2
        return exp_lp_tokens_redeemed

    def __check_redeem_event(self, event: RedeemPDLPTokensEvent):
        chain_lp_tokens_reserve = self.contract_data_fetcher.get_token_reserve(self.pd_contract_identity.lp_token)

        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            exp_lp_tokens_reserve = self.lp_tokens_reserve - \
                                    self.__get_exp_lp_tokens_redeemed(event.amount, self.final_first_token_reserve)
        else:
            exp_lp_tokens_reserve = self.lp_tokens_reserve - \
                                    self.__get_exp_lp_tokens_redeemed(event.amount, self.second_redeem_tokens_reserve)

        if chain_lp_tokens_reserve != exp_lp_tokens_reserve:
            log_step_fail("TEST CHECK FAIL: LP tokens reserve not as expected!")
            log_substep(f"Chain LP tokens reserve: {chain_lp_tokens_reserve}")
            log_substep(f"Expected LP tokens reserve: {exp_lp_tokens_reserve}")

        # update LP tokens tracking data
        self.lp_tokens_reserve = chain_lp_tokens_reserve

        log_step_pass("Checked redeem event data!")

    def __redeem_event_account_tracking(self, event: RedeemPDLPTokensEvent, user_address: Address):
        if user_address.bech32() not in self.account_tracker.keys():
            self.account_tracker[user_address.bech32()] = PriceDiscoveryAccountEconomics(user_address)

        # TODO: check first/second_token_deposited conformity starting from an account init
        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned - event.amount
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned
            exp_lp_tokens_owned = self.account_tracker[user_address.bech32()].lp_tokens_redeemed + \
                                  self.__get_exp_lp_tokens_redeemed(event.amount, self.final_first_token_reserve)
        else:
            exp_first_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].first_redeem_tokens_owned
            exp_second_redeem_tokens_owned = self.account_tracker[
                                                user_address.bech32()].second_redeem_tokens_owned - event.amount
            exp_lp_tokens_owned = self.account_tracker[user_address.bech32()].lp_tokens_redeemed + \
                                  self.__get_exp_lp_tokens_redeemed(event.amount, self.second_redeem_tokens_reserve)

        chain_redeem_tokens_on_account = get_all_token_nonces_details_for_account(self.pd_contract_identity.redeem_token,
                                                                           user_address.bech32(),
                                                                           self.proxy
                                                                           )
        _, chain_lp_tokens_on_account, _ = get_token_details_for_address(self.pd_contract_identity.lp_token,
                                                                   user_address.bech32(),
                                                                   self.proxy)

        # check for redeem tokens proper decrease (kinda overkill)
        first_redeem_token_found = False
        second_redeem_token_found = False
        chain_first_redeem_tokens = 0
        chain_second_redeem_tokens = 0
        for chain_token in chain_redeem_tokens_on_account:
            if chain_token['nonce'] == self.pd_contract_identity.first_redeem_token_nonce:
                chain_first_redeem_tokens = int(chain_token['balance'])
                if chain_first_redeem_tokens != exp_first_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
                    log_substep(f"Chain first redeem tokens: {chain_first_redeem_tokens}")
                    log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
                    first_redeem_token_found = True
            if chain_token['nonce'] == self.pd_contract_identity.second_redeem_token_nonce:
                chain_second_redeem_tokens = int(chain_token['balance'])
                if chain_second_redeem_tokens != exp_second_redeem_tokens_owned:
                    log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
                    log_substep(f"Chain second redeem tokens: {chain_second_redeem_tokens}")
                    log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")
                    second_redeem_token_found = True

        if not first_redeem_token_found and exp_first_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: First redeem tokens on account not as expected!")
            log_substep(f"Chain first redeem tokens: 0")
            log_substep(f"Expected first redeem tokens: {exp_first_redeem_tokens_owned}")
        if not second_redeem_token_found and exp_second_redeem_tokens_owned > 0:
            log_step_fail("TEST CHECK FAIL: Second redeem tokens on account not as expected!")
            log_substep(f"Chain second redeem tokens: 0")
            log_substep(f"Expected second redeem tokens: {exp_second_redeem_tokens_owned}")

        # check for lp tokens retrieved - the real deal
        if chain_lp_tokens_on_account != exp_lp_tokens_owned:
            log_step_fail("TEST CHECK FAIL: LP tokens on account not as expected!")
            log_substep(f"Chain LP tokens on account: {chain_lp_tokens_on_account}")
            log_substep(f"Expected LP on account: {exp_lp_tokens_owned}")

        # update redeem tokens data on account
        self.account_tracker[user_address.bech32()].first_redeem_tokens_owned = chain_first_redeem_tokens
        self.account_tracker[user_address.bech32()].second_redeem_tokens_owned = chain_second_redeem_tokens
        self.account_tracker[user_address.bech32()].lp_tokens_redeemed = chain_lp_tokens_on_account

        log_step_pass("Tracked and checked redeem account data!")

    def redeem_event_tracking(self, event: RedeemPDLPTokensEvent, user_address: Address, tx_hash: str):
        # TODO: check state based on tx_hash success
        self.__check_redeem_event(event)
        self.__redeem_event_account_tracking(event, user_address)

        if event.nonce == self.pd_contract_identity.first_redeem_token_nonce:
            self.first_redeem_tokens_reserve -= event.amount
        else:
            self.second_redeem_tokens_reserve -= event.amount
