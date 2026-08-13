from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.contract_data_fetchers import PermissionsHubContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy
from utils.utils_chain import log_explorer_transaction
from utils.utils_generic import log_step_fail, log_step_pass
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from multiversx_sdk.abi import AddressValue

logger = get_logger(__name__)

# The contract's four endpoints, one declaration each: two lists in and two lists out, at the same
# 30M gas, each requiring at least one address and sending them all as the bech32 text they arrived
# as. The flattest table in `contracts/` — the only thing separating the four is what they are
# called and what they announce.
_WHITELIST = _Endpoint("Add addresses to whitelist", 30000000, "whitelist", at_least=1)
_REMOVE_WHITELIST = _Endpoint("Remove addresses to whitelist", 30000000, "removeWhitelist",
                              at_least=1)
_BLACKLIST = _Endpoint("Add addresses to blacklist", 30000000, "blacklist", at_least=1)
_REMOVE_BLACKLIST = _Endpoint("Remove addresses from blacklist", 30000000, "removeBlacklist",
                              at_least=1)


class PermissionsHubContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
    )

    def __init__(self, address: str = ""):
        self.address = address

    @classmethod
    def load_contract_by_address(cls, address: str):
        return PermissionsHubContract(address)

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        """
        function_purpose = f"Deploy permissions hub contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        arguments = args
        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def add_to_whitelist(self, user: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - whitelisted_sc_addresses: list[address]
        """
        return self._call_endpoint(_WHITELIST, user, proxy, args)

    def remove_from_whitelist(self, user: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - whitelisted_sc_addresses: list[address]
        """
        return self._call_endpoint(_REMOVE_WHITELIST, user, proxy, args)

    def add_to_blacklist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - blacklisted_sc_addresses: list[address]
        """
        return self._call_endpoint(_BLACKLIST, deployer, proxy, args)

    def remove_from_blacklist(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """Expecting as args:
        - blacklisted_sc_addresses: list[address]
        """
        return self._call_endpoint(_REMOVE_BLACKLIST, deployer, proxy, args)


    def is_whitelisted(self, user: str, address: str, proxy: ProxyNetworkProvider) -> int:
        return self._query_view(proxy, PermissionsHubContractDataFetcher, 'isWhitelisted',
                                [
                                    AddressValue.new_from_address(Address(address)),
                                    AddressValue.new_from_address(Address(user))
                                ])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed permissions hub contract: {self.address}")
