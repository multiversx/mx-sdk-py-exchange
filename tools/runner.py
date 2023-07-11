import sys
from typing import List
from argparse import ArgumentParser
from tools.runners import pair_runner, farm_runner, \
    staking_runner, metastaking_runner, router_runner, \
    proxy_runner, locked_asset_runner


def main(cli_args: List[str]):
    parser = ArgumentParser()
    subparser = parser.add_subparsers(dest='command')
    pair = subparser.add_parser('pair', help='handle pairs')
    farms = subparser.add_parser('farms', help='handle farms')
    stakings = subparser.add_parser('stakings', help='handle stakings')
    metastakings = subparser.add_parser('metastakings', help='handle metastakings')
    router = subparser.add_parser('router', help='handle router')
    proxy = subparser.add_parser('proxy', help='handle proxy')
    locked_asset = subparser.add_parser('locked-asset', help='handle locked asset')

    pair_runner.add_parsed_arguments(pair)
    farm_runner.add_parsed_arguments(farms)
    staking_runner.add_parsed_arguments(stakings)
    metastaking_runner.add_parsed_arguments(metastakings)
    router_runner.add_parsed_arguments(router)
    proxy_runner.add_parsed_arguments(proxy)
    locked_asset_runner.add_parsed_arguments(locked_asset)

    parser.add_help = True
    args = parser.parse_args(cli_args)

    if args.command == 'pair':
        pair_runner.handle_command(args)
    elif args.command == 'farms':
        farm_runner.handle_command(args)
    elif args.command == 'stakings':
        staking_runner.handle_command(args)
    elif args.command == 'metastakings':
        metastaking_runner.handle_command(args)
    elif args.command == 'router':
        router_runner.handle_command(args)
    elif args.command == 'proxy':
        proxy_runner.handle_command(args)
    elif args.command == 'locked_asset':
        locked_asset_runner.handle_command(args)
    elif args.command == 'help':
        parser.print_help()


if __name__ == '__main__':
    main(sys.argv[1:])
