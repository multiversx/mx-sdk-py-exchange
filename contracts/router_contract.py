import config
from contracts.contract_identities import DEXContractInterface, RouterContractVersion
from utils.logger import get_logger
from utils.utils_tx import deploy, upgrade_call, get_deployed_address_from_tx, endpoint_call
from utils.utils_generic import log_step_pass, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk_core import CodeMetadata
from multiversx_sdk_network_providers import ProxyNetworkProvider


logger = get_logger(__name__)


class RouterContract(DEXContractInterface):
    def __init__(self, version: RouterContractVersion, address: str = ""):
        self.address = address
        self.version = version

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "version": self.version.value
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return RouterContract(address=config_dict['address'],
                              version=RouterContractVersion(config_dict['version']))

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        type[str]: pair template address
        """
        function_purpose = f"Deploy router contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = [
            Address(args[0])
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        type[str]: pair template address
        """
        function_purpose = f"Upgrade router contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        arguments = [
            Address(args[0])
        ]

        tx_hash = upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                               bytecode_path, metadata, arguments)

        return tx_hash

    def add_common_tokens_for_user_pairs(self, owner: Account, proxy: ProxyNetworkProvider, *tokens):
        """Expecting as args:
            type[str..]: common token IDs
        """
        function_purpose = f"Add common tokens for user pairs"
        logger.info(function_purpose)

        gas_limit = 100000000

        sc_args = []
        for token in tokens:
            sc_args.append(token)

        return endpoint_call(proxy, gas_limit, owner, Address(self.address), "addCommonTokensForUserPairs", sc_args)

    def config_enable_by_user_parameters(self, deployer: Account, proxy: ProxyNetworkProvider, **kargs):
        """Expecting as args:
            type[str]: common_token_id
            type[str]: locked_token_id
            type[int]: min_locked_token_value
            type[int]: min_lock_period_epochs
        """
        function_purpose = f"Add enable config for common token"
        logger.info(function_purpose)

        gas_limit = 100000000

        sc_args = [
            kargs['common_token_id'],
            kargs['locked_token_id'],
            kargs['min_locked_token_value'],
            kargs['min_lock_period_epochs']
        ]

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "configEnableByUserParameters", sc_args)

    def pair_contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: first pair token
            type[str]: second pair token
            type[str]: address of initial liquidity adder
            type[str]: total fee percentage
            type[str]: special fee percentage
            type[str..]: admin addresses (v2 only)
        """
        function_purpose = f"Deploy pair via router"
        logger.info(function_purpose)

        address, tx_hash = "", ""

        if len(args) < 5:
            log_unexpected_args(function_purpose, args)
            return address, tx_hash

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            Address(args[2]),
            args[3],
            args[4]
        ]

        if self.version == RouterContractVersion.V2:
            sc_args.extend(args[5:])

        tx_hash = endpoint_call(proxy, gas_limit, deployer, Address(self.address), "createPair", sc_args)

        # retrieve deployed contract address
        if tx_hash != "":
            address = get_deployed_address_from_tx(tx_hash, proxy)

        return tx_hash, address

    def pair_contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, args: list) -> str:
        """ Expected as args:
        type[str]: first token id
        type[str]: second token id
        type[int]: total fee percent
        type[int]: special fee percent
        type[str]: initial liquidity adder (only v1)
        """
        function_purpose = f"Upgrade pair contract"
        logger.info(function_purpose)

        tx_hash = ""

        if len(args) < 4:
            log_unexpected_args(function_purpose, args)
            return tx_hash

        gas_limit = 200000000
        sc_args = [
            args[0],
            args[1],
            args[2],
            args[3]
        ]
        if self.version == RouterContractVersion.V1:
            sc_args.insert(2, args[4])

        tx_hash = endpoint_call(proxy, gas_limit, deployer, Address(self.address), "upgradePair", sc_args)

        return tx_hash

    def issue_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address
            type[str]: lp token name
            type[str]: lp token ticker
        """
        function_purpose = f"Issue LP token"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            Address(args[0]),
            args[1],
            args[2]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueLpToken", sc_args,
                             value=config.DEFAULT_ISSUE_TOKEN_PRICE)

    def set_lp_token_local_roles(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        function_purpose = f"Set LP token local roles"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            Address(pair_contract)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setLocalRoles", sc_args)

    def set_fee_on(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: pair address to send fees
            type[str]: address to receive fees
            type[str]: expected token
        """
        function_purpose = f"Set fee on for pool"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            Address(args[0]),
            Address(args[1]),
            args[2]
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setFeeOn", sc_args)
    
    def set_pair_creation_enabled(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: status
        """
        function_purpose = f"Set fee on for pool"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 10000000
        sc_args = args
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setPairCreationEnabled", sc_args)

    def pair_contract_pause(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        function_purpose = f"Pause pair contract"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            Address(pair_contract)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "pause", sc_args)

    def pair_contract_resume(self, deployer: Account, proxy: ProxyNetworkProvider, pair_contract: str):
        function_purpose = f"Resume pair contract"
        logger.info(function_purpose)

        gas_limit = 30000000
        sc_args = [
            Address(pair_contract)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "resume", sc_args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed router contract: {self.address}")
