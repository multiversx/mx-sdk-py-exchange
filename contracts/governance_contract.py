import config
from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes, hex_to_string
from utils import decoding_structures
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from typing import List, Dict, Any


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and how many arguments it requires. `_call_endpoint` on `DEXContractInterface`
# does the rest, so each wrapper below carries only its signature and the argument documentation its
# callers depend on.
#
# The most uniform table in `contracts/`: six of the seven take a proposal id or a setting and send
# it exactly as given, and the five settings all cost 10M. Only `propose` — which pays its fee in
# tokens — differs in shape at all.
_PROPOSE = _Endpoint("propose", 30000000, "propose", transfers=True)
_VOTE = _Endpoint("Vote proposal", 20000000, "vote", exactly=2)
_CANCEL = _Endpoint("Cancel proposal", 10000000, "cancel", exactly=1)
_WITHDRAW_DEPOSIT = _Endpoint("Withdraw deposit from proposal", 10000000, "withdrawDeposit",
                              exactly=1)
_CHANGE_VOTING_PERIOD = _Endpoint("Change voting period in blocks", 10000000,
                                  "changeVotingPeriodInBlocks", exactly=1)
_CHANGE_VOTING_DELAY = _Endpoint("Change voting delay in blocks", 10000000,
                                 "changeVotingDelayInBlocks", exactly=1)
_CHANGE_QUORUM_PERCENTAGE = _Endpoint("Change quorum percentage", 10000000,
                                      "changeQuorumPercentage", exactly=1)


class GovernanceContract(DEXContractInterface):
    # `fee_token` is the token proposals are paid in, not one this contract issues, so it is
    # persisted but absent from `_CONTRACT_TOKENS`.
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("fee_token"),
    )

    def __init__(self, fee_token: str = "", address: str = ""):
        self.address = address
        self.fee_token = fee_token

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
        return self._call_endpoint(_PROPOSE, user, proxy, args)

    def vote(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
            type[int]: VoteType [0 - yes, 1 - no, 2 - no with veto, 3 - abstain]
        """
        return self._call_endpoint(_VOTE, deployer, proxy, args)

    def cancel(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
        """
        return self._call_endpoint(_CANCEL, deployer, proxy, args)

    def withdraw_deposit(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: proposal id
        """
        return self._call_endpoint(_WITHDRAW_DEPOSIT, user, proxy, args)

    def set_voting_period(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: delay in blocks
        """
        return self._call_endpoint(_CHANGE_VOTING_PERIOD, user, proxy, args)

    def set_voting_delay(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: delay in blocks
        """
        return self._call_endpoint(_CHANGE_VOTING_DELAY, user, proxy, args)

    def set_quorum_percentage(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: new quorum percentage (10000 = 100%)
        """
        return self._call_endpoint(_CHANGE_QUORUM_PERCENTAGE, user, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed {type(self).__name__} contract: {self.address}")
