from typing import Dict, List, Any

from contracts.contract_identities import DEXContractInterface
from utils.contract_data_fetchers import SimpleLockEnergyContractDataFetcher
from utils import decoding_structures
from utils.logger import get_logger
from utils.utils_tx import multi_esdt_endpoint_call, endpoint_call, deploy, upgrade_call
from utils.utils_generic import log_step_pass, log_substep, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address, decode_merged_attributes
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


class SimpleLockEnergyContract(DEXContractInterface):
    def __init__(self, base_token: str, locked_token: str = "", lp_proxy_token: str = "", farm_proxy_token: str = "",
                 address: str = ""):
        self.address = address
        self.base_token = base_token
        self.locked_token = locked_token
        self.lp_proxy_token = lp_proxy_token
        self.farm_proxy_token = farm_proxy_token

    def get_config_dict(self) -> dict:
        output_dict = {
            "address": self.address,
            "base_token": self.base_token,
            "locked_token": self.locked_token,
            "lp_proxy_token": self.lp_proxy_token,
            "farm_proxy_token": self.farm_proxy_token
        }
        return output_dict

    @classmethod
    def load_config_dict(cls, config_dict: dict):
        return SimpleLockEnergyContract(address=config_dict['address'],
                                        base_token=config_dict['base_token'],
                                        locked_token=config_dict['locked_token'],
                                        lp_proxy_token=config_dict['lp_proxy_token'],
                                        farm_proxy_token=config_dict['farm_proxy_token'])

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        function_purpose = "Deploy simple lock energy contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 5:
            log_unexpected_args(function_purpose, args)
            return "", ""
        arguments = [
            self.base_token,   # base token id
            args[0],           # legacy token id
            Address(args[1]),   # locked asset factory address
            args[2]   # min migrated token locking epochs
        ]
        lock_fee_pairs = list(zip(args[3], args[4]))
        lock_options = [item for sublist in lock_fee_pairs for item in sublist]
        arguments.extend(lock_options)  # lock_options

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list, no_init=False):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        function_purpose = "Upgrade simple lock energy contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if no_init:
            arguments = []
        else:
            if len(args) != 5:
                log_unexpected_args(function_purpose, args)
                return ""
            arguments = [
                self.base_token,   # base token id
                args[0],           # legacy token id
                Address(args[1]),   # locked asset factory address
                args[2]   # min migrated token locking epochs
            ]

            lock_fee_pairs = list(zip(args[3], args[4]))
            lock_options = [item for sublist in lock_fee_pairs for item in sublist]
            arguments.extend(lock_options)  # lock_options

        return upgrade_call(type(self).__name__, proxy, gas_limit, deployer, Address(self.address),
                            bytecode_path, metadata, [])

    def issue_locked_lp_token(self, deployer: Account, proxy: ProxyNetworkProvider, locked_lp_token: str):
        function_purpose = "Issue locked LP token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            locked_lp_token,
            locked_lp_token,
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueLpProxyToken", sc_args,
                             value="50000000000000000")

    def issue_locked_farm_token(self, deployer: Account, proxy: ProxyNetworkProvider, locked_lp_token: str):
        function_purpose = "Issue locked Farm token"
        logger.info(function_purpose)

        gas_limit = 100000000
        sc_args = [
            locked_lp_token,
            locked_lp_token,
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueFarmProxyToken", sc_args,
                             value="50000000000000000")

    def issue_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        function_purpose = "Issue locked token"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 100000000
        sc_args = [
            args[0],
            args[1],
            18
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "issueLockedToken", sc_args,
                             value="50000000000000000")

    def set_transfer_role_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: new role address; empty will assign the role to the contract itself
        """

        function_purpose = "Set transfer role locked token"
        logger.info(function_purpose)
        return endpoint_call(proxy, 100000000, deployer, Address(self.address), "setTransferRoleLockedToken", args)

    def set_burn_role_locked_token(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: new role address
        """
        function_purpose = "set burn roles on locked token for address"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 100000000, deployer, Address(self.address), "setBurnRoleLockedToken", args)

    def set_old_locked_asset_factory(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: old locked asset factory address
        """
        function_purpose = "set old locked asset factory address"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setOldLockedAssetFactoryAddress", args)

    def set_fees_collector(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: fees collector address
        """
        function_purpose = "set fees collector address"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setFeesCollectorAddress", args)

    def set_token_unstake(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: token unstake address
        """
        function_purpose = "set fees collector address"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setTokenUnstakeAddress", args)

    def add_lock_options(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        function_purpose = "add lock options"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "addLockOptions", args)

    def remove_lock_options(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        function_purpose = "remove lock options"
        logger.info(function_purpose)

        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "removeLockOptions", args)

    def set_penalty_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: min penalty 0 - 10000
            type[int]: max penalty - 10000
        """
        function_purpose = "set penalty percentage"
        logger.info(function_purpose)

        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setPenaltyPercentage", args)

    def set_fees_burn_percentage(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[int]: burn percentage 0 - 10000
        """
        function_purpose = "set fees burn percentage"
        logger.info(function_purpose)

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setFeesBurnPercentage", args)

    def add_sc_to_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        function_purpose = "Add SC to Whitelist in simple lock energy contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_address)
        ]
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "addSCAddressToWhitelist", sc_args)

    def remove_sc_from_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        function_purpose = "Remove SC from Whitelist in simple lock energy contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_address)
        ]

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "removeSCAddressFromWhitelist", sc_args)

    def add_sc_to_token_transfer_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        function_purpose = "Add SC to Token Transfer Whitelist in simple lock energy contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_address)
        ]

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "addToTokenTransferWhitelist", sc_args)

    def remove_sc_from_token_transfer_whitelist(self, deployer: Account, proxy: ProxyNetworkProvider, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        function_purpose = "Remove SC from Token Transfer Whitelist in simple lock energy contract"
        logger.info(function_purpose)

        gas_limit = 50000000
        sc_args = [
            Address(contract_address)
        ]

        return endpoint_call(proxy, gas_limit, deployer, Address(self.address),
                             "removeFromTokenTransferWhitelist", sc_args)
    
    def set_energy_for_old_tokens(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: address
            type[int]: token_amount
            type[int]: energy_amount
        """
        function_purpose = "Set energy for old tokens in simple lock energy contract"
        logger.info(function_purpose)

        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        gas_limit = 50000000
        sc_args = [
            Address(args[0]),
            args[1],
            args[2]
        ]
        
        return endpoint_call(proxy, gas_limit, deployer, Address(self.address), "setEnergyForOldTokens", sc_args)

    def lock_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: lock epochs
            opt: type[address]: destination address
        """
        function_purpose = "lock tokens"
        logger.info(function_purpose)

        if len(args) < 2:
            log_unexpected_args(function_purpose, args)
            return ""

        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "lockTokens", args)

    def unlock_tokens(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            opt: type[address]: destination address
        """
        function_purpose = "unlock tokens"
        logger.info(function_purpose)
        if len(args) < 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "unlockTokens", args)

    def unlock_early(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
        """
        function_purpose = "unlock tokens early"
        logger.info(function_purpose)
        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "unlockEarly", args)

    def reduce_lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: epochs to reduce
        """
        function_purpose = "reduce lock period"
        logger.info(function_purpose)
        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "reduceLockPeriod", args)

    def extend_lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: new lock option
        """
        function_purpose = "extend lock period"
        logger.info(function_purpose)
        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "extendLockingPeriod", args)

    def extend_lock(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: new lock option
        """
        function_purpose = "extend lock period"
        logger.info(function_purpose)
        if len(args) != 2:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "extendLockingPeriod", args)

    def add_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        function_purpose = "add liquidity for locked token"
        logger.info(function_purpose)
        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""

        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "addLiquidityLockedToken", args)

    def remove_liquidity_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        function_purpose = "add liquidity for locked token"
        logger.info(function_purpose)
        if len(args) != 3:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "removeLiquidityLockedToken", args)

    def enter_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "enter farm with locked token"
        logger.info(function_purpose)
        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "enterFarmLockedToken", args)

    def exit_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "exit farm with locked token"
        logger.info(function_purpose)
        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "exitFarmLockedToken", args)

    def claim_farm_locked_token(self, user: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "claim farm with locked token"
        logger.info(function_purpose)
        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return ""
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "farmClaimRewardsLockedToken", args)

    def pause(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Resume simple lock energy contract"
        logger.info(function_purpose)
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "pause", [])

    def resume(self, deployer: Account, proxy: ProxyNetworkProvider):
        function_purpose = "Resume simple lock energy contract"
        logger.info(function_purpose)
        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "unpause", [])

    def set_energy_entry(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
            type[str]: user address
            type[str]: energy
            type[str]: amount
        """
        function_purpose = "Set energy entry"
        logger.info(function_purpose)

        return endpoint_call(proxy, 10000000, deployer, Address(self.address), "setEnergyForOldTokens", args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = None):
        self.set_transfer_role_locked_token(deployer, proxy, [])
        self.resume(deployer, proxy)

    def print_contract_info(self):
        log_step_pass(f"Deployed simple lock energy contract: {self.address}")
        log_substep(f"Base token: {self.base_token}")
        log_substep(f"Locked token: {self.locked_token}")
        log_substep(f"Locked LP token: {self.lp_proxy_token}")
        log_substep(f"Locked Farm token: {self.farm_proxy_token}")

    def get_lock_options(self, proxy: ProxyNetworkProvider) -> List[Dict[str, Any]]:
        data_fetcher = SimpleLockEnergyContractDataFetcher(Address(self.address), proxy.url)
        raw_result = data_fetcher.get_data("getLockOptions")
        if not raw_result:
            return []
        decoded_results = []
        for entry in raw_result:
            decoded_entry = decode_merged_attributes(entry, decoding_structures.LOCK_OPTIONS)
            decoded_results.append(decoded_entry)
        return decoded_results

    def get_energy_for_user(self, proxy: ProxyNetworkProvider, user_address: str) -> Dict[str, Any]:
        data_fetcher = SimpleLockEnergyContractDataFetcher(Address(self.address), proxy.url)
        raw_results = data_fetcher.get_data('getEnergyEntryForUser', [Address(user_address).serialize()])
        if not raw_results:
            return {}
        energy_entry_user = decode_merged_attributes(raw_results, decoding_structures.ENERGY_ENTRY)

        return energy_entry_user
