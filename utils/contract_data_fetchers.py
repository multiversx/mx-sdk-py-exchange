import sys
import traceback

from multiversx_sdk_core import Address, ContractQueryBuilder
from multiversx_sdk_network_providers import ProxyNetworkProvider

from utils.utils_chain import base64_to_hex


class DataFetcher:
    def __init__(self, contract_address: Address, proxy_url: str):
        self.proxy = ProxyNetworkProvider(proxy_url)
        self.contract_address = contract_address
        self.view_handler_map = {}

    def get_data(self, view_name: str, attrs: list = []):
        if view_name in self.view_handler_map:
            return self.view_handler_map[view_name](view_name, attrs)
        else:
            raise ValueError(f"View name not registered in {type(self).__name__}")

    def _query_contract(self, view_name: str, attrs: list = []):
        builder = ContractQueryBuilder(
            contract=self.contract_address,
            function=view_name,
            call_arguments=attrs
        )
        query = builder.build()
        return self.proxy.query_contract(query)

    def _get_int_view(self, view_name: str, attrs) -> int:
        try:
            result = self._query_contract(view_name, attrs)
            if result.return_data == '':
                return 0
            return int(base64_to_hex(result.return_data), base=16)
        except Exception as ex:
            print(f"Exception encountered on view name {view_name}: {ex}")
            traceback.print_exception(*sys.exc_info())
        return -1

    def _get_int_list_view(self, view_name: str, attrs) -> list:
        try:
            result = self._query_contract(view_name, attrs)
            return [int(base64_to_hex(elem), base=16) for elem in result.return_data]
        except Exception as ex:
            print(f"Exception encountered on view name {view_name}: {ex}")
            traceback.print_exception(*sys.exc_info())
        return []

    def _get_hex_view(self, view_name: str, attrs) -> str:
        try:
            result = self._query_contract(view_name, attrs)
            return base64_to_hex(result.return_data)
        except Exception as ex:
            print(f"Exception encountered on view name {view_name}: {ex}")
            traceback.print_exception(*sys.exc_info())
        return ""

    def _get_hex_list_view(self, view_name: str, attrs) -> list:
        try:
            result = self._query_contract(view_name, attrs)
            return [base64_to_hex(elem) for elem in result.return_data]
        except Exception as ex:
            print(f"Exception encountered on view name {view_name}: {ex}")
            traceback.print_exception(*sys.exc_info())
        return []


class LockedAssetContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getLockedAssetTokenId": self._get_hex_view,
            "getAssetTokenId": self._get_hex_view,
        }


class ProxyContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getWrappedLpTokenId": self._get_hex_view,
            "getWrappedFarmTokenId": self._get_hex_view,
            "getAssetTokenId": self._get_hex_view,
            "getLockedTokenIds": self._get_hex_list_view,
        }


class SimpleLockContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getLockedTokenId": self._get_hex_view,
            "getLpProxyTokenId": self._get_hex_view,
            "getFarmProxyTokenId": self._get_hex_view,
            "getLockOptions": self._get_hex_list_view,
            "getPenaltyPercentage": self._get_int_list_view,
            "getFeesBurnPercentage": self._get_int_view,
            "getEnergyAmountForUser": self._get_int_view,
            "getEnergyEntryForUser": self._get_int_view,
            "getFeesCollectorAddress": self._get_hex_view,
        }


class SimpleLockEnergyContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getLockedTokenId": self._get_hex_view,
            "getLpProxyTokenId": self._get_hex_view,
            "getFarmProxyTokenId": self._get_hex_view,
            "getBaseAssetTokenId": self._get_hex_view,
            "getEnergyAmountForUser": self._get_int_view,
            "getEnergyEntryForUser": self._get_int_view,
            "getFeesBurnPercentage": self._get_int_view,
            "getPenaltyPercentage": self._get_hex_view,
            "getLockOptions": self._get_int_list_view,
        }


class RouterContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getAllPairsManagedAddresses": self._get_hex_list_view,
            "getPairTemplateAddress": self._get_hex_view
        }


class PriceDiscoveryContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "totalLpTokensReceived": self._get_int_view,
            "getAcceptedTokenFinalAmount": self._get_int_view,
            "getLaunchedTokenFinalAmount": self._get_int_view,
            "getStartEpoch": self._get_int_view,
            "getEndEpoch": self._get_int_view,
            "getRedeemTokenId": self._get_hex_view,
        }

    def get_token_reserve(self, token_ticker: str) -> int:
        data = self.proxy.get_fungible_token_of_account(self.contract_address, token_ticker)
        return data.balance


class FarmContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getFarmTokenSupply": self._get_int_view,
            "getFarmingTokenReserve": self._get_int_view,
            "getLastRewardBlockNonce": self._get_int_view,
            "getPerBlockRewardAmount": self._get_int_view,
            "getRewardPerShare": self._get_int_view,
            "getRewardReserve": self._get_int_view,
            "getUndistributedFees": self._get_int_view,
            "getCurrentBlockFee": self._get_int_view,
            "getDivisionSafetyConstant": self._get_int_view,
            "getFarmTokenId": self._get_hex_view,
            "getFarmingTokenId": self._get_hex_view,
            "getRewardTokenId": self._get_hex_view,
            "getState": self._get_int_view,
        }


class PairContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getAmountOut": self._get_int_view,
            "getEquivalent": self._get_int_view,
            "getTotalFeePercent": self._get_int_view,
            "getSpecialFee": self._get_int_view,
            "updateAndGetSafePrice": self._get_hex_view,
            "getLpTokenIdentifier": self._get_hex_view,
            "getFirstTokenId": self._get_hex_view,
            "getSecondTokenId": self._get_hex_view,
            "getTokensForGivenPosition": self._get_int_list_view,
            "getState": self._get_int_view,
            "getReservesAndTotalSupply": self._get_int_list_view,
            "updateAndGetTokensForGivenPositionWithSafePrice": self._get_hex_list_view
        }

    def get_token_reserve(self, token_ticker: str) -> int:
        data = self.proxy.get_fungible_token_of_account(self.contract_address, token_ticker)
        return data.balance


class FeeCollectorContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getAmountOut": self._get_int_view,
            "getEquivalent": self._get_int_view,
            "updateAndGetSafePrice": self._get_hex_view,
            "getLpTokenIdentifier": self._get_hex_view,
            "getTokensForGivenPosition": self._get_int_list_view,
            "getReservesAndTotalSupply": self._get_int_list_view,
        }

    def get_token_reserve(self, token_ticker: str) -> int:
        data = self.proxy.get_fungible_token_of_account(self.contract_address, token_ticker)
        return data.balance


class StakingContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getFarmTokenSupply": self._get_int_view,
            "getLastRewardBlockNonce": self._get_int_view,
            "getPerBlockRewardAmount": self._get_int_view,
            "getAnnualPercentageRewards": self._get_int_view,
            "getRewardCapacity": self._get_int_view,
            "getRewardPerShare": self._get_int_view,
            "getMinUnbondEpochs": self._get_int_view,
            "getDivisionSafetyConstant": self._get_int_view,
            "getFarmTokenId": self._get_hex_view,
            "getFarmingTokenId": self._get_hex_view,
            "getState": self._get_int_view,
        }


class MetaStakingContractDataFetcher(DataFetcher):
    def __init__(self, contract_address: Address, proxy_url: str):
        super().__init__(contract_address, proxy_url)
        self.view_handler_map = {
            "getDualYieldTokenId": self._get_hex_view,
        }


class ChainDataFetcher:
    def __init__(self, proxy_url: str):
        self.proxy = ProxyNetworkProvider(proxy_url)

    def get_tx_block_nonce(self, txhash: str) -> int:
        if txhash == "":
            print("No hash provided")
            return 0
        try:
            response = self.proxy.get_transaction(txhash)
            return response.block_nonce

        except Exception as ex:
            print("Exception encountered:", ex)
            traceback.print_exception(*sys.exc_info())
            return 0

    def get_current_block_nonce(self) -> int:
        try:
            response = self.proxy.get_network_status(1)
            return response.highest_final_nonce
        except Exception as ex:
            print("Exception encountered:", ex)
            traceback.print_exception(*sys.exc_info())
            return 0
