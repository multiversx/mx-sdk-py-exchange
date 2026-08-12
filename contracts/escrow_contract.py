from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.utils_chain import Account, WrapperAddress as Address
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_unexpected_args

logger = get_logger(__name__)

# The contract's three endpoints, one declaration each: what the call is for, what it costs, what
# the contract calls it, and the fewest arguments it accepts. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature and the
# argument documentation its callers depend on.
#
# `_WITHDRAW` goes out through the transfer dispatcher while carrying nothing to transfer: its one
# argument is the sender being withdrawn from, which the dispatcher reads as the token list. Its two
# neighbours divide the other way — locking sends tokens, cancelling sends none and says so.
_LOCK_FUNDS = _Endpoint("lock tokens", 60000000, "lockFunds", at_least=2, transfers=True)
_WITHDRAW = _Endpoint("withdraw tokens", 10000000, "withdraw", at_least=1, transfers=True)
_CANCEL_TRANSFER = _Endpoint("cancel transfer", 10000000, "cancelTransfer", at_least=2)


class EscrowContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
            type[str]: energy factory address
            type[str]: locked token ID
            type[int]: minimum locked epochs
            type[int]: epochs cooldown duration
        """
        function_purpose = "Deploy escrow contract"
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
        """ Expected as args: []
        """
        function_purpose = f"upgrade {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            arguments = []

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                                        bytecode_path, metadata, arguments)

        return tx_hash
    
    def lock_funds(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[address]: destination address
        """
        return self._call_endpoint(_LOCK_FUNDS, user, proxy, args)

    def withdraw(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: sender address
        """
        return self._call_endpoint(_WITHDRAW, user, proxy, args)

    def cancel_transfer(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[address]: sender address
            type[address]: receiver address
        """
        return self._call_endpoint(_CANCEL_TRANSFER, user, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed escrow contract: {self.address}")
