import random
from datetime import datetime

import config
from contracts.farm_contract import FarmContract
from contracts.metastaking_contract import MetaStakingContract
from contracts.pair_contract import PairContract
from deploy.dex_structure import DeployStructure
from utils.results_logger import ResultsLogger
from utils.utils_tx import NetworkProviders
from trackers.farm_economics_tracking import FarmEconomics, FarmAccountEconomics
from trackers.pair_economics_tracking import PairEconomics
from trackers.staking_economics_tracking import StakingEconomics
from trackers.metastaking_economics_tracking import MetastakingEconomics
from trackers.concrete_observer import Observable
from utils.utils_chain import Account, BunchOfAccounts, WrapperAddress as Address


class Context:
    def __init__(self):

        self.deploy_structure = DeployStructure()
        self.network_provider = NetworkProviders(config.DEFAULT_API, config.DEFAULT_PROXY)

        self.deployer_account = Account.from_file(config.DEFAULT_OWNER)

        if "shadowfork" in config.DEFAULT_PROXY and config.SF_DEX_REFERENCE_ADDRESS:
            # get owner of the SF reference contract
            owner = self.network_provider.proxy.get_account(Address(config.SF_DEX_REFERENCE_ADDRESS)).owner_address.to_bech32()
            print(f"Shadowfork detected. Owner: {owner}")

            config.DEX_OWNER_ADDRESS = owner
            config.DEX_ADMIN_ADDRESS = owner

        if config.DEX_OWNER_ADDRESS:    # manual override only for shadowforks
            self.deployer_account.address = Address(config.DEX_OWNER_ADDRESS)

        if config.DEFAULT_ADMIN == config.DEFAULT_OWNER:
            self.admin_account = self.deployer_account
        else:
            self.admin_account = Account.from_file(config.DEFAULT_ADMIN)
            
        if config.DEX_ADMIN_ADDRESS:  # manual override only for shadowforks
            self.admin_account.address = Address(config.DEX_ADMIN_ADDRESS)

        self.accounts = BunchOfAccounts.load_accounts_from_files([config.DEFAULT_ACCOUNTS])
        self.nonces_file = config.DEFAULT_WORKSPACE / "_nonces.json"
        self.debug_level = 1

        # logger
        self.start_time = datetime.now()
        self.results_logger = ResultsLogger(f"{self.start_time.day}_{self.start_time.hour}_{self.start_time.minute}_event_results.json")

        self.add_liquidity_max_amount = 0.1
        self.remove_liquidity_max_amount = 0.5
        self.numEvents = 100  # sys.maxsize
        self.pair_slippage = 0.05
        self.swap_min_tokens_to_spend = 0
        self.swap_max_tokens_to_spend = 0.8

        self.enter_farm_max_amount = 0.2
        self.exit_farm_max_amount = 0.5

        self.enter_metastake_max_amount = 0.1
        self.exit_metastake_max_amount = 0.3

        # BEGIN DEPLOY
        self.deployer_account.sync_nonce(self.network_provider.proxy)
        self.admin_account.sync_nonce(self.network_provider.proxy)

        # TOKENS HANDLING
        self.deploy_structure.deploy_tokens(self.deployer_account, self.network_provider, False)

        # configure contracts and deploy them
        # DEPLOY CONTRACTS
        self.deploy_structure.deploy_structure(self.deployer_account, self.network_provider, False)

        # CONTRACTS START
        self.deploy_structure.start_deployed_contracts(self.deployer_account, self.network_provider, False)

        # deploy closing
        self.deploy_structure.print_deployed_contracts()

        self.observable = Observable()
        # self.init_observers()     # call should be parameterized so that observers can be disabled programmatically

    def init_observers(self):

        farm_unlocked_contracts = self.deploy_structure.contracts[config.FARMS_UNLOCKED].deployed_contracts
        for contract in farm_unlocked_contracts:
            contract_dict = contract.get_config_dict()
            observer = FarmEconomics(contract_dict['address'], contract_dict['version'], self.network_provider)
            self.observable.subscribe(observer)

        farm_locked_contracts = self.deploy_structure.contracts[config.FARMS_LOCKED].deployed_contracts
        for contract in farm_locked_contracts:
            contract_dict = contract.get_config_dict()
            observer = FarmEconomics(contract_dict['address'], contract_dict['version'], self.network_provider)
            self.observable.subscribe(observer)

        for acc in self.accounts.get_all():
            account_observer = FarmAccountEconomics(acc.address, self.network_provider)
            self.observable.subscribe(account_observer)

        pair_contracts = self.deploy_structure.contracts[config.PAIRS].deployed_contracts
        for contract in pair_contracts:
            contract_dict = contract.get_config_dict()
            observer = PairEconomics(contract_dict['address'], contract.firstToken, contract.secondToken, self.network_provider)
            self.observable.subscribe(observer)

        staking_contracts = self.deploy_structure.contracts[config.STAKINGS].deployed_contracts
        for contract in staking_contracts:
            contract_dict = contract.get_config_dict()
            observer = StakingEconomics(contract_dict['address'], self.network_provider)
            self.observable.subscribe(observer)

        metastaking_contracts = self.deploy_structure.contracts[config.METASTAKINGS].deployed_contracts
        for contract in metastaking_contracts:
            contract_dict = contract.get_config_dict()
            farm_contract = self.get_farm_contract_by_address(contract_dict['farm_address'])
            pair_contract = self.get_pair_contract_by_address(contract_dict['lp_address'])
            observer = MetastakingEconomics(contract_dict['address'], contract_dict['stake_address'],
                                            farm_contract, pair_contract, self.network_provider)
            self.observable.subscribe(observer)

    def get_slippaged_below_value(self, value: int):
        return value - int(value * self.pair_slippage)

    def get_slippaged_above_value(self, value: int):
        return value + int(value * self.pair_slippage)

    def set_swap_spend_limits(self, swap_min_spend, swap_max_spend):
        self.swap_min_tokens_to_spend = swap_min_spend
        self.swap_max_tokens_to_spend = swap_max_spend

    def get_router_v2_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.ROUTER_V2, index)

    def get_simple_lock_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.SIMPLE_LOCKS, index)

    def get_pair_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.PAIRS, index)

    def get_pair_v2_contract(self, index: int) -> PairContract:
        return self.deploy_structure.get_deployed_contract_by_index(config.PAIRS_V2, index)

    def get_fee_collector_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.FEES_COLLECTORS, index)

    def get_unlocked_farm_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.FARMS_UNLOCKED, index)

    def get_locked_farm_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.FARMS_LOCKED, index)

    def get_staking_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.STAKINGS, index)

    def get_metastaking_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.METASTAKINGS, index)

    def get_price_discovery_contract(self, index: int):
        return self.deploy_structure.get_deployed_contract_by_index(config.PRICE_DISCOVERIES, index)

    def get_contracts(self, contract_label: str):
        return self.deploy_structure.get_deployed_contracts(contract_label)

    def get_farm_contract_by_address(self, address: str) -> FarmContract:
        contract = self.deploy_structure.get_deployed_contract_by_address(config.FARMS_LOCKED, address)
        if contract is None:
            contract = self.deploy_structure.get_deployed_contract_by_address(config.FARMS_UNLOCKED, address)
        if contract is None:
            contract = self.deploy_structure.get_deployed_contract_by_address(config.FARMS_V2, address)

        return contract

    def get_random_farm_contract(self):
        return random.choice([random.choice(self.deploy_structure.get_deployed_contracts(config.FARMS_LOCKED)),
                             random.choice(self.deploy_structure.get_deployed_contracts(config.FARMS_UNLOCKED))])

    def get_pair_contract_by_address(self, address: str) -> PairContract:
        contract = self.deploy_structure.get_deployed_contract_by_address(config.PAIRS, address)
        if contract is None:
            contract = self.deploy_structure.get_deployed_contract_by_address(config.PAIRS_V2, address)

        return contract

    def get_random_pair_contract(self):
        return random.choice(self.deploy_structure.get_deployed_contracts(config.PAIRS))

    def get_random_user_account(self):
        account_list = self.accounts.get_all()
        return random.choice(account_list)

    def get_random_price_discovery_contract(self):
        return random.choice(self.deploy_structure.get_deployed_contracts(config.PRICE_DISCOVERIES))

    def get_random_metastaking_contract(self) -> MetaStakingContract:
        return random.choice(self.deploy_structure.get_deployed_contracts(config.METASTAKINGS))

    def get_contract_index(self, contract_label: str, contract):
        return self.deploy_structure.get_deployed_contracts(contract_label).index(contract)
