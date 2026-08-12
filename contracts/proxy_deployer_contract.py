import sys
import traceback

import logging

from contracts.contract_identities import DEXContractInterface, _ConfigField, _Endpoint
from utils.logger import get_logger
from utils.utils_tx import deploy, get_deployed_address_from_tx
from utils.utils_generic import log_step_fail, log_step_pass, log_warning, log_unexpected_args
from utils.utils_chain import Account, WrapperAddress as Address
from multiversx_sdk import CodeMetadata, ProxyNetworkProvider


logger = get_logger(__name__)


def _forwarded_call(args: list) -> list:
    """The farm address, the endpoint being forwarded to, and that endpoint's own arguments.

    The third argument is the remote endpoint's argument list, and a caller with only one to pass is
    allowed to pass it unwrapped — so it is flattened here rather than required to be a list.
    """
    farm_address, endpoint_name, endpoint_args = args
    return [Address(farm_address), endpoint_name,
            *(endpoint_args if isinstance(endpoint_args, list) else [endpoint_args])]


# The contract's two endpoints, one declaration each. Both deploy or drive a farm through this
# contract rather than acting on it, which is why both convert the address they were handed.
#
# `_DEPLOY_FARM` answers with a hash like the other 72; `farm_contract_deploy` goes on to read the
# address the deploy produced off that hash, which is the only thing left in its body.
_DEPLOY_FARM = _Endpoint("Deploy farm via router", 100000000, "deployFarm", at_least=3,
                         build=lambda args: [args[0], args[1], Address(args[2])])
_CALL_FARM_ENDPOINT = _Endpoint(
    "Call farm endpoint via proxy deployer", 20000000, "callFarmEndpoint", exactly=3,
    build=_forwarded_call,
    detail=lambda args: f"Calling remote farm endpoint: {args[1]}",
    detail_level=logging.DEBUG)


class ProxyDeployerContract(DEXContractInterface):
    _CONFIG_FIELDS = (
        _ConfigField("address"),
        _ConfigField("template", arg="template_name"),
    )

    def __init__(self, template_name: str, address: str = ""):
        """
        template_name: should be one of the defined names in config
        """
        self.address = address
        self.template = template_name

    @classmethod
    def load_contract_by_address(cls, address: str):
        raise NotImplementedError

    def contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, bytecode_path, args: list):
        """Expecting as args:
        type[str]: template sc address
        """
        function_purpose = f"Deploy proxy deployer contract"
        logger.info(function_purpose)

        metadata = CodeMetadata(upgradeable=True, payable_by_contract=True, readable=True)
        gas_limit = 200000000

        if len(args) != 1:
            log_unexpected_args(function_purpose, args)
            return "", ""

        arguments = [
            Address(args[0])
        ]

        tx_hash, address = deploy(type(self).__name__, proxy, gas_limit, deployer, bytecode_path, metadata, arguments)
        return tx_hash, address

    def farm_contract_deploy(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """Expecting as args:
            type[str]: reward token id
            type[str]: farming token id
            type[str]: pair contract address
        """
        tx_hash = self._call_endpoint(_DEPLOY_FARM, deployer, proxy, args)

        # the farm is deployed by this contract, so its address only exists once the call has gone out
        address = get_deployed_address_from_tx(tx_hash, proxy) if tx_hash != "" else ""
        return tx_hash, address

    def call_farm_endpoint(self, deployer: Account, proxy: ProxyNetworkProvider, args: list):
        """ Expected as args:
        type[str]: farm address
        type[str]: farm endpoint
        type[list]: farm endpoint args
        """
        return self._call_endpoint(_CALL_FARM_ENDPOINT, deployer, proxy, args)

    def contract_start(self, deployer: Account, proxy: ProxyNetworkProvider, args: list = []):
        pass

    def print_contract_info(self):
        log_step_pass(f"Deployed proxy deployer contract: {self.address}")
