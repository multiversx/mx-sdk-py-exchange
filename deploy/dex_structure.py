import time
from pathlib import Path
from typing import List, Type, Dict, Optional

import config
from contracts.fees_collector_contract import FeesCollectorContract
from contracts.proxy_deployer_contract import ProxyDeployerContract
from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from contracts.unstaker_contract import UnstakerContract
from deploy import sync_tokens, issue_tokens
from deploy.tokens_tracks import BunchOfTracks
from utils.contract_data_fetchers import PairContractDataFetcher, PriceDiscoveryContractDataFetcher, \
    SimpleLockContractDataFetcher, LockedAssetContractDataFetcher, FarmContractDataFetcher, StakingContractDataFetcher, \
    MetaStakingContractDataFetcher, ProxyContractDataFetcher, SimpleLockEnergyContractDataFetcher
from contracts.builtin_contracts import ESDTContract
from contracts.farm_contract import FarmContract
from contracts.locked_asset_contract import LockedAssetContract
from contracts.egld_wrap_contract import EgldWrapContract
from contracts.pair_contract import PairContract
from contracts.price_discovery_contract import PriceDiscoveryContract
from contracts.router_contract import RouterContract
from contracts.simple_lock_contract import SimpleLockContract
from contracts.contract_identities import FarmContractVersion, DEXContractInterface, \
    RouterContractVersion, PairContractVersion, ProxyContractVersion, StakingContractVersion, MetaStakingContractVersion
from contracts.metastaking_contract import MetaStakingContract
from contracts.staking_contract import StakingContract
from contracts.dex_proxy_contract import DexProxyContract
from utils.utils_tx import NetworkProviders
from utils.utils_chain import hex_to_string
from utils.utils_chain import Account, WrapperAddress as Address
from utils.utils_generic import write_json_file, read_json_file, log_step_fail, log_step_pass, \
    log_warning
from deploy import populate_deploy_lists


class ContractStructure:
    def __init__(self, label: str, contract_class: Type[DEXContractInterface], bytecode_path: str, deploy_function,
                 deploy_clean: bool = True):
        self.label = label
        self.contract_class = contract_class
        self.deploy_structure_list = populate_deploy_lists.populate_list(config.DEPLOY_STRUCTURE_JSON, label)
        self.deployed_contracts: List[contract_class] = []
        self.deploy_clean = deploy_clean
        self.deploy_function = deploy_function
        self.bytecode = bytecode_path

    def save_deployed_contracts(self):
        if self.deployed_contracts:
            dump = []
            for contract in self.deployed_contracts:
                dump.append(contract.get_config_dict())

            filepath = config.DEFAULT_CONFIG_SAVE_PATH / f"deployed_{self.label}.json"
            Path(config.DEFAULT_CONFIG_SAVE_PATH).mkdir(parents=True, exist_ok=True)

            write_json_file(filepath, dump)
            log_step_pass(f"Saved deployed {self.label} contracts.")

    def get_saved_deployed_contracts(self) -> list:
        contracts_list = []
        filepath = config.DEFAULT_CONFIG_SAVE_PATH / f"deployed_{self.label}.json"
        if not Path(filepath).is_file():    # no config available
            return []

        retrieved_contract_configs = read_json_file(filepath)

        for contract_config in retrieved_contract_configs:
            contract = self.contract_class.load_config_dict(contract_config)
            contracts_list.append(contract)

        return contracts_list

    def get_deployed_contract_by_address(self, address: str) -> DEXContractInterface or None:
        found_contract = None
        for contract in self.deployed_contracts:
            if contract.address == address:
                found_contract = contract
                break

        return found_contract

    def get_deployed_contract_by_index(self, index: int) -> DEXContractInterface or None:
        if index+1 > len(self.deployed_contracts):
            return None
        return self.deployed_contracts[index]

    def load_deployed_contracts(self):
        contracts_list = self.get_saved_deployed_contracts()
        if len(self.deploy_structure_list) == len(contracts_list):
            self.deployed_contracts = contracts_list
            log_step_pass(f"Loaded {len(contracts_list)} {self.label}.")
            return

        log_step_fail(f"No contracts fetched for: {self.label}; "
                             f"Either no save available or mismatch between deploy structure and loaded contracts.")

    def print_deployed_contracts(self):
        log_step_pass(f"{self.label}:")
        for contract in self.deployed_contracts:
            contract.print_contract_info()


