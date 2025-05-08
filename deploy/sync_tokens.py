import sys
from argparse import ArgumentParser
from multiprocessing.dummy import Pool
from typing import List

import config
from deploy.tokens_tracks import BunchOfTracks
from utils.logger import get_logger
from utils.utils_chain import BunchOfAccounts
from utils.utils_chain import WrapperAddress as Address
from multiversx_sdk import ProxyNetworkProvider
from utils.errors import GenericError
logger = get_logger(__name__)


def main(cli_args: List[str]):

    parser = ArgumentParser()
    parser.add_argument("--proxy", default=config.DEFAULT_PROXY)
    parser.add_argument("--accounts", default=config.DEFAULT_OWNER)
    parser.add_argument("--tokens", default=config.get_default_tokens_file())
    parser.add_argument("--tokens-prefix", default=config.DEFAULT_TOKEN_PREFIX)

    args = parser.parse_args(cli_args)

    proxy = ProxyNetworkProvider(args.proxy)
    print(proxy.url)
    bunch_of_accounts = BunchOfAccounts.load_accounts_from_files([args.accounts])
    accounts = bunch_of_accounts.get_all()
    # sync tokens only for SC owner to optimize time
    addresses = [item.address for item in accounts]
    print(f"Will fetch tokens for {len(accounts)} users. Total: {len(addresses)} addresses.")

    tracks = BunchOfTracks(args.tokens_prefix)

    def get_for_address(address: Address):
        try:
            tokens = proxy.get_fungible_tokens_of_account(address)
            tracks.put_for_account(address, tokens)
        except GenericError as error:
            print(error)

    Pool(25).map(get_for_address, addresses)

    # tracks.put_all_tokens(proxy.get_all_tokens())
    tracks.save(args.tokens)

    print("Num all_tokens", len(tracks.get_all_tokens()))
    print("Num all entries", len(tracks.get_all_individual_assets()))


if __name__ == "__main__":
    main(sys.argv[1:])
