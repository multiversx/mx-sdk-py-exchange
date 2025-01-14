import config
from contracts.contract_identities import DEXContractInterface
from utils.logger import get_logger
from utils.utils_tx import deploy, endpoint_call, multi_esdt_endpoint_call, upgrade_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from typing import List, Dict, Any


logger = get_logger(__name__)


class GovernanceContract(DEXContractInterface):
    def __init__(self, fee_token: str = "", address: str = ""):
        self.address = address
        self.fee_token = fee_token

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "fee_token": self.fee_token
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return GovernanceContract(address=config_dict['address'],
                                  fee_token=config_dict['fee_token'])
    
    def get_contract_tokens(self) -> list[str]:
        return []

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = []):
        """ Expected as args:
            type[int]: min_energy_for_propose
            type[int]: min_fee_for_propose
            type[int]: quorum_percentage
            type[int]: votingDelayInBlocks
            type[int]: votingPeriodInBlocks
            type[int]: withdraw_percentage_defeated
            type[str]: energy_factory_address
            type[str]: fees_collector_address
        """
        function_purpose = f"Deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        if len(args) != 8:
            log_unexpected_args(function_purpose, args)
            return ""

        metadata = CodeMetadata(upgradeable=True, payable=False, payable_by_contract=False, readable=True)
        gas_limit = 100000000

        arguments = args[:6] + [Address(args[6]), Address(args[7]), self.fee_token]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = [],
                         no_init: bool = False):
        """ Expected as args:
            type[int]: min_energy_for_propose
            type[int]: min_fee_for_propose
            type[int]: quorum_percentage
            type[int]: votingDelayInBlocks
            type[int]: votingPeriodInBlocks
            type[int]: withdraw_percentage_defeated
            type[str]: energy_factory_address
            type[str]: fees_collector_address
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable=False, payable_by_contract=False, readable=True)
        gas_limit = 100000000
        tx_hash = ""

        if no_init:
            arguments = []
        else:
            if len(args) != 8:
                log_unexpected_args(function_purpose, args)
                return tx_hash

            arguments = args[:6] + [Address(args[6]), Address(args[7]), self.fee_token]

        logger.debug(f"Arguments: {arguments}")

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, arguments)
        return tx_hash

    def propose(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: fee payment
            opt: type[list]: actions ???
        """
        function_purpose = f"propose"
        logger.info(function_purpose)

        gas_limit = 30000000
        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit, user,
                                        Address(self.address), "propose", args)

    def vote(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
            type[int]: VoteType [0 - yes, 1 - no, 2 - no with veto, 3 - abstain]
        """
        function_purpose = f"Vote proposal"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 20000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "vote", sc_args)
    
    def cancel(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
        """
        function_purpose = f"Cancel proposal"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "cancel", sc_args)
    
    def withdraw_deposit(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
        """
        function_purpose = f"Withdraw deposit from proposal"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "withdrawDeposit", sc_args)
    
    def set_voting_period(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: delay in blocks
        """
        function_purpose = f"Change voting period in blocks"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "changeVotingPeriodInBlocks", sc_args)

    def set_voting_delay(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: delay in blocks
        """
        function_purpose = f"Change voting delay in blocks"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "changeVotingDelayInBlocks", sc_args)
    
    def set_quorum_percentage(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: new quorum percentage (10000 = 100%)
        """
        function_purpose = f"Change quorum percentage"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, user, Address(self.address), "changeQuorumPercentage", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed {type(self).__name__} contract: {self.address}")