class DeployStructure:
    def __init__(self):
        self.token_prefix = populate_deploy_lists.get_token_prefix(config.DEPLOY_STRUCTURE_JSON)
        self.number_of_tokens = populate_deploy_lists.get_number_of_tokens(config.DEPLOY_STRUCTURE_JSON)
        self.tokens = []    # will be filled with tokens on network
        self.esdt_contract = ESDTContract(config.TOKENS_CONTRACT_ADDRESS)

        self.contracts: Dict[str, ContractStructure] = {
            config.EGLD_WRAPS:
                ContractStructure(config.EGLD_WRAPS, EgldWrapContract, config.EGLD_WRAP_BYTECODE_PATH,
                                  self.egld_wrap_deploy, False),
            config.LOCKED_ASSETS:
                ContractStructure(config.LOCKED_ASSETS, LockedAssetContract, config.LOCKED_ASSET_FACTORY_BYTECODE_PATH,
                                  self.locked_asset_deploy, False),
            config.PROXIES:
                ContractStructure(config.PROXIES, DexProxyContract, config.PROXY_BYTECODE_PATH,
                                  self.proxy_deploy, False),
            config.SIMPLE_LOCKS:
                ContractStructure(config.SIMPLE_LOCKS, SimpleLockContract, config.SIMPLE_LOCK_BYTECODE_PATH,
                                  self.simple_lock_deploy, False),
            config.SIMPLE_LOCKS_ENERGY:
                ContractStructure(config.SIMPLE_LOCKS_ENERGY, SimpleLockEnergyContract, config.SIMPLE_LOCK_ENERGY_BYTECODE_PATH,
                                  self.simple_lock_energy_deploy, False),
            config.FEES_COLLECTORS:
                ContractStructure(config.FEES_COLLECTORS, FeesCollectorContract, config.FEES_COLLECTOR_BYTECODE_PATH,
                                  self.fees_collector_deploy, False),
            config.UNSTAKERS:
                ContractStructure(config.UNSTAKERS, UnstakerContract, config.UNSTAKER_BYTECODE_PATH,
                                  self.token_unstake_deploy, False),
            config.PROXIES_V2:
                ContractStructure(config.PROXIES_V2, DexProxyContract, config.PROXY_V2_BYTECODE_PATH,
                                  self.proxy_deploy, False),
            config.ROUTER:
                ContractStructure(config.ROUTER, RouterContract, config.ROUTER_BYTECODE_PATH,
                                  self.router_deploy, False),
            config.ROUTER_V2:
                ContractStructure(config.ROUTER_V2, RouterContract, config.ROUTER_V2_BYTECODE_PATH,
                                  self.router_deploy, False),
            config.PAIRS:
                ContractStructure(config.PAIRS, PairContract, config.PAIR_BYTECODE_PATH,
                                  self.pool_deploy_from_router, False),
            config.PAIRS_V2:
                ContractStructure(config.PAIRS_V2, PairContract, config.PAIR_V2_BYTECODE_PATH,
                                  self.pool_deploy_from_router, False),
            config.FARMS_COMMUNITY:
                ContractStructure(config.FARMS_COMMUNITY, FarmContract, config.FARM_COMMUNITY_BYTECODE_PATH,
                                  self.farm_community_deploy, False),
            config.FARMS_UNLOCKED:
                ContractStructure(config.FARMS_UNLOCKED, FarmContract, config.FARM_BYTECODE_PATH,
                                  self.farm_deploy, False),
            config.FARMS_LOCKED:
                ContractStructure(config.FARMS_LOCKED, FarmContract, config.FARM_LOCKED_BYTECODE_PATH,
                                  self.farm_deploy, False),
            config.PROXY_DEPLOYERS:
                ContractStructure(config.PROXY_DEPLOYERS, ProxyDeployerContract, config.FARM_DEPLOYER_BYTECODE_PATH,
                                  self.proxy_deployer_deploy, False),
            config.FARMS_V2:
                ContractStructure(config.FARMS_V2, FarmContract, config.FARM_V2_BYTECODE_PATH,
                                  self.farm_boosted_deploy, False),  # self.farm_deploy_from_proxy_deployer, True),
            config.PRICE_DISCOVERIES:
                ContractStructure(config.PRICE_DISCOVERIES, PriceDiscoveryContract, config.PRICE_DISCOVERY_BYTECODE_PATH,
                                  self.price_discovery_deploy, False),
            config.STAKINGS:
                ContractStructure(config.STAKINGS, StakingContract, config.STAKING_BYTECODE_PATH,
                                  self.staking_deploy, False),
            config.STAKINGS_V2:
                ContractStructure(config.STAKINGS_V2, StakingContract, config.STAKING_V2_BYTECODE_PATH,
                                  self.staking_deploy, False),
            config.STAKINGS_BOOSTED:
                ContractStructure(config.STAKINGS_BOOSTED, StakingContract, config.STAKING_V3_BYTECODE_PATH,
                                  self.staking_deploy, False),
            config.METASTAKINGS:
                ContractStructure(config.METASTAKINGS, MetaStakingContract, config.STAKING_PROXY_BYTECODE_PATH,
                                  self.metastaking_deploy, False),
            config.METASTAKINGS_V2:
                ContractStructure(config.METASTAKINGS_V2, MetaStakingContract, config.STAKING_PROXY_V2_BYTECODE_PATH,
                                  self.metastaking_deploy, False),
            config.METASTAKINGS_BOOSTED:
                ContractStructure(config.METASTAKINGS_BOOSTED, MetaStakingContract, config.STAKING_PROXY_V3_BYTECODE_PATH,
                                  self.metastaking_deploy, False)
        }

    # main entry method to deploy tokens (either deploy fresh ones or reuse existing ones)
    def deploy_tokens(self, deployer_account: Account, network_provider: NetworkProviders,
                      clean_deploy_override: bool):
        if not clean_deploy_override:
            if not self.load_deployed_tokens():
                return
        else:
            # get current tokens, see if they satisfy the request
            sync_tokens.main(["--tokens-prefix", self.token_prefix])
            tracks = BunchOfTracks(self.token_prefix).load(config.get_default_tokens_file())

            # issue tokens if necessary
            if len(tracks.accounts_by_token) < self.number_of_tokens:
                token_hashes = []
                for i in range(self.number_of_tokens - len(tracks.accounts_by_token)):
                    hashes = issue_tokens.main(["--tokens-prefix", self.token_prefix, "--yes"])
                    token_hashes.extend(hashes)

                for txhash in token_hashes:
                    network_provider.check_complex_tx_status(txhash)

                time.sleep(40)

                # get tokens, save them in offline json then load them here
                sync_tokens.main(["--tokens-prefix", self.token_prefix])
                tracks = tracks.load(config.get_default_tokens_file())

            # retrieve from list of tuples (holding address, token)
            self.load_tokens_from_individual_asset_tracks(tracks.get_all_individual_assets())
            self.save_deployed_tokens()

    def load_tokens_from_individual_asset_tracks(self, tracks):
        # individual_asset_tracks returns an array of tuples(Address, tokenID)
        # each array element contains a unique token
        # the second element in tuple stores the token ID
        for token in tracks:
            self.tokens.append(token[1])

    def save_deployed_tokens(self):
        if self.tokens:
            filepath = config.DEFAULT_CONFIG_SAVE_PATH / "deployed_tokens.json"
            write_json_file(filepath, self.tokens)
            log_step_pass("Saved deployed tokens.")
        else:
            log_step_fail("No tokens to save!")

    def get_saved_deployed_tokens(self) -> list:
        filepath = config.DEFAULT_CONFIG_SAVE_PATH / "deployed_tokens.json"
        retrieved_tokens = read_json_file(filepath)

        if retrieved_tokens and len(retrieved_tokens) == self.number_of_tokens:
            log_step_pass(f"Loaded {len(retrieved_tokens)} tokens.")
            return retrieved_tokens
        elif retrieved_tokens and len(retrieved_tokens) >= self.number_of_tokens:
            log_warning(f"Loaded {len(retrieved_tokens)} tokens instead of expected {self.number_of_tokens}.")
            return retrieved_tokens
        else:
            log_step_fail("No tokens loaded!")
            return []

    def load_deployed_tokens(self) -> bool:
        loaded_tokens = self.get_saved_deployed_tokens()
        if loaded_tokens and len(loaded_tokens) >= self.number_of_tokens:
            self.tokens = loaded_tokens
            return True
        else:
            return False

    def save_deployed_contracts(self):
        for contracts in self.contracts.values():
            contracts.save_deployed_contracts()

    def print_deployed_contracts(self):
        log_step_pass(f"Deployed contracts below:")
        for contracts in self.contracts.values():
            contracts.print_deployed_contracts()
            print("")

    # main entry method to deploy the DEX contract structure (either fresh deploy or loading existing ones)
    def deploy_structure(self, deployer_account: Account, network_provider: NetworkProviders,
                         clean_deploy_override: bool):
        deployer_account.sync_nonce(network_provider.proxy)
        for contract_label, contracts in self.contracts.items():
            if not clean_deploy_override and not contracts.deploy_clean:
                contracts.load_deployed_contracts()
            else:
                log_step_pass(f"Starting setup process for {contract_label}:")
                contracts.deploy_function(contract_label, deployer_account, network_provider)
                if len(contracts.deployed_contracts) > 0:
                    contracts.print_deployed_contracts()
                    self.contracts[contract_label] = contracts
                    contracts.save_deployed_contracts()
                else:
                    log_warning(f"No contracts deployed for {contract_label}!")

    # should be run for fresh deployed contracts
    def start_deployed_contracts(self, deployer_account: Account, network_provider: NetworkProviders,
                                 clean_deploy_override: bool):
        deployer_account.sync_nonce(network_provider.proxy)
        for contracts in self.contracts.values():
            if contracts.deploy_clean or clean_deploy_override:
                for contract in contracts.deployed_contracts:
                    contract.contract_start(deployer_account, network_provider.proxy)

        self.global_start_setups(deployer_account, network_provider, clean_deploy_override)

    def global_start_setups(self, deployer_account: Account, network_provider: NetworkProviders,
                            clean_deploy_override: bool):
        self.set_transfer_role_locked_token(deployer_account, network_provider, clean_deploy_override)
        # self.set_proxy_v2_in_pairs(deployer_account, network_provider, clean_deploy_override)     # used only when not done implicitly

    def set_transfer_role_locked_token(self, deployer_account: Account, network_provider: NetworkProviders,
                                       clean_deploy_override: bool):
        energy_factory: Optional[SimpleLockEnergyContract] = None
        energy_factory = self.get_deployed_contract_by_index(config.SIMPLE_LOCKS_ENERGY, 0)
        whitelist = [config.PROXIES_V2, config.FEES_COLLECTORS,
                     config.UNSTAKERS, config.METASTAKINGS_V2]

        # gather contract addresses to whitelist
        addresses = []
        if energy_factory:
            for contracts in self.contracts.values():
                if not contracts.deploy_clean and not clean_deploy_override:
                    continue
                if contracts.label not in whitelist:
                    continue
                addresses.extend([contract.address for contract in contracts.deployed_contracts])

        # whitelist addresses
        for address in addresses:
            tx_hash = energy_factory.set_transfer_role_locked_token(deployer_account, network_provider.proxy,
                                                                    [address])
            if not network_provider.check_complex_tx_status(tx_hash, "set transfer role for locked asset on contracts"):
                return

    def set_proxy_v2_in_pairs(self, deployer_account: Account, network_providers: NetworkProviders,
                              clean_deploy_override: bool):
        search_label = "proxy_v2"
        pair_contracts = self.contracts[config.PAIRS_V2]

        # execute only if proxy is clean or overriden
        if not self.contracts[config.PROXIES_V2].deploy_clean and not clean_deploy_override:
            return
        # execute only if pair contracts weren't cleanly deployed
        if pair_contracts.deploy_clean:
            return

        # Set proxy in pairs
        if len(pair_contracts.deploy_structure_list) != len(pair_contracts.deployed_contracts):
            log_step_fail(f"Uneven length of pair deployed contracts! Skipping.")
            return
        for index, config_pair in enumerate(pair_contracts.deploy_structure_list):
            if search_label in config_pair:
                pair_contract: Optional[PairContract] = None
                pair_contract = pair_contracts.get_deployed_contract_by_index(index)
                proxy_contract: Optional[DexProxyContract] = None
                proxy_contract = self.contracts[config.PROXIES_V2].get_deployed_contract_by_index(
                    config_pair[search_label])

                if not proxy_contract:
                    log_step_fail(f"Configured proxy not found for pair: {pair_contract.address}")

                tx_hash = proxy_contract.add_pair_to_intermediate(deployer_account, network_providers.proxy,
                                                                  pair_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "set proxy for pair address"):
                    return

    def get_deployed_contracts(self, label: str):
        return self.contracts[label].deployed_contracts

    def get_deployed_contract_by_index(self, label: str, index: int):
        return self.contracts[label].get_deployed_contract_by_index(index)

    def get_deployed_contract_by_address(self, label: str, address: str):
        return self.contracts[label].get_deployed_contract_by_address(address)

    # CONTRACT DEPLOYERS ------------------------------
    def egld_wrap_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for contract_config in contract_structure.deploy_structure_list:
            # deploy locked asset contract
            wrapped_token = self.tokens[contract_config["unlocked_asset"]]

            # deploy contract
            deployed_contract = EgldWrapContract(wrapped_token)
            tx_hash, contract_address = deployed_contract.contract_deploy(deployer_account,
                                                                          network_providers.proxy,
                                                                          contract_structure.bytecode)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "egld wrapper"): return
            deployed_contract.address = contract_address
            log_step_pass(f"EGLD wrap contract address: {contract_address}")

            # Set special role on wrapped tokens
            tx_hash = self.esdt_contract.set_special_role_token(deployer_account,
                                                                network_providers.proxy,
                                                                [wrapped_token, contract_address,
                                                                 "ESDTRoleLocalMint", "ESDTRoleLocalBurn"])
            if not network_providers.check_complex_tx_status(tx_hash, "set special role on wrapped token"): return

            deployed_contracts.append(deployed_contract)

        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def locked_asset_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for config_locked_asset in contract_structure.deploy_structure_list:
            # deploy locked asset contract
            unlocked_token = self.tokens[config_locked_asset["unlocked_asset"]]
            locked_token = config_locked_asset["locked_asset"]
            locked_token_name = config_locked_asset["locked_asset_name"]

            # deploy contract
            deployed_locked_asset_contract = LockedAssetContract(unlocked_token)
            tx_hash, contract_address = deployed_locked_asset_contract.contract_deploy(deployer_account,
                                                                                       network_providers.proxy,
                                                                                       contract_structure.bytecode)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "locked asset"): return
            deployed_locked_asset_contract.address = contract_address
            log_step_pass(f"Locked asset contract address: {contract_address}")

            # register locked token and save it
            tx_hash = deployed_locked_asset_contract.register_locked_asset_token(deployer_account,
                                                                                 network_providers.proxy,
                                                                                 [locked_token_name, locked_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register locked token"): return
            locked_token_hex = LockedAssetContractDataFetcher(Address(deployed_locked_asset_contract.address),
                                                              network_providers.proxy.url).get_data("getLockedAssetTokenId")
            deployed_locked_asset_contract.locked_asset = hex_to_string(locked_token_hex)

            # Set special role on unlocked asset
            tx_hash = self.esdt_contract.set_special_role_token(deployer_account,
                                                                network_providers.proxy,
                                                                [unlocked_token, contract_address,
                                                                 "ESDTRoleLocalMint"])
            if not network_providers.check_complex_tx_status(tx_hash, "set special role on unlocked asset"): return

            deployed_contracts.append(deployed_locked_asset_contract)

        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def proxy_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        """
        locked_asset - mandatory for V1; optional for V2
        energy_factory - mandatory for V2
        """
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for config_proxy in contract_structure.deploy_structure_list:
            if contracts_index == config.PROXIES:
                version = ProxyContractVersion.V1
            elif contracts_index == config.PROXIES_V2:
                version = ProxyContractVersion.V2
            else:
                log_step_fail(f"Aborting deploy: Unsupported proxy label.")
                return

            # deploy proxy contract
            locked_asset_contract: Optional[LockedAssetContract] = None
            energy_contract: Optional[SimpleLockEnergyContract] = None
            asset = ""
            locked_assets = []
            factory_addresses = []

            if version == ProxyContractVersion.V1 or ProxyContractVersion.V2:
                if 'locked_asset' not in config_proxy and version == ProxyContractVersion.V1:
                    log_step_fail(f"Aborting deploy: locked asset not configured.")
                    return

                locked_asset_contract = self.contracts[config.LOCKED_ASSETS].\
                    get_deployed_contract_by_index(config_proxy["locked_asset"])
                if locked_asset_contract:
                    asset = locked_asset_contract.unlocked_asset
                    locked_assets.append(locked_asset_contract.locked_asset)
                    factory_addresses.append(locked_asset_contract.address)
                elif version == ProxyContractVersion.V1:
                    log_step_fail(f"Aborting deploy: locked asset contract not available.")
                    return

            if version == ProxyContractVersion.V2:
                if 'energy_factory' not in config_proxy:
                    log_step_fail(f"Aborting deploy: energy factory not configured.")
                    return

                energy_contract = self.contracts[config.SIMPLE_LOCKS_ENERGY].\
                    get_deployed_contract_by_index(config_proxy["energy_factory"])
                if asset and asset != energy_contract.base_token:
                    log_step_fail(f"Aborting deploy: Mismatch configuration in base tokens.")
                    return
                elif not asset:
                    asset = energy_contract.base_token
                locked_assets.append(energy_contract.locked_token)
                factory_addresses.append(energy_contract.address)

            proxy_lp_token = config_proxy["proxy_lp"]
            proxy_lp_token_name = config_proxy["proxy_lp_name"]
            proxy_farm_token = config_proxy["proxy_farm"]
            proxy_farm_token_name = config_proxy["proxy_farm_name"]

            # deploy contract
            deployed_proxy_contract = DexProxyContract(locked_assets, asset, version)
            tx_hash, contract_address = deployed_proxy_contract.contract_deploy(deployer_account,
                                                                                network_providers.proxy,
                                                                                contract_structure.bytecode,
                                                                                [factory_addresses])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "proxy"): return
            deployed_proxy_contract.address = contract_address
            log_step_pass(f"Proxy contract address: {contract_address}")

            # register proxy lp token and save it
            tx_hash = deployed_proxy_contract.register_proxy_lp_token(deployer_account,
                                                                      network_providers.proxy,
                                                                      [proxy_lp_token_name, proxy_lp_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register proxy lp token"): return
            proxy_lp_token = ProxyContractDataFetcher(Address(deployed_proxy_contract.address),
                                                      network_providers.proxy.url).get_data("getWrappedLpTokenId")
            deployed_proxy_contract.proxy_lp_token = hex_to_string(proxy_lp_token)

            # register proxy farm token and save it
            tx_hash = deployed_proxy_contract.register_proxy_farm_token(deployer_account,
                                                                        network_providers.proxy,
                                                                        [proxy_farm_token_name, proxy_farm_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register proxy farm token"): return
            proxy_farm_token = ProxyContractDataFetcher(Address(deployed_proxy_contract.address),
                                                        network_providers.proxy.url).get_data("getWrappedFarmTokenId")
            deployed_proxy_contract.proxy_farm_token = hex_to_string(proxy_farm_token)

            # Whitelist proxy in locked asset factory contract
            if version == ProxyContractVersion.V1 or version == ProxyContractVersion.V2:
                tx_hash = locked_asset_contract.whitelist_contract(deployer_account, network_providers.proxy,
                                                                   deployed_proxy_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist proxy in locked asset contract"): return
            if version == ProxyContractVersion.V2:
                tx_hash = energy_contract.add_sc_to_token_transfer_whitelist(deployer_account, network_providers.proxy,
                                                                             deployed_proxy_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist proxy in energy factory contract"): return

                # set energy factory proxy
                tx_hash = deployed_proxy_contract.set_energy_factory_address(deployer_account, network_providers.proxy,
                                                                             energy_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "set energy factory in proxy contract"): return

            # Set special roles on unlocked asset token
            self.esdt_contract.set_special_role_token(deployer_account, network_providers.proxy,
                                                      [asset, deployed_proxy_contract.address, "ESDTRoleLocalMint"])
            if not network_providers.check_complex_tx_status(tx_hash, "set special role on unlocked asset"): return

            self.esdt_contract.set_special_role_token(deployer_account, network_providers.proxy,
                                                      [asset, deployed_proxy_contract.address, "ESDTRoleLocalBurn"])
            if not network_providers.check_complex_tx_status(tx_hash, "set special role on unlocked asset"): return

            deployed_contracts.append(deployed_proxy_contract)

        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def simple_lock_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for config_simple_lock in contract_structure.deploy_structure_list:
            # deploy simple lock contract
            locked_token = config_simple_lock["locked_token"]
            locked_token_name = config_simple_lock["locked_token_name"]
            locked_lp_token = config_simple_lock["locked_lp_token"]
            locked_lp_token_name = config_simple_lock["locked_lp_token_name"]
            locked_farm_token = config_simple_lock["locked_farm_token"]
            locked_farm_token_name = config_simple_lock["locked_farm_token_name"]

            # deploy contract
            deployed_simple_lock_contract = SimpleLockContract()
            tx_hash, contract_address = deployed_simple_lock_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "simple lock"): return
            deployed_simple_lock_contract.address = contract_address
            log_step_pass(f"Simple lock contract address: {contract_address}")

            # issue locked token and save it
            tx_hash = deployed_simple_lock_contract.issue_locked_token(deployer_account,
                                                                       network_providers.proxy,
                                                                       [locked_token_name,
                                                                        locked_token])
            if not network_providers.check_complex_tx_status(tx_hash, "issue locked token"): return
            locked_token_hex = SimpleLockContractDataFetcher(Address(deployed_simple_lock_contract.address),
                                                             network_providers.proxy.url).get_data("getLockedTokenId")
            deployed_simple_lock_contract.locked_token = hex_to_string(locked_token_hex)

            # issue locked LP token and save it
            tx_hash = deployed_simple_lock_contract.issue_locked_lp_token(deployer_account,
                                                                          network_providers.proxy,
                                                                          [locked_lp_token_name,
                                                                           locked_lp_token])
            if not network_providers.check_complex_tx_status(tx_hash, "issue locked LP token"): return
            locked_lp_token_hex = SimpleLockContractDataFetcher(Address(deployed_simple_lock_contract.address),
                                                                network_providers.proxy.url).get_data("getLpProxyTokenId")
            deployed_simple_lock_contract.lp_proxy_token = hex_to_string(locked_lp_token_hex)

            # issue locked farm token and save it
            tx_hash = deployed_simple_lock_contract.issue_locked_farm_token(deployer_account,
                                                                            network_providers.proxy,
                                                                            [locked_farm_token_name,
                                                                             locked_farm_token])
            if not network_providers.check_complex_tx_status(tx_hash, "issue locked farm token"): return
            locked_lp_token_hex = SimpleLockContractDataFetcher(Address(deployed_simple_lock_contract.address),
                                                                network_providers.proxy.url).get_data("getLpProxyTokenId")
            deployed_simple_lock_contract.lp_proxy_token = hex_to_string(locked_lp_token_hex)

            deployed_contracts.append(deployed_simple_lock_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def fees_collector_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for contract_config in contract_structure.deploy_structure_list:
            # deploy fees collector contract
            energy_factory_contract: Optional[SimpleLockEnergyContract] = None
            if 'energy_factory' in contract_config:
                energy_factory_contract = self.contracts[config.SIMPLE_LOCKS_ENERGY].get_deployed_contract_by_index(
                    contract_config['energy_factory']
                )
            else:
                log_step_fail(f"Aborting deploy: Energy factory not configured! Contract will be dumped.")
                return

            # deploy contract
            deployed_contract = FeesCollectorContract()
            tx_hash, contract_address = deployed_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode,
                [energy_factory_contract.locked_token, energy_factory_contract.address])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "fees collector"): return
            deployed_contract.address = contract_address
            log_step_pass(f"Fees collector contract address: {contract_address}")

            # set energy factory in fees collector
            tx_hash = deployed_contract.set_energy_factory_address(deployer_account, network_providers.proxy,
                                                                   energy_factory_contract.address)
            if not network_providers.check_simple_tx_status(tx_hash, "set energy factory in fees collector"): return

            # set locking address in fees collector
            tx_hash = deployed_contract.set_locking_address(deployer_account, network_providers.proxy,
                                                            energy_factory_contract.address)
            if not network_providers.check_simple_tx_status(tx_hash, "set locking address in fees collector"): return

            # set lock epochs
            tx_hash = deployed_contract.set_lock_epochs(deployer_account, network_providers.proxy,
                                                        contract_config['lock_epochs'])
            if not network_providers.check_simple_tx_status(tx_hash, "set lock epochs in fees collector"): return

            # set locked tokens per block
            tx_hash = deployed_contract.set_locked_tokens_per_block(deployer_account, network_providers.proxy,
                                                                    contract_config['locked_tokens_per_block'])
            if not network_providers.check_simple_tx_status(tx_hash, "set locked tokens per block in fees collector"):
                return

            # whitelist fees collector in energy contract
            tx_hash = energy_factory_contract.add_sc_to_whitelist(deployer_account, network_providers.proxy,
                                                                  deployed_contract.address)
            if not network_providers.check_simple_tx_status(tx_hash, "add fees collector in energy contract"): return

            deployed_contracts.append(deployed_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def simple_lock_energy_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for contract_config in contract_structure.deploy_structure_list:
            # deploy simple lock energy contract
            base_token = self.tokens[contract_config['base_token']]
            locked_token = contract_config["locked_token"]
            locked_token_name = contract_config["locked_token_name"]

            locked_asset_factory: Optional[LockedAssetContract] = None
            if 'locked_asset_factory' in contract_config:
                locked_asset_factory = self.contracts[config.LOCKED_ASSETS].get_deployed_contract_by_index(
                    contract_config['locked_asset_factory'])
                if locked_asset_factory is None:
                    log_step_fail(f"Aborting deploy: Locked asset factory contract not available! Contract will be dumped.")
                    return
            else:
                log_step_fail(f"Aborting deploy: Locked asset factory not configured! Contract will be dumped.")
                return

            # deploy contract
            deployed_contract = SimpleLockEnergyContract(base_token)
            tx_hash, contract_address = deployed_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode,
                [locked_asset_factory.locked_asset, locked_asset_factory.address,
                 contract_config['min_migrated_lock_epochs'],
                 contract_config['lock_options'], contract_config['penalties']])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "simple lock energy"): return
            deployed_contract.address = contract_address
            log_step_pass(f"Simple lock energy contract address: {contract_address}")

            # issue locked token and save it
            tx_hash = deployed_contract.issue_locked_token(deployer_account,
                                                           network_providers.proxy,
                                                           [locked_token_name, locked_token])
            if not network_providers.check_complex_tx_status(tx_hash, "issue locked token"): return
            locked_token_hex = SimpleLockEnergyContractDataFetcher(
                Address(deployed_contract.address), network_providers.proxy.url).get_data("getLockedTokenId")
            deployed_contract.locked_token = hex_to_string(locked_token_hex)

            # Set special role on unlocked asset for burning base token
            tx_hash = self.esdt_contract.set_special_role_token(deployer_account,
                                                                network_providers.proxy,
                                                                [base_token, contract_address,
                                                                 "ESDTRoleLocalBurn"])
            if not network_providers.check_complex_tx_status(tx_hash, "set burn role on unlocked asset"): return

            # Set special role on unlocked asset for base token minting
            tx_hash = self.esdt_contract.set_special_role_token(deployer_account,
                                                                network_providers.proxy,
                                                                [base_token, contract_address,
                                                                 "ESDTRoleLocalMint"])
            if not network_providers.check_complex_tx_status(tx_hash, "set mint role on unlocked asset"): return

            # set transfer role for self
            tx_hash = deployed_contract.set_transfer_role_locked_token(deployer_account,
                                                                       network_providers.proxy,
                                                                       [])
            if not network_providers.check_complex_tx_status(tx_hash, "set transfer role for locked asset on factory"):
                return

            deployed_contracts.append(deployed_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def token_unstake_deploy(self, contracts_index: str, deployer_account: Account,
                             network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for contract_config in contract_structure.deploy_structure_list:
            # deploy token unstake contract

            fees_collector: Optional[FeesCollectorContract] = None
            if 'fees_collector' in contract_config:
                fees_collector = self.contracts[config.FEES_COLLECTORS].get_deployed_contract_by_index(
                    contract_config["fees_collector"])
                if fees_collector is None:
                    log_step_fail(f"Aborting deploy: Fees collector contract not available! "
                                         f"Contract will be dumped.")
                    return
            else:
                log_step_fail(
                    f"Aborting deploy: Fees collector not configured! Contract will be dumped.")
                return

            energy_factory: Optional[SimpleLockEnergyContract] = None
            if 'energy_factory' in contract_config:
                energy_factory = self.contracts[config.SIMPLE_LOCKS_ENERGY].get_deployed_contract_by_index(
                    contract_config['energy_factory'])
                if energy_factory is None:
                    log_step_fail(f"Aborting deploy: Energy factory contract not available! "
                                         f"Contract will be dumped.")
                    return
            else:
                log_step_fail(f"Aborting deploy: Energy factory not configured! Contract will be dumped.")
                return

            # deploy contract
            deployed_contract = UnstakerContract()
            tx_hash, contract_address = deployed_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode,
                [contract_config['unbond_epochs'], energy_factory.address, contract_config['fees_burn_percentage'],
                 fees_collector.address])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "token unstake"): return
            deployed_contract.address = contract_address
            log_step_pass(f"Token unstake contract address: {contract_address}")

            # Set special role on unlocked asset for burning base token
            tx_hash = self.esdt_contract.set_special_role_token(deployer_account,
                                                                network_providers.proxy,
                                                                [energy_factory.base_token, contract_address,
                                                                 "ESDTRoleLocalBurn"])
            if not network_providers.check_complex_tx_status(tx_hash, "set burn role on unlocked asset"): return

            # Set special role on locked asset for burning locked token
            tx_hash = energy_factory.set_burn_role_locked_token(deployer_account,
                                                                network_providers.proxy,
                                                                [contract_address])
            if not network_providers.check_complex_tx_status(tx_hash, "set burn role on locked asset"): return

            # add token unstake address in energy contract
            tx_hash = energy_factory.set_token_unstake(deployer_account, network_providers.proxy, [contract_address])
            if not network_providers.check_simple_tx_status(tx_hash, "set unstake address in energy contract"): return

            tx_hash = energy_factory.add_sc_to_whitelist(deployer_account, network_providers.proxy, contract_address)
            if not network_providers.check_simple_tx_status(tx_hash, "whitelist unstake address in energy contract"): return

            # whitelist unstaker address in fees collector (unstake sends fees from energy factory)
            if 'fees_collector' in contract_config:
                tx_hash = fees_collector.add_known_contracts(deployer_account, network_providers.proxy,
                                                             [contract_address])
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist energy address in fees collector"): return

                tx_hash = fees_collector.add_known_tokens(deployer_account, network_providers.proxy,
                                                          [energy_factory.locked_token])
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist locked token in fees collector"): return

            deployed_contracts.append(deployed_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def router_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        version = RouterContractVersion.V1 if contracts_index == config.ROUTER else RouterContractVersion.V2

        for _ in contract_structure.deploy_structure_list:
            # deploy template pair
            if version == RouterContractVersion.V1:
                pair_version = PairContractVersion.V1
                pair_bytecode = self.contracts[config.PAIRS].bytecode
            else:
                pair_version = PairContractVersion.V2
                pair_bytecode = self.contracts[config.PAIRS_V2].bytecode

            template_pair_contract = PairContract(self.tokens[0], self.tokens[1], pair_version)
            tx_hash, contract_address = template_pair_contract.contract_deploy(
                deployer_account, network_providers.proxy, pair_bytecode,
                [config.ZERO_CONTRACT_ADDRESS, config.ZERO_CONTRACT_ADDRESS,
                 config.ZERO_CONTRACT_ADDRESS, 0, 0, config.ZERO_CONTRACT_ADDRESS])

            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "pair contract"): return
            template_pair_contract.address = contract_address

            # deploy router
            router_contract = RouterContract(version)
            tx_hash, contract_address = router_contract.contract_deploy(
                deployer_account, network_providers.proxy, self.contracts[contracts_index].bytecode,
                [template_pair_contract.address])

            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "router"): return
            router_contract.address = contract_address
            log_step_pass(f"Router contract address: {contract_address}")

            deployed_contracts.append(router_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def pool_deploy_from_router(self, contracts_index: str, deployer_account: Account,
                                network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        version = PairContractVersion.V1 if contracts_index == config.PAIRS else PairContractVersion.V2

        for config_pool in contract_structure.deploy_structure_list:
            # deploy pair contract from router
            first_token = self.tokens[config_pool['launched_token']]
            second_token = self.tokens[config_pool['accepted_token']]
            lp_token = config_pool['lp_token']
            lp_token_name = config_pool['lp_token_name']
            if version == PairContractVersion.V1:
                used_router_label = config.ROUTER
            else:
                used_router_label = config.ROUTER_V2

            router_contract = self.contracts[used_router_label].get_deployed_contract_by_index(0)
            if router_contract is None:
                log_step_fail(f"Aborting deploy: Router contract not available! Contract will be dumped.")
                return

            # deploy contract
            total_fee = config_pool['total_fee']
            special_fee = config_pool['special_fee']
            initial_liquidity_provider = config_pool[
                'liquidity_provider'] if 'liquidity_provider' in config_pool else config.ZERO_CONTRACT_ADDRESS
            admins = config_pool['admins'] if 'admins' in config_pool else []

            deployed_pair_contract = PairContract(first_token, second_token, version)
            args = [initial_liquidity_provider, total_fee, special_fee]
            args.extend(admins)
            tx_hash, contract_address = deployed_pair_contract.contract_deploy_via_router(
                deployer_account, network_providers.proxy, router_contract, args)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "pair via router"): return
            deployed_pair_contract.address = contract_address
            log_step_pass(f"Pair contract address: {contract_address}")

            # issue LP token and save it
            tx_hash = deployed_pair_contract.issue_lp_token_via_router(deployer_account, network_providers.proxy,
                                                                       router_contract, [lp_token_name, lp_token])
            if not network_providers.check_complex_tx_status(tx_hash, "issue LP token"): return
            lp_token_hex = PairContractDataFetcher(Address(deployed_pair_contract.address),
                                                   network_providers.proxy.url).get_data("getLpTokenIdentifier")
            deployed_pair_contract.lpToken = hex_to_string(lp_token_hex)

            # Set LP Token local roles
            tx_hash = deployed_pair_contract.set_lp_token_local_roles_via_router(deployer_account,
                                                                                 network_providers.proxy,
                                                                                 router_contract)
            if not network_providers.check_complex_tx_status(tx_hash, "set lp token local roles via router"): return

            # Set proxy if applicable
            if "proxy" in config_pool or "proxy_v2" in config_pool:
                proxy_contract: Optional[DexProxyContract] = None
                if "proxy" in config_pool:
                    proxy_contract = self.contracts[config.PROXIES].\
                        get_deployed_contract_by_index(config_pool['proxy'])
                elif "proxy_v2" in config_pool:
                    proxy_contract = self.contracts[config.PROXIES_V2].\
                        get_deployed_contract_by_index(config_pool["proxy_v2"])
                if proxy_contract is None:
                    log_step_fail(f"Aborting setup: Proxy contract not available! Contract will be dumped.")
                    return
                tx_hash = proxy_contract.add_pair_to_intermediate(deployer_account, network_providers.proxy,
                                                                  contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "set pair to intermediate in proxy"): return

            # Set simple lock if applicable
            if "simple_lock" in config_pool:
                if "locking_deadline_offset" in config_pool:
                    locking_deadline_offset = config_pool['locking_deadline_offset']
                else:
                    log_warning("Locking deadline offset not set, using default value 3 epochs")
                    locking_deadline_offset = 3

                if "unlock_epoch_offset" in config_pool:
                    unlock_epoch_offset = config_pool['unlock_epoch_offset']
                else:
                    log_warning("Unlock epoch offset not set, using default value 3 epochs")
                    unlock_epoch_offset = 3

                current_epoch = network_providers.proxy.get_network_status(0).current_epoch
                locking_deadline_epoch = current_epoch + locking_deadline_offset
                unlock_epoch = current_epoch + unlock_epoch_offset

                # set locking deadline in pair
                tx_hash = deployed_pair_contract.set_locking_deadline_epoch(deployer_account, network_providers.proxy,
                                                                            locking_deadline_epoch)
                if not network_providers.check_simple_tx_status(tx_hash, "set locking deadline epoch in pair"): return

                # set unlock epoch in pair
                tx_hash = deployed_pair_contract.set_unlock_epoch(deployer_account, network_providers.proxy,
                                                                  unlock_epoch)
                if not network_providers.check_simple_tx_status(tx_hash, "set unlock epoch in pair"): return

                deployed_simple_lock: Optional[SimpleLockContract] = None
                deployed_simple_lock = self.contracts[config.SIMPLE_LOCKS].get_deployed_contract_by_index(config_pool['simple_lock'])
                if deployed_simple_lock is None:
                    log_step_fail(f"Aborting setup: Simple lock contract not available! Contract will be dumped.")
                    return
                # add simple lock address in pair
                tx_hash = deployed_pair_contract.set_locking_sc_address(deployer_account, network_providers.proxy,
                                                                        deployed_simple_lock.address)
                if not network_providers.check_simple_tx_status(tx_hash, "set simple locking sc address in pair"): return

                # whitelist in simple lock contract
                tx_hash = deployed_simple_lock.add_lp_to_whitelist(deployer_account, network_providers.proxy,
                                                                   [deployed_pair_contract.address, first_token,
                                                                    second_token])
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist pair in simple locking contract"): return

            # Set fees collector if applicable
            if "fees_collector" in config_pool and version == PairContractVersion.V2:
                fees_collector: Optional[FeesCollectorContract] = None
                fees_collector = self.contracts[config.FEES_COLLECTORS].get_deployed_contract_by_index(config_pool['fees_collector'])
                if fees_collector is None:
                    log_step_fail(f"Aborting setup: Fees collector contract not available! Contract will be dumped.")
                    return
                if 'fees_collector_cut' not in config_pool:
                    log_step_fail(f"Aborting setup: fees_collector_cut not available in config! Contract will be dumped.")
                    return
                fees_cut = config_pool['fees_collector_cut']

                # setup fees collector in pair
                tx_hash = deployed_pair_contract.add_fees_collector(deployer_account, network_providers.proxy,
                                                                    [fees_collector.address, fees_cut])
                if not network_providers.check_simple_tx_status(tx_hash, "set fees collector in pair"): return

                # add pair address in fees collector
                _ = fees_collector.add_known_contracts(deployer_account, network_providers.proxy,
                                                       [contract_address])
                _ = fees_collector.add_known_tokens(deployer_account, network_providers.proxy,
                                                    [deployed_pair_contract.firstToken,
                                                     deployed_pair_contract.secondToken])

            deployed_contracts.append(deployed_pair_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def farm_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for config_farm in contract_structure.deploy_structure_list:
            # deploy farm contract
            lp_address = config.ZERO_CONTRACT_ADDRESS
            lp_contract: Optional[PairContract] = None
            locked_asset_address = config.ZERO_CONTRACT_ADDRESS
            locked_asset_contract: Optional[LockedAssetContract] = None
            version = FarmContractVersion.V14Locked if contracts_index == config.FARMS_LOCKED else \
                FarmContractVersion.V14Unlocked

            if version == FarmContractVersion.V14Locked:
                if not self.contracts[config.LOCKED_ASSETS].deployed_contracts:
                    log_step_fail("Aborting deploy for farm locked. Locked asset contract not existing.")
                    return
                locked_asset_contract = self.contracts[config.LOCKED_ASSETS].deployed_contracts[0]
                locked_asset_address = locked_asset_contract.address

            farmed_token = self.tokens[config_farm['farmed_token']]
            farm_token = config_farm['farm_token']
            if 'farming_token' in config_farm:
                farming_token = self.tokens[config_farm['farming_token']]
            elif 'farming_pool' in config_farm:
                # TODO: add check to verify existence of pair contract as prerequisite
                lp_contract = self.contracts[config.PAIRS].deployed_contracts[config_farm['farming_pool']]
                farming_token = lp_contract.lpToken
                lp_address = lp_contract.address
            else:
                log_step_fail(f'Aborting deploy: farming token/pool not configured!')
                return

            # deploy contract
            deployed_farm_contract = FarmContract(farming_token=farming_token,
                                                  farm_token="",
                                                  farmed_token=farmed_token,
                                                  address="",
                                                  version=version,
                                                  )
            tx_hash, contract_address = deployed_farm_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode,
                [lp_address, locked_asset_address])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "farm"): return
            deployed_farm_contract.address = contract_address
            log_step_pass(f"Farm contract address: {contract_address}")

            # register farm token and save it
            tx_hash = deployed_farm_contract.register_farm_token(deployer_account, network_providers.proxy, farm_token)
            if not network_providers.check_complex_tx_status(tx_hash, "register farm token"): return
            farm_token_hex = FarmContractDataFetcher(Address(deployed_farm_contract.address),
                                                     network_providers.proxy.url).get_data("getFarmTokenId")
            deployed_farm_contract.farmToken = hex_to_string(farm_token_hex)

            # Whitelist farm in pool if it's linked to pool
            if lp_contract is not None:
                tx_hash = lp_contract.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in pool"): return

            # Whitelist farm in locked asset contract or provide mint role for rewards
            if locked_asset_contract is not None:
                tx_hash = locked_asset_contract.whitelist_contract(deployer_account, network_providers.proxy,
                                                                   contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in locked asset contract"): return
            else:
                tx_hash = self.esdt_contract.set_special_role_token(deployer_account, network_providers.proxy,
                                                                    [farmed_token, contract_address,
                                                                     "ESDTRoleLocalMint"])
                if not network_providers.check_complex_tx_status(tx_hash, "set special role on farmed token"): return

            # set rewards per block
            tx_hash = deployed_farm_contract.set_rewards_per_block(deployer_account, network_providers.proxy,
                                                                   config_farm['rpb'])
            if not network_providers.check_simple_tx_status(tx_hash, "set rewards per block in farm"): return

            # set penalty percent
            tx_hash = deployed_farm_contract.set_penalty_percent(deployer_account, network_providers.proxy, 0)
            if not network_providers.check_simple_tx_status(tx_hash, "set penalty percent in farm"): return

            # Set proxy if applicable
            if "proxy" in config_farm or "proxy_v2" in config_farm:
                proxy_contract: Optional[DexProxyContract] = None
                if "proxy" in config_farm:
                    proxy_contract = self.contracts[config.PROXIES].\
                        get_deployed_contract_by_index(config_farm['proxy'])
                elif "proxy_v2" in config_farm:
                    proxy_contract = self.contracts[config.PROXIES_V2].\
                        get_deployed_contract_by_index(config_farm['proxy_v2'])
                tx_hash = proxy_contract.add_farm_to_intermediate(deployer_account, network_providers.proxy,
                                                                  contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "set farm to intermediate in proxy"):
                    return

                # Set simple lock if applicable
                if "simple_lock" in config_farm:
                    deployed_simple_lock: Optional[SimpleLockContract] = None
                    deployed_simple_lock = self.contracts[config.SIMPLE_LOCKS].get_deployed_contract_by_index(
                        config_farm['simple_lock'])
                    if deployed_simple_lock is None:
                        log_step_fail(f"Aborting setup: Simple lock contract not available! Contract will be dumped.")
                        return

                    # whitelist in simple lock contract
                    tx_hash = deployed_simple_lock.add_farm_to_whitelist(deployer_account, network_providers.proxy,
                                                                         [deployed_farm_contract.address,
                                                                          deployed_farm_contract.farmingToken,
                                                                          1])

                    if not network_providers.check_simple_tx_status(tx_hash,
                                                                    "whitelist farm in simple locking contract"):
                        return

                    # whitelist simple lock contract in farm
                    tx_hash = deployed_farm_contract.add_contract_to_whitelist(deployer_account, network_providers.proxy,
                                                                               deployed_simple_lock.address)
                    if not network_providers.check_simple_tx_status(tx_hash,
                                                                    "whitelist simple lock in farm"): return

            deployed_contracts.append(deployed_farm_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def proxy_deployer_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []

        for contract_config in contract_structure.deploy_structure_list:
            # deploy template contract
            if "template" not in contract_config:
                log_step_fail(f"Aborting deploy: template not configured")
                return

            template_name = contract_config['template']
            if template_name in self.contracts:
                contract_bytecode = self.contracts[contract_config['template']].bytecode
            else:
                log_step_fail("Aborting deploy: Template for proxy deployer not valid.")
                return

            if template_name == config.FARMS_V2:
                version = FarmContractVersion.V2Boosted
            else:
                log_step_fail(f"Aborting deploy: invalid template configured")
                return

            template_contract = FarmContract(
                self.tokens[0],
                "",
                self.tokens[0],
                "",
                version)
            tx_hash, template_address = template_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_bytecode,
                [config.ZERO_CONTRACT_ADDRESS, config.ZERO_CONTRACT_ADDRESS])

            if not network_providers.check_deploy_tx_status(tx_hash, template_address, "template farm contract"): return
            template_contract.address = template_address

            # deploy proxy deployer
            contract = ProxyDeployerContract(template_name)
            tx_hash, contract_address = contract.contract_deploy(
                deployer_account, network_providers.proxy, self.contracts[contracts_index].bytecode,
                [template_contract.address])

            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "proxy deployer"): return
            contract.address = contract_address
            log_step_pass(f"Proxy deployer contract address: {contract_address}")

            deployed_contracts.append(contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def farm_deploy_from_proxy_deployer(self, contracts_index: str, deployer_account: Account,
                                        network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []

        for contract_config in contract_structure.deploy_structure_list:
            # deploy farm contract from proxy deployer
            # get deployer proxy contract
            if "deployer" not in contract_config:
                log_step_fail(f"Aborting deploy: deployer not configured")
                return

            deployer_contract: Optional[ProxyDeployerContract] = \
                self.contracts[config.PROXY_DEPLOYERS].get_deployed_contract_by_index(
                contract_config['deployer'])

            if deployer_contract is None:
                log_step_fail(f"Aborting deploy: deployer contract not available")

            # determine version
            version = None
            if deployer_contract.template == config.FARMS_V2:
                version = FarmContractVersion.V2Boosted

            # get lock factory
            if 'lock_factory' not in contract_config:
                log_step_fail("Aborting deploy: Locked factory contract not existing!")
                return
            locking_contract: Optional[SimpleLockEnergyContract] = None
            locking_contract = self.contracts[config.SIMPLE_LOCKS_ENERGY].get_deployed_contract_by_index(
                contract_config['lock_factory']
            )

            # get contract config
            farmed_token = self.tokens[contract_config['farmed_token']]
            farm_token = contract_config['farm_token']
            farm_token_name = contract_config['farm_token_name']
            lp_contract: Optional[PairContract] = None
            lp_address = config.ZERO_CONTRACT_ADDRESS
            if 'farming_token' in contract_config:
                farming_token = self.tokens[contract_config['farming_token']]
            elif 'farming_pool' in contract_config:
                lp_contract = self.contracts[config.PAIRS_V2].get_deployed_contract_by_index(
                    contract_config['farming_pool'])
                if lp_contract is None:
                    log_step_fail(f'Aborting deploy: farming pool v2 not existing!')
                    return
                farming_token = lp_contract.lpToken
                lp_address = lp_contract.address
            else:
                log_step_fail(f'Aborting deploy: farming token/pool not configured!')
                return

            # deploy contract
            deployed_contract = FarmContract(farming_token=farming_token,
                                             farm_token="",
                                             farmed_token=farmed_token,
                                             address="",
                                             version=version,
                                             )
            tx_hash, contract_address = deployer_contract.farm_contract_deploy(deployer_account, network_providers.proxy,
                                                                       [farmed_token, farming_token, lp_address])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "boosted farm"): return
            deployed_contract.address = contract_address
            log_step_pass(f"Farm contract address: {contract_address}")

            # register farm token and save it
            tx_hash = deployed_contract.register_farm_token(deployer_account, network_providers.proxy,
                                                            [farm_token_name, farm_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register farm token"): return
            farm_token_hex = FarmContractDataFetcher(Address(deployed_contract.address),
                                                     network_providers.proxy.url).get_data("getFarmTokenId")
            deployed_contract.farmToken = hex_to_string(farm_token_hex)

            # Whitelist farm in pool if it's linked to pool
            if lp_contract is not None:
                tx_hash = lp_contract.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in pool"): return

            # Set energy contract
            if locking_contract is not None:
                # tx_hash = deployed_contract.set_energy_factory_address(deployer_account, network_providers.proxy,
                #                                                        locking_contract.address)
                # TODO: we should get rid of proxy calls for consistency
                tx_hash = deployer_contract.call_farm_endpoint(deployer_account, network_providers.proxy,
                                                               [deployed_contract.address,
                                                                "setEnergyFactoryAddress",
                                                                locking_contract.address])
                if not network_providers.check_simple_tx_status(tx_hash, "set energy address in farm"): return
            else:
                log_step_fail(f"Failed to set up energy contract in farm. Energy contract not available!")
                return

            # Set locking contract
            if locking_contract is not None:
                # tx_hash = deployed_contract.set_locking_address(deployer_account, network_providers.proxy,
                #                                                 locking_contract.address)
                # TODO: we should get rid of proxy calls for consistency
                tx_hash = deployer_contract.call_farm_endpoint(deployer_account, network_providers.proxy,
                                                               [deployed_contract.address,
                                                                "setLockingScAddress",
                                                                locking_contract.address])
                if not network_providers.check_simple_tx_status(tx_hash, "set locking address in farm"): return
            else:
                log_step_fail(f"Failed to set up locking contract in farm. Locking contract not available!")
                return

            # Set lock epochs
            if 'lock_epochs' not in contract_config:
                lock_epochs = 1440
                log_step_fail(f"Rewards per block not configured! Setting default: {lock_epochs}")
            else:
                lock_epochs = contract_config['lock_epochs']
            # tx_hash = deployed_contract.set_lock_epochs(deployer_account, network_providers.proxy,
            #                                             lock_epochs)
            # TODO: we should get rid of proxy calls for consistency
            tx_hash = deployer_contract.call_farm_endpoint(deployer_account, network_providers.proxy,
                                                           [deployed_contract.address,
                                                            "setLockEpochs",
                                                            lock_epochs])
            if not network_providers.check_simple_tx_status(tx_hash, "set lock epochs in farm"): return

            # Set boosted yields rewards percentage
            if 'boosted_rewards' not in contract_config:
                boosted_rewards = 6000
                log_step_fail(f"Boosted yields rewards percentage configured! Setting default: {boosted_rewards}")
            else:
                boosted_rewards = contract_config['boosted_rewards']
            tx_hash = deployed_contract.set_boosted_yields_rewards_percentage(deployer_account, network_providers.proxy,
                                                                              boosted_rewards)
            if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields rewards percentage in farm"):
                return

            # Set boosted yields factors
            if "base_const" not in contract_config or \
                    "energy_const" not in contract_config or \
                    "farm_const" not in contract_config or \
                    "min_energy" not in contract_config or \
                    "min_farm" not in contract_config:
                log_step_fail(f"Aborting deploy: Boosted yields factors not configured!")
            tx_hash = deployed_contract.set_boosted_yields_factors(deployer_account, network_providers.proxy,
                                                                   [contract_config['base_const'],
                                                                    contract_config['energy_const'],
                                                                    contract_config['farm_const'],
                                                                    contract_config['min_energy'],
                                                                    contract_config['min_farm']])
            if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields factors in farm"):
                return

            # set rewards per block
            if 'rpb' not in contract_config:
                rpb = 10000
                log_step_fail(f"Rewards per block not configured! Setting default: {rpb}")
            else:
                rpb = contract_config['rpb']
            tx_hash = deployed_contract.set_rewards_per_block(deployer_account, network_providers.proxy,
                                                              rpb)
            if not network_providers.check_simple_tx_status(tx_hash, "set rewards per block in farm"): return

            # set penalty percent
            if 'penalty' not in contract_config:
                log_step_fail(f"Penalty percent not configured! Setting default: 0")
                penalty = 0
            else:
                penalty = contract_config['penalty']
            # tx_hash = deployed_contract.set_penalty_percent(deployer_account, network_providers.proxy,
            #                                                 penalty)
            # TODO: we should get rid of proxy calls for consistency
            tx_hash = deployer_contract.call_farm_endpoint(deployer_account, network_providers.proxy,
                                                           [deployed_contract.address,
                                                            "set_penalty_percent",
                                                            penalty])
            if not network_providers.check_simple_tx_status(tx_hash, "set penalty percent in farm"): return

            # Set simple lock if applicable
            if "simple_lock" in contract_config:
                deployed_simple_lock: Optional[SimpleLockContract] = None
                deployed_simple_lock = self.contracts[config.SIMPLE_LOCKS].get_deployed_contract_by_index(
                    contract_config['simple_lock'])
                if deployed_simple_lock is None:
                    log_step_fail(f"Aborting setup: Simple lock contract not available! Contract will be dumped.")
                    return

                # whitelist in simple lock contract
                tx_hash = deployed_simple_lock.add_farm_to_whitelist(deployer_account, network_providers.proxy,
                                                                     [deployed_contract.address,
                                                                      deployed_contract.farmingToken,
                                                                      deployed_contract.version.value - 1])

                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist farm in simple locking contract"):
                    return

                # whitelist simple lock contract in farm
                tx_hash = deployed_contract.add_contract_to_whitelist(deployer_account, network_providers.proxy,
                                                                      deployed_simple_lock.address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist simple lock in farm"): return

            deployed_contracts.append(deployed_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def farm_boosted_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []

        for contract_config in contract_structure.deploy_structure_list:
            # get lock factory
            if 'lock_factory' not in contract_config:
                log_step_fail("Aborting deploy: Locked factory contract not existing!")
                return
            locking_contract: Optional[SimpleLockEnergyContract] = None
            locking_contract = self.contracts[config.SIMPLE_LOCKS_ENERGY].get_deployed_contract_by_index(
                contract_config['lock_factory']
            )

            # get contract config
            farmed_token = self.tokens[contract_config['farmed_token']]
            farm_token = contract_config['farm_token']
            farm_token_name = contract_config['farm_token_name']
            lp_contract: Optional[PairContract] = None
            lp_address = config.ZERO_CONTRACT_ADDRESS
            if 'farming_token' in contract_config:
                farming_token = self.tokens[contract_config['farming_token']]
            elif 'farming_pool' in contract_config:
                lp_contract = self.contracts[config.PAIRS_V2].get_deployed_contract_by_index(
                    contract_config['farming_pool'])
                if lp_contract is None:
                    log_step_fail(f'Aborting deploy: farming pool v2 not existing!')
                    return
                farming_token = lp_contract.lpToken
                lp_address = lp_contract.address
            else:
                log_step_fail(f'Aborting deploy: farming token/pool not configured!')
                return

            version = FarmContractVersion.V2Boosted

            # deploy contract
            deployed_contract = FarmContract(farming_token=farming_token,
                                             farm_token="",
                                             farmed_token=farmed_token,
                                             address="",
                                             version=version,
                                             )
            tx_hash, contract_address = deployed_contract.contract_deploy(deployer_account, network_providers.proxy,
                                                                          contract_structure.bytecode,
                                                                          [lp_address,
                                                                           deployer_account.address.bech32()])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "boosted farm"): return
            deployed_contract.address = contract_address
            log_step_pass(f"Farm contract address: {contract_address}")

            # register farm token and save it
            tx_hash = deployed_contract.register_farm_token(deployer_account, network_providers.proxy,
                                                            [farm_token_name, farm_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register farm token"): return
            farm_token_hex = FarmContractDataFetcher(Address(deployed_contract.address),
                                                     network_providers.proxy.url).get_data("getFarmTokenId")
            deployed_contract.farmToken = hex_to_string(farm_token_hex)

            # Whitelist farm in pool if it's linked to pool
            if lp_contract is not None:
                tx_hash = lp_contract.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in pool"): return

            # Set energy contract
            if locking_contract is not None:
                tx_hash = deployed_contract.set_energy_factory_address(deployer_account, network_providers.proxy,
                                                                       locking_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash, "set energy address in farm"): return
            else:
                log_step_fail(f"Failed to set up energy contract in farm. Energy contract not available!")
                return

            # Set locking contract
            if locking_contract is not None:
                tx_hash = deployed_contract.set_locking_address(deployer_account, network_providers.proxy,
                                                                locking_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash, "set locking address in farm"): return
            else:
                log_step_fail(f"Failed to set up locking contract in farm. Locking contract not available!")
                return

            # Set lock epochs
            if 'lock_epochs' not in contract_config:
                lock_epochs = 1440
                log_step_fail(f"Rewards per block not configured! Setting default: {lock_epochs}")
            else:
                lock_epochs = contract_config['lock_epochs']

            tx_hash = deployed_contract.set_lock_epochs(deployer_account, network_providers.proxy,
                                                        lock_epochs)
            if not network_providers.check_simple_tx_status(tx_hash, "set lock epochs in farm"): return

            # Set boosted yields rewards percentage
            if 'boosted_rewards' not in contract_config:
                boosted_rewards = 6000
                log_step_fail(f"Boosted yields rewards percentage not configured! Setting default: {boosted_rewards}")
            else:
                boosted_rewards = contract_config['boosted_rewards']
            tx_hash = deployed_contract.set_boosted_yields_rewards_percentage(deployer_account, network_providers.proxy,
                                                                              boosted_rewards)
            if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields rewards percentage in farm"):
                return

            # Set boosted yields factors
            if "base_const" not in contract_config or \
                    "energy_const" not in contract_config or \
                    "farm_const" not in contract_config or \
                    "min_energy" not in contract_config or \
                    "min_farm" not in contract_config:
                log_step_fail(f"Aborting deploy: Boosted yields factors not configured!")
            tx_hash = deployed_contract.set_boosted_yields_factors(deployer_account, network_providers.proxy,
                                                                   [contract_config['base_const'],
                                                                    contract_config['energy_const'],
                                                                    contract_config['farm_const'],
                                                                    contract_config['min_energy'],
                                                                    contract_config['min_farm']])
            if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields factors in farm"):
                return

            # set rewards per block
            if 'rpb' not in contract_config:
                rpb = 10000
                log_step_fail(f"Rewards per block not configured! Setting default: {rpb}")
            else:
                rpb = contract_config['rpb']
            tx_hash = deployed_contract.set_rewards_per_block(deployer_account, network_providers.proxy,
                                                              rpb)
            if not network_providers.check_simple_tx_status(tx_hash, "set rewards per block in farm"): return

            # set penalty percent
            if 'penalty' not in contract_config:
                log_step_fail(f"Penalty percent not configured! Setting default: 0")
                penalty = 0
            else:
                penalty = contract_config['penalty']
            tx_hash = deployed_contract.set_penalty_percent(deployer_account, network_providers.proxy,
                                                            penalty)
            if not network_providers.check_simple_tx_status(tx_hash, "set penalty percent in farm"): return

            # set minimum farming epochs
            if 'min_farming_epochs' not in contract_config:
                log_step_fail(f"Penalty percent not configured! Setting default: 7")
                min_epochs = 7
            else:
                min_epochs = contract_config['min_farming_epochs']
            tx_hash = deployed_contract.set_minimum_farming_epochs(deployer_account, network_providers.proxy,
                                                                   min_epochs)
            if not network_providers.check_simple_tx_status(tx_hash, "set min farming epochs in farm"): return

            # Set proxy if applicable
            if "proxy" in contract_config or "proxy_v2" in contract_config:
                proxy_contract: Optional[DexProxyContract] = None
                if "proxy" in contract_config:
                    proxy_contract = self.contracts[config.PROXIES]. \
                        get_deployed_contract_by_index(contract_config['proxy'])
                elif "proxy_v2" in contract_config:
                    proxy_contract = self.contracts[config.PROXIES_V2]. \
                        get_deployed_contract_by_index(contract_config['proxy_v2'])
                tx_hash = proxy_contract.add_farm_to_intermediate(deployer_account, network_providers.proxy,
                                                                  contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "set farm to intermediate in proxy"): return

                # whitelist proxy in farm
                tx_hash = deployed_contract.add_contract_to_whitelist(deployer_account, network_providers.proxy,
                                                                      proxy_contract.address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist proxy in farm"): return

            # Set simple lock if applicable
            if "simple_lock" in contract_config:
                deployed_simple_lock: Optional[SimpleLockContract] = None
                deployed_simple_lock = self.contracts[config.SIMPLE_LOCKS].get_deployed_contract_by_index(
                    contract_config['simple_lock'])
                if deployed_simple_lock is None:
                    log_step_fail(f"Aborting setup: Simple lock contract not available! Contract will be dumped.")
                    return

                # whitelist in simple lock contract
                tx_hash = deployed_simple_lock.add_farm_to_whitelist(deployer_account, network_providers.proxy,
                                                                     [deployed_contract.address,
                                                                      deployed_contract.farmingToken,
                                                                      deployed_contract.version.value - 1])

                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "whitelist farm in simple locking contract"):
                    return

                # whitelist simple lock contract in farm
                tx_hash = deployed_contract.add_contract_to_whitelist(deployer_account, network_providers.proxy,
                                                                      deployed_simple_lock.address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist simple lock in farm"): return

            deployed_contracts.append(deployed_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def farm_community_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        contract_structure = self.contracts[contracts_index]
        deployed_contracts = []
        for config_farm in contract_structure.deploy_structure_list:
            # deploy farm contract
            lp_address = config.ZERO_CONTRACT_ADDRESS
            lp_contract: Optional[PairContract] = None
            locked_asset_address = config.ZERO_CONTRACT_ADDRESS
            locked_asset_contract: Optional[LockedAssetContract] = None
            version = FarmContractVersion.V14Unlocked

            farmed_token = self.tokens[config_farm['farmed_token']]
            farm_token = config_farm['farm_token']
            if 'farming_token' in config_farm:
                farming_token = self.tokens[config_farm['farming_token']]
            else:
                # TODO: add check to verify existence of pair contract as prerequisite
                lp_contract = self.contracts[config.PAIRS].deployed_contracts[config_farm['farming_pool']]
                farming_token = lp_contract.lpToken
                lp_address = lp_contract.address

            # deploy contract
            deployed_farm_contract = FarmContract(farming_token=farming_token,
                                                  farm_token="",
                                                  farmed_token=farmed_token,
                                                  address="",
                                                  version=version,
                                                  )
            tx_hash, contract_address = deployed_farm_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode,
                [lp_address, locked_asset_address])
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "farm"): return
            deployed_farm_contract.address = contract_address
            log_step_pass(f"Farm contract address: {contract_address}")

            # register farm token and save it
            tx_hash = deployed_farm_contract.register_farm_token(deployer_account, network_providers.proxy, farm_token)
            if not network_providers.check_complex_tx_status(tx_hash, "register farm token"): return
            farm_token_hex = FarmContractDataFetcher(Address(deployed_farm_contract.address),
                                                     network_providers.proxy.url).get_data("getFarmTokenId")
            deployed_farm_contract.farmToken = hex_to_string(farm_token_hex)

            # Whitelist farm in pool if it's linked to pool
            if lp_contract is not None:
                tx_hash = lp_contract.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in pool"): return

            # Whitelist farm in locked asset contract or provide mint role for rewards
            if locked_asset_contract is not None:
                tx_hash = locked_asset_contract.whitelist_contract(deployer_account, network_providers.proxy,
                                                                   contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "whitelist farm in locked asset contract"): return
            else:
                tx_hash = self.esdt_contract.set_special_role_token(deployer_account, network_providers.proxy,
                                                                    [farmed_token, contract_address,
                                                                     "ESDTRoleLocalMint"])
                if not network_providers.check_complex_tx_status(tx_hash, "set special role on farmed token"): return

            # set rewards per block
            tx_hash = deployed_farm_contract.set_rewards_per_block(deployer_account, network_providers.proxy,
                                                                   config_farm['rpb'])
            if not network_providers.check_simple_tx_status(tx_hash, "set rewards per block in farm"): return

            # Set proxy if applicable
            if "proxy" in config_farm:
                proxy_contract: DexProxyContract
                proxy_contract = self.contracts[config.PROXIES].deployed_contracts[config_farm['proxy']]
                tx_hash = proxy_contract.add_farm_to_intermediate(deployer_account, network_providers.proxy,
                                                                  contract_address)
                if not network_providers.check_simple_tx_status(tx_hash, "set farm to intermediate in proxy"): return

            deployed_contracts.append(deployed_farm_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def price_discovery_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        deployed_contracts = []
        contract_structure = self.contracts[contracts_index]
        for config_pd in contract_structure.deploy_structure_list:
            config_pd_pool = self.contracts[config.PAIRS].deploy_structure_list[config_pd["pool"]]
            if not self.contracts[config.SIMPLE_LOCKS].deployed_contracts:
                log_step_fail("Skipped deploy for price discovery. Simple lock contract not existing.")
                return
            deployed_simple_lock: SimpleLockContract
            deployed_simple_lock = self.contracts[config.SIMPLE_LOCKS].deployed_contracts[0]
            simple_lock_sc_address = deployed_simple_lock.address
            # start_block = dex_infra.extended_proxy.get_round() + 10
            deployer_shard = network_providers.api.get_address_details(deployer_account.address.bech32())['shard']
            start_block = network_providers.proxy.get_network_status(deployer_shard).nonce + 10
            unlock_epoch = network_providers.proxy.get_network_status(deployer_shard).epoch_number + 1
            phase_time = 50

            launched_token = self.tokens[config_pd_pool['launched_token']]
            accepted_token = self.tokens[config_pd_pool['accepted_token']]
            redeem_token = config_pd['redeem_token']

            # contract is set to start 10 blocks after deploy (1 minute)
            # each phase lasts 150 blocks (15 minutes)
            # deploy contract
            deployed_pd_contract = PriceDiscoveryContract(
                launched_token_id=launched_token,
                accepted_token_id=accepted_token,
                redeem_token="",  # will be filled after token issue
                first_redeem_token_nonce=1,
                second_redeem_token_nonce=2,
                address="",  # will be filled after deploy
                locking_sc_address=simple_lock_sc_address,
                start_block=start_block,
                no_limit_phase_duration_blocks=phase_time,
                linear_penalty_phase_duration_blocks=phase_time,
                fixed_penalty_phase_duration_blocks=phase_time,
                unlock_epoch=unlock_epoch,
                min_launched_token_price=10000000000000000000,  # 10:1 ratio
                min_penalty_percentage=1000000000000,  # 10%
                max_penalty_percentage=2000000000000,
                fixed_penalty_percentage=5000000000000,
            )

            tx_hash, contract_address = deployed_pd_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "price discovery"): return
            deployed_pd_contract.address = contract_address
            log_step_pass(f"Price discovery contract address: {contract_address}")

            # issue redeem token
            tx_hash = deployed_pd_contract.issue_redeem_token(deployer_account, network_providers.proxy, redeem_token)
            if not network_providers.check_complex_tx_status(tx_hash, "issue redeem token"): return
            redeem_token_hex = PriceDiscoveryContractDataFetcher(Address(deployed_pd_contract.address),
                                                                 network_providers.proxy.url).get_data("getRedeemTokenId")
            if hex_to_string(redeem_token_hex) == "EGLD":
                log_step_fail(f"FAIL: contract failed to set the issued token!")
                return
            deployed_pd_contract.redeem_token = hex_to_string(redeem_token_hex)

            # create initial redeem tokens
            tx_hash = deployed_pd_contract.create_initial_redeem_tokens(deployer_account, network_providers.proxy)
            if not network_providers.check_complex_tx_status(tx_hash, "create initial redeem tokens"): return

            deployed_contracts.append(deployed_pd_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def staking_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        deployed_contracts = []
        contract_structure = self.contracts[contracts_index]
        for config_staking in contract_structure.deploy_structure_list:
            staking_token = self.tokens[config_staking['staking_token']]
            stake_token = config_staking['stake_token']
            stake_token_name = config_staking['stake_token_name']
            max_apr = config_staking['apr']
            rewards_per_block = config_staking['rpb']
            unbond_epochs = config_staking['unbond_epochs']
            topup_rewards = config_staking['rewards']

            if contracts_index == config.STAKINGS:
                version = StakingContractVersion.V1
            elif contracts_index == config.STAKINGS_V2:
                version = StakingContractVersion.V2
            elif contracts_index == config.STAKINGS_BOOSTED:
                version = StakingContractVersion.V3Boosted
            else:
                log_step_fail(f"FAIL: unknown staking contract version: {contracts_index}")
                return

            # deploy contract
            deployed_staking_contract = StakingContract(
                farming_token=staking_token,
                max_apr=max_apr,
                rewards_per_block=rewards_per_block,
                unbond_epochs=unbond_epochs,
                version=version
            )

            args = []
            if version != StakingContractVersion.V1:
                args.append(deployer_account.address.bech32())
                if 'admin' in config_staking:
                    args.append(config_staking['admin'])

            tx_hash, contract_address = deployed_staking_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode, args)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "stake contract"): return
            deployed_staking_contract.address = contract_address
            log_step_pass(f"Stake contract address: {contract_address}")

            # register farm token and save it
            tx_hash = deployed_staking_contract.register_farm_token(deployer_account, network_providers.proxy,
                                                                    [stake_token_name, stake_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register stake token"): return
            farm_token_hex = StakingContractDataFetcher(Address(deployed_staking_contract.address),
                                                        network_providers.proxy.url).get_data("getFarmTokenId")
            deployed_staking_contract.farm_token = hex_to_string(farm_token_hex)

            # set rewards per block
            tx_hash = deployed_staking_contract.set_rewards_per_block(deployer_account, network_providers.proxy,
                                                                      rewards_per_block)
            if not network_providers.check_simple_tx_status(tx_hash, "set rewards per block in stake contract"): return

            if version == StakingContractVersion.V3Boosted:
                # Set boosted yields rewards percentage
                if 'boosted_rewards' not in config_staking:
                    boosted_rewards = 6000
                    log_step_fail(f"Boosted yields rewards percentage not configured! "
                                  f"Setting default: {boosted_rewards}")
                else:
                    boosted_rewards = config_staking['boosted_rewards']
                tx_hash = deployed_staking_contract.set_boosted_yields_rewards_percentage(deployer_account,
                                                                                          network_providers.proxy,
                                                                                          boosted_rewards)
                if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields rewards percentage in farm"):
                    return

                # Set boosted yields factors
                if "base_const" not in config_staking or \
                        "energy_const" not in config_staking or \
                        "farm_const" not in config_staking or \
                        "min_energy" not in config_staking or \
                        "min_farm" not in config_staking:
                    log_step_fail(f"Aborting deploy: Boosted yields factors not configured!")
                tx_hash = deployed_staking_contract.set_boosted_yields_factors(deployer_account,
                                                                               network_providers.proxy,
                                                                               [config_staking['base_const'],
                                                                                config_staking['energy_const'],
                                                                                config_staking['farm_const'],
                                                                                config_staking['min_energy'],
                                                                                config_staking['min_farm']])
                if not network_providers.check_simple_tx_status(tx_hash, "set boosted yields factors in farm"):
                    return

            # topup rewards
            tx_hash = deployed_staking_contract.topup_rewards(deployer_account, network_providers.proxy, topup_rewards)
            if not network_providers.check_simple_tx_status(tx_hash, "topup rewards in stake contract"): return

            deployed_contracts.append(deployed_staking_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts

    def metastaking_deploy(self, contracts_index: str, deployer_account: Account, network_providers: NetworkProviders):
        deployed_contracts = []
        contract_structure = self.contracts[contracts_index]
        for config_metastaking in contract_structure.deploy_structure_list:
            staking_token = self.tokens[config_metastaking['token']]
            metastake_token = config_metastaking['metastake_token']
            metastake_token_name = config_metastaking['metastake_token_name']
            lp: Optional[PairContract] = None
            if 'pool' in config_metastaking:
                lp = self.contracts[config.PAIRS].get_deployed_contract_by_index(config_metastaking['pool'])
            elif 'pool_v2' in config_metastaking:
                lp = self.contracts[config.PAIRS_V2].get_deployed_contract_by_index(config_metastaking['pool_v2'])
            else:
                log_step_fail(f"Aborting deploy: no farm pool for metastaking deploy")
                return
            farm: Optional[FarmContract] = None
            if 'farm_unlocked' in config_metastaking:
                farm = self.contracts[config.FARMS_UNLOCKED].get_deployed_contract_by_index(
                    config_metastaking['farm_unlocked'])
            elif 'farm_locked' in config_metastaking:
                farm = self.contracts[config.FARMS_LOCKED].get_deployed_contract_by_index(
                    config_metastaking['farm_locked'])
            elif 'farm_boosted' in config_metastaking:
                farm = self.contracts[config.FARMS_V2].get_deployed_contract_by_index(
                    config_metastaking['farm_boosted'])
            else:
                log_step_fail(f"Aborting deploy: no farm configured for metastaking deploy")
                return

            staking: Optional[StakingContract] = None
            if 'staking' in config_metastaking:
                staking = self.contracts[config.STAKINGS].get_deployed_contract_by_index(config_metastaking['staking'])
            elif 'staking_v2' in config_metastaking:
                staking = self.contracts[config.STAKINGS_V2].get_deployed_contract_by_index(
                    config_metastaking['staking_v2'])
            elif 'staking_boosted' in config_metastaking:
                staking = self.contracts[config.STAKINGS_BOOSTED].get_deployed_contract_by_index(
                    config_metastaking['staking_boosted'])

            if contracts_index == config.METASTAKINGS:
                version = MetaStakingContractVersion.V1
            elif contracts_index == config.METASTAKINGS_V2:
                version = MetaStakingContractVersion.V2
            elif contracts_index == config.METASTAKINGS_BOOSTED:
                version = MetaStakingContractVersion.V3Boosted
            else:
                log_step_fail(f"Aborting deploy: unknown metastaking contract version")
                return

            # deploy contract
            deployed_metastaking_contract = MetaStakingContract(
                staking_token=staking_token,
                lp_token=lp.lpToken,
                farm_token=farm.farmToken,
                stake_token=staking.farm_token,
                lp_address=lp.address,
                farm_address=farm.address,
                stake_address=staking.address,
                version=version
            )

            tx_hash, contract_address = deployed_metastaking_contract.contract_deploy(
                deployer_account, network_providers.proxy, contract_structure.bytecode)
            # check for deployment success and save the deployed address
            if not network_providers.check_deploy_tx_status(tx_hash, contract_address, "metastake"):
                return
            deployed_metastaking_contract.address = contract_address
            log_step_pass(f"Metastake contract address: {contract_address}")

            # register metastake token and save it
            tx_hash = deployed_metastaking_contract.register_dual_yield_token(deployer_account, network_providers.proxy,
                                                                              [metastake_token_name, metastake_token])
            if not network_providers.check_complex_tx_status(tx_hash, "register metastake token"):
                return
            farm_token_hex = MetaStakingContractDataFetcher(Address(deployed_metastaking_contract.address),
                                                            network_providers.proxy.url).get_data("getDualYieldTokenId")
            deployed_metastaking_contract.metastake_token = hex_to_string(farm_token_hex)

            # whitelist in pair contract
            tx_hash = lp.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
            if not network_providers.check_simple_tx_status(tx_hash,
                                                            "whitelist metastaking contract in pair contract"):
                return

            # whitelist in farm contract
            tx_hash = farm.add_contract_to_whitelist(deployer_account, network_providers.proxy, contract_address)
            if not network_providers.check_simple_tx_status(tx_hash,
                                                            "whitelist metastaking contract in farm contract"):
                return

            # whitelist in staking contract
            tx_hash = staking.whitelist_contract(deployer_account, network_providers.proxy, contract_address)
            if not network_providers.check_simple_tx_status(tx_hash,
                                                            "whitelist metastaking contract in staking contract"):
                return

            if version == MetaStakingContractVersion.V3Boosted:
                # set burn role from staking contract
                tx_hash = staking.set_burn_role_for_address(deployer_account, network_providers.proxy, contract_address)
                if not network_providers.check_simple_tx_status(tx_hash,
                                                                "set burn role from staking contract"):
                    return

            deployed_contracts.append(deployed_metastaking_contract)
        self.contracts[contracts_index].deployed_contracts = deployed_contracts
