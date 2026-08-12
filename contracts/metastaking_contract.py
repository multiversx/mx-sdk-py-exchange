from typing import Any, Dict, List, Tuple, override
from contracts.contract_identities import (DEXContractInterface, MetaStakingContractVersion,
                                           _as_addresses, _ConfigField, _Endpoint)
from contracts.base_contracts import BaseSCWhitelistContract, BasePermissionsHubContract
from utils.contract_data_fetchers import MetaStakingContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call
from utils.utils_chain import Account, WrapperAddress as Address, base64_to_hex, decode_merged_attributes, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider, Token
from utils.utils_generic import log_step_pass, log_substep
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES, METASTAKE_TOKEN_ATTRIBUTES, STAKE_V2_TOKEN_ATTRIBUTES, STAKE_V1_TOKEN_ATTRIBUTES
import config


logger = get_logger(__name__)

# The contract's endpoints, one declaration each: what the call is for, what it costs, what the
# contract calls it, and what it makes of the arguments it is handed. `_call_endpoint` on
# `DEXContractInterface` does the rest, so each wrapper below carries only its signature, the debug
# line naming who signed, and the argument documentation its callers depend on.
#
# ⚠️ `_SET_LOCAL_ROLES_DUAL_YIELD_TOKEN` is the only endpoint in `contracts/` addressed to anything
# but its own contract: `on` names the metastake token, and a token identifier is not a bech32
# address, so every call to it raises. Preserved as it behaves — see docs/CLEANUP.md.
_REGISTER_DUAL_YIELD_TOKEN = _Endpoint("Register metastaking token", 100000000,
                                       "registerDualYieldToken", exactly=2, refuses=False,
                                       build=lambda args: [args[0], args[1], 18],
                                       value="50000000000000000")
_SET_LOCAL_ROLES_DUAL_YIELD_TOKEN = _Endpoint("Set local roles for metastake token", 100000000,
                                              "setLocalRolesDualYieldToken", on="metastake_token")
_WHITELIST_CONTRACT = _Endpoint("Whitelist contract in metastaking", 50000000,
                                "addSCAddressToWhitelist", build=_as_addresses)

# The five that move a user's tokens. Each names itself after the endpoint it calls rather than
# describing it, which is what makes their purposes camelCase where the three above are prose.
_ENTER_METASTAKE = _Endpoint("enterMetastaking", 70000000, "stakeFarmTokens", transfers=True)
_ENTER_METASTAKE_ON_BEHALF = _Endpoint("enterMetastakingOnBehalf", 70000000, "stakeFarmOnBehalf",
                                       transfers=True)
_EXIT_METASTAKE = _Endpoint("exitMetastaking", 90000000, "unstakeFarmTokens", transfers=True)
_CLAIM_REWARDS_METASTAKING = _Endpoint("claimDualYield", 70000000, "claimDualYield", transfers=True)
_CLAIM_REWARDS_ON_BEHALF_METASTAKING = _Endpoint("claimDualYieldOnBehalf", 70000000,
                                                 "claimDualYieldOnBehalf", transfers=True)

_SET_ENERGY_FACTORY_ADDRESS = _Endpoint("Set energy factory address in proxy staking contract",
                                        50000000, "setEnergyFactoryAddress", rejects_empty=True)


