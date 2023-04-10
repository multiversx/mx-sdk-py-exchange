from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from utils.contract_data_fetchers import SimpleLockEnergyContractDataFetcher
from utils.utils_tx import ESDTToken, NetworkProviders
from utils.utils_chain import get_token_details_for_address, decode_merged_attributes, base64_to_hex
from multiversx_sdk_cli.accounts import Address


class SimpleLockEnergyTokenAttributes:
    token_identifier: str
    original_token_nonce: int
    unlock_epoch: int

    def __init__(self, decoded_dict: dict):
        for key, value in decoded_dict.items():
            setattr(self, key, value)


class SimpleLockEnergyTracker:
    token_decode_structure = {
        'token_identifier': 'string',
        'original_token_nonce': 'u64',
        'unlock_epoch': 'u64',
    }

    def __init__(self, address: str, network_provider: NetworkProviders):
        self.address = address
        self.network_provider = network_provider
        self.contract_data_fetcher = SimpleLockEnergyContractDataFetcher(Address(address), network_provider.proxy.url)
        self.base_token = self.contract_data_fetcher.get_data("getBaseAssetTokenId")
        self.locked_token = self.contract_data_fetcher.get_data("getLockedTokenId")

        # penalties_hex = self.contract_data_fetcher.get_data("getPenaltyPercentage")
        # penalties_decoded = decode_merged_attributes(penalties_hex, {'min': 'u16', 'max': 'u16'})
        # self.min_penalty = penalties_decoded['min']
        # self.max_penalty = penalties_decoded['max']
        self.fees_burn_percentage = self.contract_data_fetcher.get_data("getFeesBurnPercentage")

        self.lock_options: list = self.contract_data_fetcher.get_data("getLockOptions")
        self.lock_options.sort()

    def get_locked_token_attributes(self, token: ESDTToken) -> SimpleLockEnergyTokenAttributes:
        # fetch token attributes
        raw_attributes = self.network_provider.api.get_nft_data(token.get_full_token_name())['attributes']
        # decode token attributes
        decoded_attributes = decode_merged_attributes(base64_to_hex(raw_attributes), self.token_decode_structure)
        token_attributes = SimpleLockEnergyTokenAttributes(decoded_attributes)
        return token_attributes

    def get_expected_penalty(self, token: ESDTToken, reduce_epochs: int = -1) -> int:
        """
        Token: full token details on which the penalty should be applied
        reduce_epochs: how many epochs; if -1 or default, will consider reduce on remaining period
        """
        token_attributes = self.get_locked_token_attributes(token)
        current_epoch = self.network_provider.proxy.get_epoch()

        remaining_lock_epochs = token_attributes.unlock_epoch - current_epoch
        max_unlock_epochs = max(remaining_lock_epochs, 0)

        if reduce_epochs < 0:
            unlock_epochs = max_unlock_epochs
        else:
            unlock_epochs = min(reduce_epochs, max_unlock_epochs)

        penalty = self.min_penalty + (self.max_penalty - self.min_penalty) * unlock_epochs // self.lock_options[-1]

        return penalty
