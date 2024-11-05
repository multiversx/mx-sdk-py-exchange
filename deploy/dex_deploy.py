import sys
from typing import List
from argparse import ArgumentParser

from deploy.dex_structure import DeployStructure, DeployStructureArguments
from utils.utils_tx import NetworkProviders
from utils.utils_chain import Account, WrapperAddress as Address
import config


class DexInfrastructure:
    def __init__(self, deploy_structure: DeployStructure, deployer: Account,
                 proxy_url: str, api_url: str):
        self.deploy_structure = deploy_structure
        self.deployer_account = deployer
        self.network_provider = NetworkProviders(api_url, proxy_url)

        self.deployer_account.sync_nonce(self.network_provider.proxy)


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--deploy-tokens", required=False, default="config", help="command to deploy tokens: clean | config")   # options: clean | config
    parser.add_argument("--deploy-contracts", required=False, default="config", help="command to deploy contracts: clean | config")   # options: clean | config
    parser.add_argument("--force-start", action='store_true', required=False, default=False, help="force start of the deployed contracts")   # force start all
    DeployStructureArguments.add_clean_contract_deploy_arguments(parser)
    args = parser.parse_args(cli_args)

    deploy_structure = DeployStructure()
    deployer_account = Account.from_file(config.DEFAULT_OWNER)
    if config.DEX_OWNER_ADDRESS:  # manual override only for shadowfork
        deployer_account.address = Address(config.DEX_OWNER_ADDRESS)

    dex_infra = DexInfrastructure(deploy_structure, deployer_account, config.DEFAULT_PROXY, config.DEFAULT_API)

    # TOKENS HANDLING
    dex_infra.deploy_structure.deploy_tokens(dex_infra.deployer_account, dex_infra.network_provider,
                                             False if args.deploy_tokens == "config" else True)

    # configure contracts and deploy them
    cli_deployed_contracts_list = [arg for arg, value in vars(args).items() if value is True]
    # DEPLOY CONTRACTS
    dex_infra.deploy_structure.deploy_structure(dex_infra.deployer_account, dex_infra.network_provider,
                                                False if args.deploy_contracts == "config" else True,
                                                cli_deployed_contracts_list)

    # CONTRACTS START
    start_flag = False
    if args.deploy_contracts != "config" or args.force_start:
        start_flag = True
    dex_infra.deploy_structure.start_deployed_contracts(dex_infra.deployer_account, dex_infra.network_provider,
                                                        start_flag, cli_deployed_contracts_list)

    # program closing
    # dex_infra.save_deployed_structure()
    dex_infra.deploy_structure.print_deployed_contracts()


if __name__ == "__main__":
    main(sys.argv[1:])
