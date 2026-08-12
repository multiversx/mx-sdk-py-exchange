from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.logger import get_logger
from utils.utils_tx import deploy, ESDTToken
from utils.utils_generic import log_step_pass
from utils.utils_chain import Account
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)

# The contract's four endpoints, one declaration each. This contract exists to relay a call to
# another one, so none of the four counts or converts what it was handed — everything past the call
# type is the remote endpoint's business, not this one's. All four cost the same 100M.
#
# `_CALL_ENDPOINT` names no `value`: the EGLD it forwards is an argument of the wrapper, so it rides
# on `_call_endpoint` rather than on the declaration.
_CALL_ENDPOINT = _Endpoint("Call endpoint", 100000000, "callEndpoint")
_CALL_INTERNAL_TRANSFER_ENDPOINT = _Endpoint("Call internal transfer endpoint", 100000000,
                                             "callInternalTransferEndpoint")
_CALL_TRANSFER_ENDPOINT = _Endpoint("Call transfer endpoint", 100000000, "callTransferEndpoint",
                                    transfers=True)
_CALL_HYBRID_TRANSFER_ENDPOINT = _Endpoint("Call hybrid transfer endpoint", 100000000,
                                           "callHybridTransferEndpoint", transfers=True)


class DummyProxyContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        return DummyProxyContract(address=address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list = None):
        """ Expected as args:
        """
        function_purpose = f"deploy {type(self).__name__} contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True, payable=True)
        gas_limit = 50000000

        arguments = []
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def call_endpoint(self, user: Account, proxy: ProxyNetworkProvider, amount: int, args: list = None):
        """ 
        Simply calls the specified endpoint on given contract address.
        Expected as args:
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        return self._call_endpoint(_CALL_ENDPOINT, user, proxy, args, value=str(amount))

    def call_internal_transfer_endpoint(self, user: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ 
        Calls the specified endpoint on given contract address while it also transfers user given tokens with the call.
        Expected as args:
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[str]: token id
        type[int]: nonce
        type[int]: amount
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        return self._call_endpoint(_CALL_INTERNAL_TRANSFER_ENDPOINT, user, proxy, args)


    def call_transfer_endpoint(self, user: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ 
        Calls the specified endpoint on given contract address while it also transfers specified tokens owned by the dummy proxy with the call.
        Expected as args:
        type[list[ESDTToken]]: tokens list
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        return self._call_endpoint(_CALL_TRANSFER_ENDPOINT, user, proxy, args)


    def call_hybrid_transfer_endpoint(self, user: Account, proxy: ProxyNetworkProvider, args: list = None):
        """ 
        Calls the specified endpoint on given contract address while it also transfers user given tokens and internally owned tokens with the call.
        Expected as args:
        type[list[ESDTToken]]: tokens list
        type[int]: call type - 0 sync; 1 async; 2 promise; 3 transfer execute
        type[str]: internal token id
        type[int]: internal token nonce
        type[int]: internal token amount
        type[address]: contract address
        type[string]: function name
        type[any..]: function args
        """
        return self._call_endpoint(_CALL_HYBRID_TRANSFER_ENDPOINT, user, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed dummy proxy contract: {self.address}")
