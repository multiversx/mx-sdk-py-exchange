from enum import Enum

from utils.utils_tx import send_contract_call_tx, prepare_contract_call_tx
from utils.utils_generic import print_test_step_fail, print_warning
from erdpy.accounts import Account, Address
from erdpy.proxy import ElrondProxy


class ESDTRoles(Enum):
    ESDTRoleLocalMint = 1
    ESDTRoleLocalBurn = 2


class ESDTContract:
    def __init__(self, esdt_address):
        self.address = esdt_address

    """ Expected as args:
        type[str]: token_id
        type[str]: address to assign role to
        type[str]: role name
    """
    def set_special_role_token(self, token_owner: Account, proxy: ElrondProxy, args: list):
        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to add trusted swap pair. Args list not as expected.")
            return ""
        token_id = args[0]
        address = args[1]
        role = args[2]
        print_warning(f"Set ESDT role {role} for {token_id} on address {address}")

        network_config = proxy.get_network_config()
        gas_limit = 100000000
        sc_args = [
            "0x" + token_id.encode("ascii").hex(),
            "0x" + Address(address).hex(),
            "0x" + role.encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), token_owner, network_config, gas_limit,
                                      "setSpecialRole", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        token_owner.nonce += 1 if tx_hash != "" else 0

        return tx_hash

    def unset_special_role_token(self, token_owner: Account, proxy: ElrondProxy, args: list):
        if len(args) != 3:
            print_test_step_fail(f"FAIL: Failed to add trusted swap pair. Args list not as expected.")
            return ""
        token_id = args[0]
        address = args[1]
        role = args[2]
        print_warning(f"Set ESDT role {role} for {token_id} on address {address}")

        network_config = proxy.get_network_config()
        gas_limit = 10000000
        sc_args = [
            "0x" + token_id.encode("ascii").hex(),
            "0x" + Address(address).hex(),
            "0x" + role.encode("ascii").hex()
        ]
        tx = prepare_contract_call_tx(Address(self.address), token_owner, network_config, gas_limit,
                                      "unSetSpecialRole", sc_args)
        tx_hash = send_contract_call_tx(tx, proxy)
        token_owner.nonce += 1 if tx_hash != "" else 0

        return tx_hash
