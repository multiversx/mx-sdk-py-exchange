import sys, requests, re
import traceback
from argparse import ArgumentParser
from typing import List

from utils.utils_chain import decode_merged_attributes, base64_to_hex

PROXY = "https://testnet-gateway.elrond.com"
API = "https://testnet-api.elrond.com"


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--type", required=False)                   # needed in case of --attrs
    parser.add_argument("--attrs", required=False, default="")      # optional, either this or --token
    parser.add_argument("--encoding", default="base64")
    parser.add_argument("--token", required=False, default="")      # optional, either this or --attrs
    args = parser.parse_args(cli_args)

    # export PYTHONPATH=.
    # python3 arrows/stress/dex/manual_tools.py --type=staked --attrs=AAAABwQh8UGLGBkAAAAAAAPY5gAAAAAAAAAIlfxdqMQuIxQ=
    # python3 arrows/stress/dex/manual_tools.py --token=RIDESTAKE-1e7cef-6422

    attributes_schema_staked_tokens = {
        'reward_per_share': 'biguint',
        'compounded_reward': 'biguint',
        'current_farm_amount': 'biguint',
    }

    attributes_schema_unstaked_tokens = {
        'unlock_epoch': 'u64',
    }

    attributes_schema_proxy_staked_tokens = {
        'lp_farm_token_nonce': 'u64',
        'lp_farm_token_amount': 'biguint',
        'staking_farm_token_nonce': 'u64',
        'staking_farm_token_amount': 'biguint',
    }

    attributes_schema_farmv12_tokens = {
        'rewards_per_share': 'biguint',
        'entering_epoch': 'u64',
        'original_entering_epoch': 'u64',
        'apr_multiplier': 'u8',
        'locked_rewards': 'u8',
        'initial_farming_amount': 'biguint',
        'compounded_rewards': 'biguint',
        'current_farm_amount': 'biguint',
    }

    attributes_schema_farmv14_tokens = {
        'rewards_per_share': 'biguint',
        'entering_epoch': 'u64',
        'original_entering_epoch': 'u64',
        'apr_multiplier': 'u8',
        'locked_rewards': 'u8',
        'initial_farming_amount': 'biguint',
        'compounded_rewards': 'biguint',
        'current_farm_amount': 'biguint',
    }

    esdt_token_payment_schema = {
        'token_type': 'u8',
        'token_identifier': 'string',
        'token_nonce': 'u64',
        'amount': 'biguint',
    }

    simple_locked_token_schema = {
        'token_identifier': 'string',
        'original_token_nonce': 'u64',
        'unlock_epoch': 'u64',
    }

    simple_locked_lp_schema = {
        'lp_token_id': 'string',
        'first_token_id': 'string',
        'first_token_locked_nonce': 'u64',
        'second_token_id': 'string',
        'second_token_locked_nonce': 'u64',
    }

    simple_locked_farm_schema = {
        'farm_type': 'u8',
        'farm_token_id': 'string',
        'farm_token_nonce': 'u64',
        'farming_token_id': 'string',
        'farming_token_locked_nonce': 'u64',
    }

    launchpad_epoch_config = {
        'confirmation': 'u64',
        'winners': 'u64',
        'claim': 'u64',
    }

    unlock_schedule_schema = {
        'unlock_schedule_list': {
            'unlock_epoch': 'u64',
            'unlock_percent': 'u64'
        },
        'merged': 'u8'
    }

    tokens_schema_mapper = {
        "RIDESTAKE-1e7cef": attributes_schema_staked_tokens,
        "SWEB-d9bfe2": attributes_schema_staked_tokens,
        "METARIDE-4bd193": attributes_schema_proxy_staked_tokens,
        "METARIDELK-b28dc3": attributes_schema_proxy_staked_tokens,
        "SLKTK1-475419": simple_locked_token_schema,
        "LKLPS1-7ad725": simple_locked_lp_schema,
        "LKFARM-a74e31": simple_locked_farm_schema,
        "EGLDMEXFL-ef2065": attributes_schema_farmv14_tokens,
    }

    decoded_attrs = {}
    attributes_schema = {}
    if args.type == "staked":
        attributes_schema = attributes_schema_staked_tokens
    if args.type == "proxystaked":
        attributes_schema = attributes_schema_proxy_staked_tokens
    if args.type == "unstaked":
        attributes_schema = attributes_schema_unstaked_tokens
    if args.type == "farmv12":
        attributes_schema = attributes_schema_farmv12_tokens
    if args.type == "farmv14":
        attributes_schema = attributes_schema_farmv14_tokens
    if args.type == "tokenpayment":
        attributes_schema = esdt_token_payment_schema
    if args.type == "simplelocked":
        attributes_schema = simple_locked_token_schema
    if args.type == "simplelockedlp":
        attributes_schema = simple_locked_lp_schema
    if args.type == "simplelockedfarm":
        attributes_schema = simple_locked_farm_schema
    if args.type == "launchpadconfig":
        attributes_schema = launchpad_epoch_config
    if args.type == "lockedtokens":
        attributes_schema = unlock_schedule_schema

    attrs = ""
    # handling for passed attributes
    if args.attrs != "":
        if args.encoding == "hex":
            attrs = args.attrs
        else:
            attrs = base64_to_hex(args.attrs)

    # handling for fetched token attributes directly from network
    if args.token != "":
        try:
            response = requests.get(f"{API}/nfts/{args.token}").json()
            if "attributes" in response:
                attrs = base64_to_hex(response["attributes"])
                token_ticker = re.match('[^-]*-[^-]*', args.token).group(0)
                attributes_schema = tokens_schema_mapper[token_ticker]
            else:
                print("given token not found or something's not robust enough in this piece of code (dooooh)")
                return
        except Exception as ex:
            print(ex)
            traceback.print_exception(*sys.exc_info())

    if attributes_schema != {}:
        decoded_attrs = decode_merged_attributes(attrs, attributes_schema)
        print(decoded_attrs)
    else:
        print(f"Unknown type given.")
    # TODO: replace input array with attributes schema


if __name__ == "__main__":
    main(sys.argv[1:])
