import sys
import traceback
from operator import ne

from contracts.contract_identities import DEXContractInterface, MetaStakingContractIdentity
from events.metastake_events import (EnterMetastakeEvent, ExitMetastakeEvent, ClaimRewardsMetastakeEvent)
from utils.logger import get_logger
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, NetworkProviders, deploy, upgrade_call, \
    endpoint_call, ESDTToken, multi_esdt_endpoint_call
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning, \
    log_unexpected_args

logger = get_logger(__name__)


class MetaStakingContract(DEXContractInterface):
    def __init__(self, staking_token: str, lp_token: str, farm_token: str, stake_token: str,
                 lp_address: str, farm_address: str, stake_address: str,
                 metastake_token: str = "", address: str = ""):
        self.address = address
        self.metastake_token = metastake_token
        self.staking_token = staking_token
        self.lp_token = lp_token
        self.farm_token = farm_token
        self.stake_token = stake_token
        self.lp_address = lp_address
        self.farm_address = farm_address
        self.stake_address = stake_address

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "metastake_token": self.metastake_token,
            "staking_token": self.staking_token,
            "lp_token": self.lp_token,
            "farm_token": self.farm_token,
            "stake_token": self.stake_token,
            "lp_address": self.lp_address,
            "farm_address": self.farm_address,
            "stake_address": self.stake_address
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return MetaStakingContract(address=config_dict['address'],
                                   metastake_token=config_dict['metastake_token'],
                                   staking_token=config_dict['staking_token'],
                                   lp_token=config_dict['lp_token'],
                                   farm_token=config_dict['farm_token'],
                                   stake_token=config_dict['stake_token'],
                                   lp_address=config_dict['lp_address'],
                                   farm_address=config_dict['farm_address'],
                                   stake_address=config_dict['stake_address'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        function_purpose = f"Deploy metastaking contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = [
            Address(self.farm_address),
            Address(self.stake_address),
            Address(self.lp_address),
            self.staking_token,
            self.farm_token,
            self.stake_token,
            self.lp_token,
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path,
                         args: list = [], no_init: bool = False):
        function_purpose = f"Upgrade metastaking contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            arguments = [
                Address(self.farm_address),
                Address(self.stake_address),
                Address(self.lp_address),
                self.staking_token,
                self.farm_token,
                self.stake_token,
                self.lp_token,
            ]
        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, arguments)

    def register_dual_yield_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = f"Register metastaking token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "registerDualYieldToken", sc_args,
                             value="50000000000000000")

    def set_local_roles_dual_yield_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = f"Set local roles for metastake token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = []
        return endpoint_call(proxy, gas_limit, deployer, Address(self.metastake_token),
                             "setLocalRolesDualYieldToken", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        print_test_step_pass(f"Deployed metastaking contract: {self.address}")
        print_test_substep(f"Staking token: {self.staking_token}")
        print_test_substep(f"Stake address: {self.stake_address}")
        print_test_substep(f"Farm address: {self.farm_address}")
        print_test_substep(f"LP address: {self.lp_address}")

    def enter_metastake(self, network_provider: NetworkProviders, user: Account,
                        event: EnterMetastakeEvent, initial: bool = False) -> str:
        # TODO: remove initial parameter by using the event data
        function_purpose = f"enterMetastaking"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        metastake_fn = 'stakeFarmTokens'
        gas_limit = 50000000

        tokens = [ESDTToken(event.metastaking_tk, event.metastaking_tk_nonce, event.metastaking_tk_amount)]
        if not initial:
            tokens.append(ESDTToken(event.metastake_tk, event.metastake_tk_nonce, event.metastake_tk_amount))

        sc_args = [tokens]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), metastake_fn, sc_args)

    def exit_metastake(self, network_provider: NetworkProviders, user: Account, event: ExitMetastakeEvent):
        function_purpose = f"exitMetastaking"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        exit_metastake_fn = 'unstakeFarmTokens'

        tokens = [ESDTToken(self.metastake_token, event.nonce, event.amount)]
        sc_args = [tokens,
                   1,   # first token slippage
                   1    # second token slippage
                   ]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), exit_metastake_fn, sc_args)

    def claim_rewards_metastaking(self, network_provider: NetworkProviders, user: Account, event: ClaimRewardsMetastakeEvent):
        function_purpose = f"claimDualYield"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 50000000
        claim_fn = 'claimDualYield'

        tokens = [ESDTToken(self.metastake_token, event.nonce, event.amount)]

        return multi_esdt_endpoint_call(function_purpose, network_provider.proxy, gas_limit,
                                        user, Address(self.address), claim_fn, tokens)
