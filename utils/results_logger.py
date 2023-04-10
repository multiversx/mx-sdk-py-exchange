from pathlib import Path
from typing import Any

from multiversx_sdk_network_providers import ProxyNetworkProvider
from contracts.farm_contract import FarmContract
from utils.contract_data_fetchers import FarmContractDataFetcher
from utils.utils_chain import WrapperAddress as Address, get_all_token_nonces_details_for_account
from utils.utils_generic import ensure_folder, dump_out_json


class AccountSnapshotLogData:

    def __init__(self, user_address: str, token_list: list, proxy: ProxyNetworkProvider):
        self.tokens = []

        for token in token_list:
            self.tokens.append(get_all_token_nonces_details_for_account(token, user_address, proxy))


class FarmContractSnapshotLogData:
    farm_token_supply: int
    per_block_rewards: int
    last_reward_block_nonce: int
    rewards_per_share: int
    rewards_reserve: int
    division_safety_constant: int
    undistributed_fees: int
    current_block_fee: int

    def __init__(self, contract_address: str, proxy: ProxyNetworkProvider):
        data_fetcher = FarmContractDataFetcher(Address(contract_address), proxy_url=proxy.url)
        self.farm_token_supply = data_fetcher.get_data("getFarmTokenSupply")
        self.per_block_rewards = data_fetcher.get_data("getPerBlockRewardAmount")
        self.last_reward_block_nonce = data_fetcher.get_data("getLastRewardBlockNonce")
        self.rewards_per_share = data_fetcher.get_data("getRewardPerShare")
        self.rewards_reserve = data_fetcher.get_data("getRewardReserve")
        self.division_safety_constant = data_fetcher.get_data("getDivisionSafetyConstant")
        # self.undistributed_fees = data_fetcher.get_data("getUndistributedFees")
        # self.current_block_fee = data_fetcher.get_data("getCurrentBlockFee")


class FarmEventResultLogData:
    # TODO (longterm): individual members can be replaced with a freely expandable list for scalability and reusability
    event_name: str
    tx_hash: str
    event: dict
    account: str
    farm: dict
    account_pre_snapshot: dict
    account_post_snapshot: dict
    contract_post_snapshot: dict
    # internal usage data
    _farm: FarmContract
    _token_list: list

    # TODO (longterm): all following methods can be abstracted and ported towards "subscriptable" event model
    def set_generic_event_data(self, event: Any, account_address: str, farm_identity: FarmContract):
        self.event_name = type(event).__name__
        self.event = event.__dict__
        self.account = account_address
        self.farm = farm_identity.__dict__
        self._farm = farm_identity
        # TODO: add the reward token in here
        self._token_list = [farm_identity.farmingToken, farm_identity.farmToken]

    def set_pre_event_data(self, proxy: ProxyNetworkProvider):
        self.account_pre_snapshot = AccountSnapshotLogData(self.account, self._token_list, proxy).__dict__

    def set_post_event_data(self, tx_hash: str, proxy: ProxyNetworkProvider):
        self.tx_hash = tx_hash
        self.account_post_snapshot = AccountSnapshotLogData(self.account, self._token_list, proxy).__dict__
        self.contract_post_snapshot = FarmContractSnapshotLogData(self._farm.address, proxy).__dict__

    def clear_internal_data(self):
        self.__delattr__("_farm")
        self.__delattr__("_token_list")


class ResultsLogger:
    def __init__(self, filename: str):
        self.data_dump = []
        self.filename = filename
        # added the flag below to stop logger errors
        self.active = False


    def add_event_log(self, log_event: FarmEventResultLogData):
        # TODO: replace log_event type hint with EventResultLogData abstract
        if self.active:
            log_event.clear_internal_data()
            self.data_dump.append(log_event.__dict__)
            self.__save_backup_log(log_event.__dict__)

    def save_log(self):
        if self.active:
            print(f"Saving results log in file: {self.filename}")

            # out_filename = filename + "_" + str(run_time.day) + str(run_time.hour) + str(run_time.minute) + str(run_time.second)
            out_filename = self.filename
            filepath = "arrows/stress/dex/results/" + out_filename

            ensure_folder(Path(filepath).parent)
            with open(filepath, "a") as f:
                dump_out_json(self.data_dump, f)

    def __save_backup_log(self, log_event: dict):
        if self.active:
            filepath = f"arrows/stress/dex/results/{self.filename}_backup.json"
            ensure_folder(Path(filepath).parent)
            with open(filepath, "a") as f:
                dump_out_json(log_event, f)


"""Procedure to use results logger"
- instantiate ResultsLogger obj at program start
- create a FarmEventResultLogData obj in event that needs to be logged
- FarmEventResultLogData.set_generic_event_data at init
- FarmEventResultLogData.set_pre_event_data before event execution
- FarmEventResultLogData.set_post_event_data after event execution
- ResultsLogger.add_event_log(FarmEventResultLogData) after event execution
- ResultsLogger.save_log before program end (or once in a while)
"""