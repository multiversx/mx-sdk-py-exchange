import json
import os
import sys
from argparse import ArgumentParser

from typing import Dict, Any, Tuple, List

from utils.utils_generic import print_test_step_fail, print_test_step_pass, print_warning
from erdpy.proxy.http_facade import do_get


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--left-prefix", required=True)
    parser.add_argument("--right-prefix", required=True)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args(cli_args)

    report_key_files_compare(args.folder, args.left_prefix, args.right_prefix, args.verbose)


def get_account_keys_online(address: str, proxy_url: str, block_number: int = 0, with_save_in: str = "") -> Dict[str, Any]:
    if block_number == 0:
        url = f"{proxy_url}/address/{address}/keys"
    else:
        url = f"{proxy_url}/address/{address}/keys?blockNonce={block_number}"

    response = do_get(url)
    keys = response.get("pairs", dict())

    if keys and with_save_in:
        dir_path = os.path.dirname(with_save_in)
        if not os.path.exists(dir_path):
            os.mkdir(dir_path)

        with open(with_save_in, 'w') as state_writer:
            json.dump(keys, state_writer, indent=4)
            print(f'Dumped the retrieved contact state in: {with_save_in}')

    return keys


def compare_keys(left_state: dict, right_state: dict) -> Tuple[bool, dict, dict, dict, dict]:
    """
    Returns:
        identical: True/False
        keys & values only in left file
        keys & values only in right file
        common keys with different values
        common keys with identical values
    """
    keys_in_left = {}
    common_keys_different_values = {}
    common_keys = {}
    identical = False

    for left_key, left_value in left_state.items():
        if left_key in right_state:
            right_value = right_state[left_key]
            if left_value != right_value:
                # different values on key
                common_keys_different_values[left_key] = [left_value, right_value]
            else:
                # same key and value
                common_keys[left_key] = left_value
            # remove found key from right
            right_state.pop(left_key)
        else:
            # key only in left
            keys_in_left[left_key] = left_value

    # remaining keys in right are unique to right only

    if len(keys_in_left) == len(right_state) == len(common_keys_different_values) == 0:
        identical = True

    return identical, keys_in_left, right_state, common_keys_different_values, common_keys


def report_key_files_compare(folder_path: str, left_prefix: str, right_prefix: str, verbose: bool = False):
    compare_count = 0
    if not os.path.exists(folder_path):
        print_test_step_fail(f"Given folder path doesn't exist.")

    for file in os.listdir(folder_path):
        if f"{left_prefix}" not in file:
            continue

        sub_name = file[len(left_prefix):]
        right_file = f"{right_prefix}{sub_name}"
        if not os.path.exists(os.path.join(folder_path, right_file)):
            continue

        with open(os.path.join(folder_path, file)) as reader:
            left_state = json.load(reader)
        with open(os.path.join(folder_path, right_file)) as reader:
            right_state = json.load(reader)

        identical, keys_in_left, keys_in_right, common_keys_diff_values, common_keys = compare_keys(left_state,
                                                                                                    right_state)

        if identical:
            print_test_step_pass(f"\n{file} and {right_file} are identical.")
        else:
            print_test_step_fail(f"\n{file} and {right_file} are not identical.")
            if verbose:
                if keys_in_left:
                    for key, value in keys_in_left.items():
                        print_warning(f"Data only in {left_prefix}: {key}: {value}")
                        print(f"Decoded key: {bytearray.fromhex(key).decode('iso-8859-1')}")
                if keys_in_right:
                    for key, value in keys_in_right.items():
                        print_warning(f"Data only in {right_prefix}: {key}: {value}")
                        print(f"Decoded key: {bytearray.fromhex(key).decode('iso-8859-1')}")
                if common_keys_diff_values:
                    for key, value in common_keys_diff_values.items():
                        print_warning(f"Common key with different values: {key}: {value}")
                        print(f"Decoded key: {bytearray.fromhex(key).decode('iso-8859-1')}")

        compare_count += 1

    print(f"\nFound and compared {compare_count} account state file pairs.")


if __name__ == "__main__":
    main(sys.argv[1:])
