import sys
import traceback

from arrows.stress.contracts.contract import load_code_as_hex
from contracts.contract_identities import DEXContractInterface
from utils.utils_tx import prepare_contract_call_tx, send_contract_call_tx, \
    multi_esdt_endpoint_call, endpoint_call
from utils.utils_chain import print_transaction_hash
from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_test_substep, print_warning
from erdpy.accounts import Account, Address
from erdpy.contracts import CodeMetadata, SmartContract
from erdpy.proxy import ElrondProxy


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

    def contract_deploy(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        print_warning("Deploy simple lock energy contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        address = ""
        tx_hash = ""

        if len(args) != 5:
            print_test_step_fail(f"FAIL: Failed to deploy contract. Args list not as expected.")
            return tx_hash, address
        arguments = [
            "str:" + self.base_token,   # base token id
            "str:" + args[0],           # legacy token id
            args[1],   # locked asset factory address
            args[2]   # min migrated token locking epochs
        ]
        lock_fee_pairs = list(zip(args[3], args[4]))
        lock_options = [item for sublist in lock_fee_pairs for item in sublist]
        arguments.extend(lock_options)  # lock_options

        print(f"Arguments: {arguments}")
        contract = SmartContract(bytecode=bytecode, metadata=metadata)
        tx = contract.deploy(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                             network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            print_transaction_hash(tx_hash, proxy.url, True)

            address = contract.address.bech32()
            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash, address

        return tx_hash, address

    def contract_upgrade(self, deployer: Account, proxy: ElrondProxy, bytecode_path, args: list):
        """Expecting as args:
                    type[str]: legacy token id
                    type[str]: locked asset factory address
                    type[int]: min migrated token locking epochs
                    type[list]: lock options
                    type[list]: penalties
        """
        print_warning("Upgrade simple lock energy contract")

        metadata = CodeMetadata(upgradeable=True, payable_by_sc=True, readable=True)
        bytecode: str = load_code_as_hex(bytecode_path)
        network_config = proxy.get_network_config()
        gas_limit = 200000000
        value = 0
        tx_hash = ""

        if len(args) != 5:
            print_test_step_fail(f"FAIL: Failed to upgrade contract. Args list not as expected.")
            return tx_hash
        arguments = [
            "str:" + self.base_token,   # base token id
            "str:" + args[0],           # legacy token id
            args[1],   # locked asset factory address
            args[2]   # min migrated token locking epochs
        ]

        lock_fee_pairs = list(zip(args[3], args[4]))
        lock_options = [item for sublist in lock_fee_pairs for item in sublist]
        arguments.extend(lock_options)  # lock_options

        contract = SmartContract(bytecode=bytecode, metadata=metadata, address=Address(self.address))
        tx = contract.upgrade(deployer, arguments, network_config.min_gas_price, gas_limit, value,
                              network_config.chain_id, network_config.min_tx_version)

        try:
            response = proxy.send_transaction_and_wait_for_result(tx.to_dictionary())
            tx_hash = response.get_hash()
            print_transaction_hash(tx_hash, proxy.url, True)

            deployer.nonce += 1

        except Exception as ex:
            print_test_step_fail(f"Failed to send deploy transaction due to: {ex}")
            traceback.print_exception(*sys.exc_info())
            return tx_hash

        return tx_hash

    def issue_locked_lp_token(self, deployer: Account, proxy: ElrondProxy, locked_lp_token: str):
        print_warning("Issue locked LP token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x12"
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueLpProxyToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def issue_locked_farm_token(self, deployer: Account, proxy: ElrondProxy, locked_lp_token: str):
        print_warning("Issue locked Farm token")

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x" + locked_lp_token.encode("ascii").hex(),
            "0x12"
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueFarmProxyToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def issue_locked_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: token display name
            type[str]: token ticker
        """
        print_warning("Issue locked token")

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to issue locked token in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""

        network_config = proxy.get_network_config()
        tx_hash = ""

        gas_limit = 100000000
        sc_args = [
            "0x" + args[0].encode("ascii").hex(),
            "0x" + args[1].encode("ascii").hex(),
            "0x12"
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "issueLockedToken", sc_args, value="50000000000000000")
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def set_transfer_role_locked_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: new role address; empty will assign the role to the contract itself
        """

        function_purpose = "Set transfer role locked token"
        return endpoint_call(function_purpose, proxy, 100000000, deployer, Address(self.address),
                             "setTransferRoleLockedToken", args)

    def set_burn_role_locked_token(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: new role address
        """
        function_purpose = "set burn roles on locked token for address"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 100000000, deployer, Address(self.address),
                             "setBurnRoleLockedToken", args)

    def set_old_locked_asset_factory(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: old locked asset factory address
        """
        function_purpose = "set old locked asset factory address"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setOldLockedAssetFactoryAddress", args)

    def set_fees_collector(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: fees collector address
        """
        function_purpose = "set fees collector address"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setFeesCollectorAddress", args)

    def set_token_unstake(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[str]: token unstake address
        """
        function_purpose = "set fees collector address"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setTokenUnstakeAddress", args)

    def add_lock_options(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        function_purpose = "add lock options"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "addLockOptions", args)

    def remove_lock_options(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[int..]: lock options
        """
        function_purpose = "remove lock options"

        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "removeLockOptions", args)

    def set_penalty_percentage(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[int]: min penalty 0 - 10000
            type[int]: max penalty - 10000
        """
        function_purpose = "set penalty percentage"

        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setPenaltyPercentage", args)

    def set_fees_burn_percentage(self, deployer: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[int]: burn percentage 0 - 10000
        """
        function_purpose = "set fees burn percentage"

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose} in simple lock energy contract. "
                                 f"Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address),
                             "setFeesBurnPercentage", args)

    def add_sc_to_whitelist(self, deployer: Account, proxy: ElrondProxy, contract_address: str):
        print_warning("Add SC to Whitelist in simple lock energy contract")

        network_config = proxy.get_network_config()

        gas_limit = 50000000
        sc_args = [
            contract_address
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addSCAddressToWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def remove_sc_from_whitelist(self, deployer: Account, proxy: ElrondProxy, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        print_warning("Remove SC from Whitelist in simple lock energy contract")

        network_config = proxy.get_network_config()

        gas_limit = 50000000
        sc_args = [
            contract_address
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "removeSCAddressFromWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def add_sc_to_token_transfer_whitelist(self, deployer: Account, proxy: ElrondProxy, contract_address: str):
        print_warning("Add SC to Token Transfer Whitelist in simple lock energy contract")

        network_config = proxy.get_network_config()

        gas_limit = 50000000
        sc_args = [
            contract_address
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "addToTokenTransferWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def remove_sc_from_token_transfer_whitelist(self, deployer: Account, proxy: ElrondProxy, contract_address: str):
        """ Expected as args:
            type[str]: address
        """
        print_warning("Remove SC from Token Transfer Whitelist in simple lock energy contract")

        network_config = proxy.get_network_config()

        gas_limit = 50000000
        sc_args = [
            contract_address
        ]
        print(f"Arguments: {sc_args}")
        tx = prepare_contract_call_tx(Address(self.address), deployer, network_config, gas_limit,
                                      "removeFromTokenTransferWhitelist", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        deployer.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def lock_tokens(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: lock epochs
            opt: type[address]: destination address
        """
        function_purpose = "lock tokens"

        if len(args) < 2:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "lockTokens", args)

    def unlock_tokens(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            opt: type[address]: destination address
        """
        function_purpose = "unlock tokens"
        if len(args) < 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "unlockTokens", args)

    def unlock_early(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
        """
        function_purpose = "unlock tokens early"
        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "unlockEarly", args)

    def reduce_lock(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: epochs to reduce
        """
        function_purpose = "reduce lock period"
        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "reduceLockPeriod", args)

    def extend_lock(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
            type[List[ESDTToken]]: tokens list
            type[int]: new lock option
        """
        function_purpose = "extend lock period"
        if len(args) != 2:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 10000000,
                                        user, Address(self.address), "extendLockingPeriod", args)

    def add_liquidity_locked_token(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        function_purpose = "add liquidity for locked token"

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""

        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "addLiquidityLockedToken", args)

    def remove_liquidity_locked_token(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
                    type[int]: first token amount min
                    type[int]: second token amount min
        """
        function_purpose = "add liquidity for locked token"

        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 20000000,
                                        user, Address(self.address), "removeLiquidityLockedToken", args)

    def enter_farm_locked_token(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "enter farm with locked token"

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "enterFarmLockedToken", args)

    def exit_farm_locked_token(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "exit farm with locked token"

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "exitFarmLockedToken", args)

    def claim_farm_locked_token(self, user: Account, proxy: ElrondProxy, args: list):
        """ Expected as args:
                    type[List[ESDTToken]]: tokens list
        """
        function_purpose = "claim farm with locked token"

        if len(args) != 1:
            print_test_step_fail(f"FAIL: Failed to {function_purpose}. Args list not as expected.")
            return ""
        print(f"Arguments: {args}")
        return multi_esdt_endpoint_call(function_purpose, proxy, 30000000,
                                        user, Address(self.address), "farmClaimRewardsLockedToken", args)

    def pause(self, deployer: Account, proxy: ElrondProxy):
        function_purpose = "Resume simple lock energy contract"
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address), "pause", [])

    def resume(self, deployer: Account, proxy: ElrondProxy):
        function_purpose = "Resume simple lock energy contract"
        return endpoint_call(function_purpose, proxy, 10000000, deployer, Address(self.address), "unpause", [])

    def contract_start(self, deployer: Account, proxy: ElrondProxy, args: list = None):
        self.set_transfer_role_locked_token(deployer, proxy, [])
        self.resume(deployer, proxy)

    def print_contract_info(self):
        print_test_step_pass(f"Deployed simple lock energy contract: {self.address}")
        print_test_substep(f"Base token: {self.base_token}")
        print_test_substep(f"Locked token: {self.locked_token}")
        print_test_substep(f"Locked LP token: {self.lp_proxy_token}")
        print_test_substep(f"Locked Farm token: {self.farm_proxy_token}")