class MetaStakingContract(BaseSCWhitelistContract, BasePermissionsHubContract):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("metastake_token"),
        _ConfigField("staking_token"),
        _ConfigField("lp_token"),
        _ConfigField("farm_token"),
        _ConfigField("stake_token"),
        _ConfigField("lp_address"),
        _ConfigField("farm_address"),
        _ConfigField("stake_address"),
        _ConfigField("version", enum=MetaStakingContractVersion),
    )
    _CONTRACT_TOKENS = ("metastake_token",)

    def __init__(self, staking_token: str, lp_token: str, farm_token: str, stake_token: str,
                 lp_address: str, farm_address: str, stake_address: str,
                 version: MetaStakingContractVersion, metastake_token: str = "", address: str = ""):
        self.address = address
        self.metastake_token = metastake_token
        self.staking_token = staking_token
        self.lp_token = lp_token
        self.farm_token = farm_token
        self.stake_token = stake_token
        self.lp_address = lp_address
        self.farm_address = farm_address
        self.stake_address = stake_address
        self.version = version

    @classmethod
    def load_contract_by_address(cls, address: str, version=MetaStakingContractVersion.V3Boosted):
        data_fetcher = MetaStakingContractDataFetcher(Address(address), config.DEFAULT_PROXY)

        staking_token = hex_to_string(data_fetcher.get_data("getStakingTokenId"))
        lp_token = hex_to_string(data_fetcher.get_data("getLpTokenId"))
        farm_token = hex_to_string(data_fetcher.get_data("getLpFarmTokenId"))
        stake_token = hex_to_string(data_fetcher.get_data("getFarmTokenId"))
        lp_address = Address.from_hex(data_fetcher.get_data("getPairAddress")).bech32()
        farm_address = Address.from_hex(data_fetcher.get_data("getLpFarmAddress")).bech32()
        stake_address = Address.from_hex(data_fetcher.get_data("getStakingFarmAddress")).bech32()
        metastake_token = hex_to_string(data_fetcher.get_data("getDualYieldTokenId"))

        return MetaStakingContract(
            staking_token,
            lp_token,
            farm_token,
            stake_token,
            lp_address,
            farm_address,
            stake_address,
            version,
            metastake_token,
            address
        )

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
        if self.version == MetaStakingContractVersion.V3Boosted:
            arguments.insert(0, Address(args[0]))

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
            # implement below if arguments for upgrade are needed
            arguments = []

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, arguments)

    def register_dual_yield_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        return self._call_endpoint(_REGISTER_DUAL_YIELD_TOKEN, deployer, proxy, args)

    def set_local_roles_dual_yield_token(self, deployer: Account, proxy: ProxyNetworkProvider):
        return self._call_endpoint(_SET_LOCAL_ROLES_DUAL_YIELD_TOKEN, deployer, proxy, [])

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        return self._call_endpoint(_WHITELIST_CONTRACT, deployer, proxy, [contract_to_whitelist])

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed metastaking contract: {self.address}")
        log_substep(f"Staking token: {self.staking_token}")
        log_substep(f"Metastake token: {self.metastake_token}")
        log_substep(f"Stake address: {self.stake_address}")
        log_substep(f"Farm address: {self.farm_address}")
        log_substep(f"LP address: {self.lp_address}")

    def enter_metastake(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]) -> str:
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            optional: type[str]: original caller
        """
        logger.debug(f"Account: {user.address}")
        return self._call_endpoint(_ENTER_METASTAKE, user, proxy, args)

    def enter_metastake_on_behalf(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            type[str]: original caller
        """
        logger.debug(f"Account: {user.address}")
        return self._call_endpoint(_ENTER_METASTAKE_ON_BEHALF, user, proxy, args)

    def exit_metastake(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            type[int]: first token slippage
            type[int]: second token slippage
            optional: type[str]: original caller
        """
        logger.debug(f"Account: {user.address}")
        return self._call_endpoint(_EXIT_METASTAKE, user, proxy, args)

    def claim_rewards_metastaking(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            optional: type[str]: original caller
        """
        logger.debug(f"Account: {user.address}")
        return self._call_endpoint(_CLAIM_REWARDS_METASTAKING, user, proxy, args)

    def claim_rewards_on_behalf_metastaking(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
        """
        logger.debug(f"Account: {user.address}")
        return self._call_endpoint(_CLAIM_REWARDS_ON_BEHALF_METASTAKING, user, proxy, args)

    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_address: str):
        return self._call_endpoint(_SET_ENERGY_FACTORY_ADDRESS, deployer, proxy, [energy_address])


    def get_energy_factory_address(self, proxy: ProxyNetworkProvider) -> str:
        return self._query_view(proxy, MetaStakingContractDataFetcher, 'getEnergyFactoryAddress',
                                returns=Address, empty="")
    
    def get_decoded_metastake_token_attributes_from_proxy(self, proxy: ProxyNetworkProvider, 
                                                              holder_address: str, token_nonce: int) -> Dict[str, Any]:
        """ Get decoded attributes of the metastake token from the proxy without underlying farm and stake tokens.
        Proxy usage requires to know the holder address."""
        metastake_token_on_network = proxy.get_token_of_account(Address(holder_address), Token(self.metastake_token, token_nonce))
         
        decoded_attributes = decode_merged_attributes(metastake_token_on_network.attributes.hex(), METASTAKE_TOKEN_ATTRIBUTES)
        logger.debug(f'Metastake Tokens: {decoded_attributes}')

        return decoded_attributes

    def get_all_decoded_metastake_token_attributes_from_proxy(self, proxy: ProxyNetworkProvider, 
                                                              holder_address: str, token_nonce: int) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """ Get all decoded attributes of the metastake token and its underlying farm and stake tokens from the proxy. 
        Proxy usage requires to know the holder address."""
        decoded_attributes = self.get_decoded_metastake_token_attributes_from_proxy(proxy, holder_address, token_nonce)

        farm_token_on_network = proxy.get_token_of_account(Address(self.address), Token(self.farm_token, decoded_attributes.get('lp_farm_token_nonce')))
        farm_token_decoded_attributes = decode_merged_attributes(farm_token_on_network.attributes.hex(), FARM_TOKEN_ATTRIBUTES)
        logger.debug(f'Underlying Farm Tokens: {farm_token_decoded_attributes}')

        stake_token_on_network = proxy.get_token_of_account(Address(self.address), Token(self.stake_token, decoded_attributes.get('staking_farm_token_nonce')))
        try:
            stake_token_decoded_attributes = decode_merged_attributes(stake_token_on_network.attributes.hex(), STAKE_V2_TOKEN_ATTRIBUTES)
        except ValueError as e:
            # handle for old stake token attributes
            stake_token_decoded_attributes = decode_merged_attributes(stake_token_on_network.attributes.hex(), STAKE_V1_TOKEN_ATTRIBUTES)
        logger.debug(f'Underlying Stake Tokens: {stake_token_decoded_attributes}')

        return decoded_attributes, farm_token_decoded_attributes, stake_token_decoded_attributes
    