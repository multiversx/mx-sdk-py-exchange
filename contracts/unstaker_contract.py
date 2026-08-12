import sys
import traceback

from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import log_step_fail, log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, and what the
# contract calls it. `_call_endpoint` on `DEXContractInterface` does the rest, so each wrapper below
# carries only its signature and the argument documentation its callers depend on.
#
# The two unbond endpoints take nothing and disagree about it: `claim_unlocked_tokens` names `[]`
# explicitly and discards whatever it was handed, `cancel_unbond` forwards its own default — which
# is `None`, not a list. Both preserved as they are.
_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("set energy factory address", 10000000,
                                        "setEnergyFactoryAddress", at_least=1)
_CLAIM_UNLOCKED_TOKENS = _Endpoint("claim unlocked tokens", 20000000, "claimUnlockedTokens")
_CANCEL_UNBOND = _Endpoint("cancel unbond", 20000000, "cancelUnbond")
_SET_FEES_BURN_PERCENTAGE = _Endpoint("set fees burn percentage", 20000000, "setFeesBurnPercentage")


class UnstakerContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        return UnstakerContract(address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[int]: unbond epochs
            type[str]: energy factory address
            type[int]: fees burn percentage
            type[str]: fees collector address
        """
        function_purpose = f"Deploy token unstake contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 4:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = args
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address
    
    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None,
                         no_init: bool = False):
        """ Expected as args:
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            # implement below in case of upgrade args needed
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)

        return tx_hash

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: energy factory address
        """
        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy, args)

    def claim_unlocked_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
            empty
        """
        return self._call_endpoint(_CLAIM_UNLOCKED_TOKENS, deployer, proxy, [])

    def cancel_unbond(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ Expected as args:
            empty
        """
        return self._call_endpoint(_CANCEL_UNBOND, deployer, proxy, args)

    def set_fees_burn_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: fees burn percentage
        """
        return self._call_endpoint(_SET_FEES_BURN_PERCENTAGE, deployer, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed token unstake contract: {self.address}")
