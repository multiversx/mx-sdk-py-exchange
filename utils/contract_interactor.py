from typing import Sequence
import base64
from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_core import Address, ContractQueryBuilder

from utils.decode import top_dec_bytes, Decoder


class ContractInteractor:
  proxy: ProxyNetworkProvider
  contract_address: Address

  def __init__(self, proxy: ProxyNetworkProvider, contract_address: Address):
    self.proxy = proxy
    self.contract_address = contract_address

  def _query(self, function: str, args: list, decoders: Sequence[Decoder]):
    query = ContractQueryBuilder(self.contract_address, function, args).build()
    b64_data = self.proxy.query_contract(query).return_data
    dec_data = []
    for i in range(len(b64_data)):
      b64 = b64_data[i]
      decoder = decoders[min(i, len(decoders) - 1)]
      dec_data.append(top_dec_bytes(base64.b64decode(b64), decoder))
    return dec_data
