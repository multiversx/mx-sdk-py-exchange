import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from multiversx_sdk import Address

from utils.utils_chain import Account
from utils.errors import KnownError
from utils.utils_generic import dump_out_json, read_json_file

HTTP_REQUEST_TIMEOUT = 408
HTTP_SUCCESS = 200

logger = logging.getLogger("cli.contracts.verifier")


class ContractVerificationRequest:
    def __init__(
        self,
        contract: Address,
        source_code: Dict[str, Any],
        signature: bytes,
        docker_image: str,
        contract_variant: Optional[str]
    ) -> None:
        self.contract = contract
        self.source_code = source_code
        self.signature = signature
        self.docker_image = docker_image
        self.contract_variant = contract_variant

    def to_dictionary(self) -> Dict[str, Any]:
        return {
            "signature": self.signature.hex(),
            "payload": {
                "contract": self.contract.bech32(),
                "dockerImage": self.docker_image,
                "sourceCode": self.source_code,
                "contractVariant": self.contract_variant
            }
        }


class ContractVerificationPayload:
    def __init__(self, contract: Address, source_code: Dict[str, Any], docker_image: str, contract_variant: Optional[str]) -> None:
        self.contract = contract
        self.source_code = source_code
        self.docker_image = docker_image
        self.contract_variant = contract_variant

    def serialize(self) -> str:
        payload = {
            "contract": self.contract.to_bech32(),
            "dockerImage": self.docker_image,
            "sourceCode": self.source_code,
            "contractVariant": self.contract_variant
        }

        return json.dumps(payload, separators=(',', ':'))


def trigger_contract_verification(
        packaged_source: Path,
        owner: Account,
        contract: Address,
        verifier_url: str,
        docker_image: str,
        contract_variant: Optional[str]):
    source_code = read_json_file(packaged_source)

    payload = ContractVerificationPayload(contract, source_code, docker_image, contract_variant).serialize()
    signature = _create_request_signature(owner, contract, payload.encode())
    contract_verification = ContractVerificationRequest(contract, source_code, signature, docker_image, contract_variant)

    request_dictionary = contract_verification.to_dictionary()

    url = f"{verifier_url}/verifier"
    status_code, message, data = _do_post(url, request_dictionary)

    if status_code == HTTP_REQUEST_TIMEOUT:
        task_id = data.get("taskId", "")

        if task_id:
            query_status_with_task_id(verifier_url, task_id)
        else:
            dump_out_json(data)
    elif status_code != HTTP_SUCCESS:
        dump_out_json(data)
        raise KnownError(f"Cannot verify contract: {message}")
    else:
        status = data.get("status", "")
        if status:
            logger.info(f"Task status: {status}")
            dump_out_json(data)
        else:
            task_id = data.get("taskId", "")
            query_status_with_task_id(verifier_url, task_id)


def _create_request_signature(account: Account, contract_address: Address, request_payload: bytes) -> bytes:
    hashed_payload: str = hashlib.sha256(request_payload).hexdigest()
    raw_data_to_sign = f"{contract_address.to_bech32()}{hashed_payload}"

    signature_hex = account.sign_message(raw_data_to_sign.encode())
    signature = bytes.fromhex(signature_hex)

    return signature


def query_status_with_task_id(url: str, task_id: str, interval: int = 10):
    logger.info(f"Please wait while we verify your contract. This may take a while.")
    old_status = ""

    while True:
        _, _, response = _do_get(f"{url}/tasks/{task_id}")
        status = response.get("status", "")

        if status == "finished":
            logger.info(f"Verification finished!")
            dump_out_json(response)
            break
        elif status != old_status:
            logger.info(f"Task status: {status}")
            dump_out_json(response)
            old_status = status

        time.sleep(interval)


def _do_post(url: str, payload: Any) -> Tuple[int, str, Dict[str, Any]]:
    logger.debug(f"_do_post() to {url}")
    response = requests.post(url, json=payload)

    try:
        data = response.json()
        message = data.get("message", "")
        return response.status_code, message, data
    except Exception as error:
        logger.error(f"Erroneous response from {url}: {response.text}")
        raise KnownError(f"Cannot parse response from {url}", error)


def _do_get(url: str) -> Tuple[int, str, Dict[str, Any]]:
    logger.debug(f"_do_get() from {url}")
    response = requests.get(url)

    try:
        data = response.json()
        message = data.get("message", "")
        return response.status_code, message, data
    except Exception as error:
        logger.error(f"Erroneous response from {url}: {response.text}")
        raise KnownError(f"Cannot parse response from {url}", error)
