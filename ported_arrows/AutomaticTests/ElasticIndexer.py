import time

import requests


class ElasticIndexer:
    url: str

    def __init__(self, url: str):
        self.url = url

    def fetch_tx_status(self, hash_str: str):
        url = f"{self.url}/transactions/{hash_str}"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        request_error_codes = [404, 408, 429, 500, 504]
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            parsed = response.json()
            return parsed
        except Exception as ex:
            if response.status_code in request_error_codes:
                time.sleep(1)
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
            else:
                print(f'Exception occurred: {ex}')

    def is_tx_finalized(self, hash_str: str) -> bool:
        response = self.fetch_tx_status(hash_str)
        if ('status' in response and response['status'] == 'success' and 'pendingResults' not in response) \
                or ('status' in response and response['status'] == 'fail'):
            return True
        return False

    def wait_for_tx_finalized(self, hash_str: str):
        num_seconds_timeout = 60
        time.sleep(2)
        for _ in range(0, num_seconds_timeout):
            if self.is_tx_finalized(hash_str):
                return self.fetch_tx_status(hash_str)
            time.sleep(2)

    def get_no_transactions_per_account(self, address: str):
        url = f"{self.url}/accounts/{address}/transactions/count"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        parsed = response.json()
        return parsed

    def get_transactions_per_account(self, address: str):
        url = f"{self.url}/accounts/{address}/transactions"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        parsed = response.json()
        return parsed

    def get_address_details(self, address: str):
        url = f"{self.url}/accounts/{address}"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        parsed = response.json()
        return parsed

    def get_esdt_data(self, token_id: str):
        url = f"{self.url}/tokens/{token_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        parsed = response.json()
        return parsed

    def get_nft_data(self, token_id: str):
        url = f"{self.url}/nfts/{token_id}"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:81.0) Gecko/20100101 Firefox/81.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        parsed = response.json()
        return parsed
