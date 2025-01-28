import sys
import traceback

import config
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders, ESDTToken, \
    multi_esdt_endpoint_call, deploy, endpoint_call
from events.price_discovery_events import (DepositPDLiquidityEvent,
                                           WithdrawPDLiquidityEvent, RedeemPDLPTokensEvent)
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import log_step_fail, log_step_pass, log_substep, log_warning
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class PriceDiscoveryContract(DEXContractInterface):
    def __init__(self,
                 launched_token_id: str,
                 accepted_token_id: str,
                 redeem_token: str,
                 first_redeem_token_nonce: int,
                 second_redeem_token_nonce: int,
                 address: str,
                 locking_sc_address: str,
                 start_block: int,
                 no_limit_phase_duration_blocks: int,
                 linear_penalty_phase_duration_blocks: int,
                 fixed_penalty_phase_duration_blocks: int,
                 unlock_epoch: int,
                 min_launched_token_price: int,
                 min_penalty_percentage: int,
                 max_penalty_percentage: int,
                 fixed_penalty_percentage: int
                 ):
        self.launched_token_id = launched_token_id  # launched token
        self.accepted_token = accepted_token_id  # accepted token
        self.redeem_token = redeem_token
        self.first_redeem_token_nonce = first_redeem_token_nonce  # launched token
        self.second_redeem_token_nonce = second_redeem_token_nonce  # accepted token
        self.address = address
        self.locking_sc_address = locking_sc_address
        self.start_block = start_block
        self.no_limit_phase_duration_blocks = no_limit_phase_duration_blocks
        self.linear_penalty_phase_duration_blocks = linear_penalty_phase_duration_blocks
        self.fixed_penalty_phase_duration_blocks = fixed_penalty_phase_duration_blocks
        self.unlock_epoch = unlock_epoch
        self.min_launched_token_price = min_launched_token_price
        self.min_penalty_percentage = min_penalty_percentage
        self.max_penalty_percentage = max_penalty_percentage
        self.fixed_penalty_percentage = fixed_penalty_percentage

    def get_config_dict(self) -> dict:
        output_dict = {
            "launched_token_id": self.launched_token_id,
            "accepted_token": self.accepted_token,
            "redeem_token": self.redeem_token,
            "first_redeem_token_nonce": self.first_redeem_token_nonce,
            "second_redeem_token_nonce": self.second_redeem_token_nonce,
            "address": self.address,
            "locking_sc_address": self.locking_sc_address,
            "start_block": self.start_block,
            "no_limit_phase_duration_blocks": self.no_limit_phase_duration_blocks,
            "linear_penalty_phase_duration_blocks": self.linear_penalty_phase_duration_blocks,
            "fixed_penalty_phase_duration_blocks": self.fixed_penalty_phase_duration_blocks,
            "unlock_epoch": self.unlock_epoch,
            "min_launched_token_price": self.min_launched_token_price,
            "min_penalty_percentage": self.min_penalty_percentage,
            "max_penalty_percentage": self.max_penalty_percentage,
            "fixed_penalty_percentage": self.fixed_penalty_percentage,
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return PriceDiscoveryContract(launched_token_id=config_dict['launched_token_id'],  # launched token
                                      accepted_token_id=config_dict['accepted_token'],  # accepted token
                                      redeem_token=config_dict['redeem_token'],
                                      first_redeem_token_nonce=config_dict['first_redeem_token_nonce'],
                                      # launched token
                                      second_redeem_token_nonce=config_dict['second_redeem_token_nonce'],
                                      # accepted token
                                      address=config_dict['address'],
                                      locking_sc_address=config_dict['locking_sc_address'],
                                      start_block=config_dict['start_block'],
                                      no_limit_phase_duration_blocks=config_dict['no_limit_phase_duration_blocks'],
                                      linear_penalty_phase_duration_blocks=config_dict[
                                          'linear_penalty_phase_duration_blocks'],
                                      fixed_penalty_phase_duration_blocks=config_dict[
                                          'fixed_penalty_phase_duration_blocks'],
                                      unlock_epoch=config_dict['unlock_epoch'],
                                      min_launched_token_price=config_dict['min_launched_token_price'],
                                      min_penalty_percentage=config_dict['min_penalty_percentage'],
                                      max_penalty_percentage=config_dict['max_penalty_percentage'],
                                      fixed_penalty_percentage=config_dict['fixed_penalty_percentage'])
    
    def get_contract_tokens(self) -> list[str]:
        return [self.redeem_token]

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def deposit_liquidity(self, network_provider: NetworkProviders, user: Account, event: DepositPDLiquidityEvent) -> str:
        function_purpose = f"Deposit Price Discovery liquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")
        logger.debug(f"Token: {event.deposit_token} Amount: {event.amount}")

        gas_limit = 10000000
        tokens = [ESDTToken(event.deposit_token, 0, event.amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "deposit", sc_args)

    def withdraw_liquidity(self, network_provider: NetworkProviders, user: Account, event: WithdrawPDLiquidityEvent) -> str:
        function_purpose = f"Withdraw Price Discovery liquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")
        logger.debug(f"Token: {event.deposit_lp_token} Nonce: {event.nonce} Amount: {event.amount}")

        gas_limit = 10000000
        tokens = [ESDTToken(event.deposit_lp_token, event.nonce, event.amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "withdraw", sc_args)

    def redeem_liquidity_position(self, network_provider: NetworkProviders, user: Account, event: RedeemPDLPTokensEvent) -> str:
        function_purpose = f"Redeem Price Discovery liquidity"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")
        logger.debug(f"Token: {event.deposit_lp_token} Nonce: {event.nonce} Amount: {event.amount}")

        gas_limit = 10000000
        tokens = [ESDTToken(event.deposit_lp_token, event.nonce, event.amount)]
        sc_args = [tokens]
        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit, user,
                                        Address(self.address), "redeem", sc_args)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        function_purpose = f"Deploy price discovery contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True)
        network_config = proxy.get_network_config()
        gas_limit = 350000000

        arguments = [
            self.launched_token_id,  # launched token id
            self.accepted_token,  # accepted token id
            18,  # launched token decimals
            self.min_launched_token_price,
            self.start_block,
            self.no_limit_phase_duration_blocks,
            self.linear_penalty_phase_duration_blocks,
            self.fixed_penalty_phase_duration_blocks,
            self.unlock_epoch,
            self.min_penalty_percentage,
            self.max_penalty_percentage,
            self.fixed_penalty_percentage,
            Address(self.locking_sc_address)  # locking sc address
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def issue_redeem_token(self, deployer: Account, proxy: ProxyNetworkProvider, redeem_token_ticker: str):
        """ Expected as args:
        type[str]: lp token name
        type[str]: lp token ticker
        """
        function_purpose = f"Issue price discovery redeem token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            redeem_token_ticker,
            redeem_token_ticker,
            18,
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueRedeemToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def create_initial_redeem_tokens(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Create initial redeem tokens for price discovery contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "createInitialRedeemTokens", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed price discovery contract: {self.address}")
        log_substep(f"Redeem token: {self.redeem_token}")
