import sys
from typing import List
from argparse import ArgumentParser

from deploy.dex_structure import DeployStructure
from utils.utils_tx import NetworkProviders
from utils.utils_chain import Account
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
    parser.add_argument("--deploy-tokens", required=False, default="config")   # options: clean | config
    parser.add_argument("--deploy-contracts", required=False, default="config")   # options: clean | config
    parser.add_argument("--force-start", action='store_true', required=False, default=False)   # force start all
    args = parser.parse_args(cli_args)

    deploy_structure = DeployStructure()
    deployer_account = Account(pem_file=config.DEFAULT_OWNER)

    dex_infra = DexInfrastructure(deploy_structure, deployer_account, config.DEFAULT_PROXY, config.DEFAULT_API)

    # TOKENS HANDLING
    dex_infra.deploy_structure.deploy_tokens(dex_infra.deployer_account, dex_infra.network_provider,
                                             False if args.deploy_tokens == "config" else True)

    # configure contracts and deploy them
    # DEPLOY CONTRACTS
    dex_infra.deploy_structure.deploy_structure(dex_infra.deployer_account, dex_infra.network_provider,
                                                False if args.deploy_contracts == "config" else True)

    # CONTRACTS START
    start_flag = False
    if args.deploy_contracts != "config" or args.force_start:
        start_flag = True
    dex_infra.deploy_structure.start_deployed_contracts(dex_infra.deployer_account, dex_infra.network_provider,
                                                        start_flag)

    # program closing
    # dex_infra.save_deployed_structure()
    dex_infra.deploy_structure.print_deployed_contracts()


if __name__ == "__main__":
    main(sys.argv[1:])
