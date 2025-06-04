from typing import List, Dict, Any
import time
from multiversx_sdk import GenericError, ProxyNetworkProvider
import requests
from multiversx_sdk.core.constants import METACHAIN_ID


class NetworkStatusOnShard:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.current_round = data.get("erd_current_round", 0)
        self.current_epoch = data.get("erd_epoch_number", 0)
        self.current_nonce = data.get("erd_nonce", 0)


class ProxyExtension(ProxyNetworkProvider):
    def do_query_with_caller(self, sc_address: str, caller_adress: str, function_name: str) -> List[str]:
        payload = {
            "scAddress": sc_address,
            "caller": caller_adress,
            "funcName": function_name
        }

        result = self.do_post_generic('/vm-values/query', payload)
        return_data = result['data']
        value = return_data['returnData']
        return value

    def do_post(self, endpoint, payload):
        url = self.url + endpoint
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            parsed = response.json()
            return self.get_data(parsed, url)
        except requests.HTTPError as err:
            error_data = self._extract_error_from_response(err.response)
            raise Exception(url, error_data)
        except requests.ConnectionError as err:
            raise Exception(url, err)
        except Exception as err:
            raise Exception(url, err)

    def get_network_status(self, shard_id) -> NetworkStatusOnShard:
        if shard_id == "metachain":
            metrics = self.get_network_status(METACHAIN_ID)
        else:
            metrics = self.get_network_status(shard_id)
        result = NetworkStatusOnShard(metrics)
        return result

    def wait_for_epoch(self, target_epoch, idle_time=30):
        status = self.get_network_status(0)
        while status.current_epoch < target_epoch:
            status = self.get_network_status(0)
            time.sleep(idle_time)

    def wait_for_nonce_in_shard(self, shard_id: int, target_nonce: int, idle_time=6):
        status = self.get_network_status(shard_id)
        while status.current_nonce < target_nonce:
            status = self.get_network_status(shard_id)
            time.sleep(idle_time)

    def wait_epochs(self, num_epochs, idle_time=30):
        status = self.get_network_status(0)
        next_epoch = status.current_epoch + num_epochs
        while status.current_epoch < next_epoch:
            status = self.get_network_status(0)
            time.sleep(idle_time)

    def get_round(self):
        status = self.get_network_status(0)
        return status.current_round

    def get_heartbeats_info(self) -> List[dict]:
        heartbeat_info = []
        proxy = ProxyNetworkProvider(self.url)
        response = proxy.do_get_generic("node/heartbeatstatus")
        heartbeats = response.to_dictionary()['heartbeats']
        for node_heartbeat in heartbeats:
            heartbeat_info.append(node_heartbeat)
        return heartbeat_info

    def get_validators_statistics_raw(self) -> List[dict]:
        proxy = ProxyNetworkProvider(self.url)
        response = proxy.do_get_generic("validator/statistics")
        statistics = response.to_dictionary()['statistics']
        return statistics

    @staticmethod
    def get_data(parsed, url):
        err = parsed.get("error")
        code = parsed.get("code")

        if not err and code == "successful":
            return parsed.get("data", dict())

        raise GenericError(url, f"code:{code}, error: {err}")

    @staticmethod
    def _extract_error_from_response(response):
        try:
            return response.json()
        except Exception:
            return response.text
