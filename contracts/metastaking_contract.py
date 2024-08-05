from typing import Any, Dict, List, Tuple, override
from contracts.contract_identities import DEXContractInterface, MetaStakingContractVersion
from contracts.base_contracts import BaseSCWhitelistContract
from utils.contract_data_fetchers import MetaStakingContractDataFetcher
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, \
    endpoint_call, multi_esdt_endpoint_call
from utils.utils_chain import Account, WrapperAddress as Address, base64_to_hex, decode_merged_attributes, hex_to_string
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.decoding_structures import FARM_TOKEN_ATTRIBUTES, METASTAKE_TOKEN_ATTRIBUTES, STAKE_V2_TOKEN_ATTRIBUTES, STAKE_V1_TOKEN_ATTRIBUTES
import config

from utils.contract_data_fetchers import MetaStakingContractDataFetcher

logger = get_logger(__name__)


class MetaStakingContract(BaseSCWhitelistContract):
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
            "stake_address": self.stake_address,
            "version": self.version.value,
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
                                   stake_address=config_dict['stake_address'],
                                   version=MetaStakingContractVersion(config_dict['version']))

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

    def whitelist_contract(self, deployer: Account, proxy: ProxyNetworkProvider, contract_to_whitelist: str):
        function_purpose = f"Whitelist contract in metastaking"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_to_whitelist)
        ]

        endpoint_name = "addSCAddressToWhitelist"
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), endpoint_name, sc_args)

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
        function_purpose = f"enterMetastaking"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        metastake_fn = 'stakeFarmTokens'
        gas_limit = 70000000

        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit,
                                        user, Address(self.address), metastake_fn, args)

    def exit_metastake(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            type[int]: first token slippage
            type[int]: second token slippage
            optional: type[str]: original caller
        """
        function_purpose = f"exitMetastaking"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 70000000
        exit_metastake_fn = 'unstakeFarmTokens'

        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit,
                                        user, Address(self.address), exit_metastake_fn, args)

    def claim_rewards_metastaking(self, proxy: ProxyNetworkProvider, user: Account, args: List[Any]):
        """Expected as args:
            type[List[ESDTToken]]: tokens to use
            optional: type[str]: original caller
        """
        function_purpose = f"claimDualYield"
        logger.info(function_purpose)
        logger.debug(f"Account: {user.address}")

        gas_limit = 70000000
        claim_fn = 'claimDualYield'

        return multi_esdt_endpoint_call(function_purpose, proxy, gas_limit,
                                        user, Address(self.address), claim_fn, args)
    
    def set_energy_factory_address(self, deployer: Account, proxy: ProxyNetworkProvider, energy_address: str):
        function_purpose = "Set energy factory address in proxy staking contract"
        logger.info(function_purpose)

        if energy_address == "":
            log_unexpected_args(function_purpose, energy_address)
            return ""

        gas_limit = 50000000
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyFactoryAddress",
                             [energy_address])
    
    def get_energy_factory_address(self, proxy: ProxyNetworkProvider) -> str:
        data_fetcher = MetaStakingContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getEnergyFactoryAddress')
        if not raw_results:
            return ""
        address = Address.from_hex(raw_results).bech32()

        return address

    def get_all_decoded_metastake_token_attributes_from_proxy(self, proxy: ProxyNetworkProvider, 
                                                              holder_address: str, token_nonce: int) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """ Get all decoded attributes of the metastake token and its underlying farm and stake tokens from the proxy. 
        Proxy usage requires to know the holder address."""
        metastake_token_on_network = proxy.get_nonfungible_token_of_account(Address(holder_address), self.metastake_token, token_nonce)
         
        decoded_attributes = decode_merged_attributes(base64_to_hex(metastake_token_on_network.attributes), METASTAKE_TOKEN_ATTRIBUTES)
        logger.debug(f'Metatake Tokens: {decoded_attributes}')

        farm_token_on_network = proxy.get_nonfungible_token_of_account(Address(self.address), self.farm_token, decoded_attributes.get('lp_farm_token_nonce'))
        farm_token_decoded_attributes = decode_merged_attributes(base64_to_hex(farm_token_on_network.attributes), FARM_TOKEN_ATTRIBUTES)
        logger.debug(f'Underlying Farm Tokens: {farm_token_decoded_attributes}')

        stake_token_on_network = proxy.get_nonfungible_token_of_account(Address(self.address), self.stake_token, decoded_attributes.get('staking_farm_token_nonce'))
        try:
            stake_token_decoded_attributes = decode_merged_attributes(base64_to_hex(stake_token_on_network.attributes), STAKE_V2_TOKEN_ATTRIBUTES)
        except ValueError as e:
            # handle for old stake token attributes
            stake_token_decoded_attributes = decode_merged_attributes(base64_to_hex(stake_token_on_network.attributes), STAKE_V1_TOKEN_ATTRIBUTES)
        logger.debug(f'Underlying Stake Tokens: {stake_token_decoded_attributes}')

        return decoded_attributes, farm_token_decoded_attributes, stake_token_decoded_attributes
    