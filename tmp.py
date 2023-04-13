from multiversx_sdk_network_providers import ProxyNetworkProvider
from multiversx_sdk_core import Address

from contracts.pair_contract_gen import PairContractInteractor


proxy = ProxyNetworkProvider("https://gateway.multiversx.com")
contract_address = Address.from_bech32("erd1qqqqqqqqqqqqqpgqp5d4x3d263x4alnapwafwujch5xqmvyq2jpsk2xhsy")
interactor = PairContractInteractor(proxy, contract_address)

print(interactor.getState())
print(interactor.getTokensForGivenPosition(1000))
