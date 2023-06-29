import json
from utils.logger import get_logger

logger = get_logger(__name__)


def load_json_as_dict(json_file: str) -> json:
    with open(json_file, 'r') as file:
        json_dict = json.load(file)

    return json_dict


def populate_list(json_file: str, key: str) -> list:
    json_dict = load_json_as_dict(json_file)
    values = []

    if key not in json_dict:
        logger.warning(f"Structure definition for {key} not found in {json_file}")
        return values

    for i in range(len(json_dict[key])):
        values.append(json_dict[key][i])

    return values


def get_token_prefix(json_file: str) -> str:
    json_dict = load_json_as_dict(json_file)

    prefix = json_dict['token']['token_prefix']
    return prefix


def get_number_of_tokens(json_file: str) -> int:
    json_dict = load_json_as_dict(json_file)

    number_of_tokens = json_dict['token']['number_of_tokens']
    return number_of_tokens
