from typing import List, Optional, Sequence, Union
import base64
from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_core import Address, ContractQueryBuilder
from multiversx_sdk_core.transaction_builders import ContractCallBuilder, DefaultTransactionBuildersConfiguration

from utils.logger import get_logger
from utils.decode import top_dec_bytes, Decoder
from utils.utils_chain import Account
from utils.utils_tx import send_contract_call_tx, _prep_args_for_addresses, ESDTToken


logger = get_logger(__name__)

Payment = Union[int, ESDTToken, Sequence[ESDTToken]]


class ContractInteractor:
  proxy: ProxyNetworkProvider
  contract: Address
  user: Optional[Account]

  def __init__(self, proxy: ProxyNetworkProvider, contract: Address, user: Optional[Account] = None):
    self.proxy = proxy
    self.contract = contract
    self.user = user

  def _query(self, function: str, args: list, decoders: List[Decoder]):
    query = ContractQueryBuilder(self.contract, function, args).build()
    b64_data = self.proxy.query_contract(query).return_data
    dec_data = []
    for i in range(len(b64_data)):
      b64 = b64_data[i]
      decoder = decoders[min(i, len(decoders) - 1)]
      dec_data.append(top_dec_bytes(base64.b64decode(b64), decoder))
    return dec_data

  def _call(self, function: str, args: Sequence, gas_limit: int, payment: Optional[Payment] = None):
    logger.debug(f"Calling {function} at {self.contract.bech32()}")
    logger.debug(f"With args: {args}")

    value: Union[int, None] = None
    esdt_transfers: Sequence[ESDTToken] = []
    if isinstance(payment, int):
      value = payment
    elif isinstance(payment, ESDTToken):
      esdt_transfers = [payment]
    elif isinstance(payment, list) and all(isinstance(x, ESDTToken) for x in payment):
      esdt_transfers = payment

    network_config = self.proxy.get_network_config()     # TODO: find solution to avoid this call
    config = DefaultTransactionBuildersConfiguration(chain_id=network_config.chain_id)
    builder = ContractCallBuilder(
      config=config,
      caller=self.user.address,
      contract=self.contract,
      function_name=function,
      call_arguments=_prep_args_for_addresses(args),
      value=value,
      esdt_transfers=esdt_transfers,
      gas_limit=gas_limit,
      nonce=self.user.nonce,
    )
    tx = builder.build()
    tx.signature = self.user.sign_transaction(tx)

    tx_hash = send_contract_call_tx(tx, self.proxy)
    self.user.nonce += 1 if tx_hash != "" else 0

    return tx_hash
