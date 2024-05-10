# mx-sdk-py-exchange
Python utility toolkit for xExchange interactions.

Features include:
- Configurable DEX SC setup deployment
  - save/load setup
  - additive deployment to existing setup
- Interaction with DEX SCs via exposed endpoints
- Data reading from DEX SCs via exposed views
- DEX SC operation trackers 
- Attributes decoding tool
- Setup updater tool

### Disclaimer
This is currently a work in progress and should be treated as such.
Modules are under migration process to mxpy, need a lot of cleanup & refactors and may not be functional/used anylonger.

### Virtual environment

Create a virtual environment and install the dependencies:

```
python3 -m venv ./.venv
source ./.venv/bin/activate
pip install -r ./requirements.txt --upgrade
pip install -r ./requirements-dev.txt --upgrade
```

### Operation
Start by initializing the environment:
```
export PYTHONPATH=.
```

#### Config
To configure the exchange setup and operation, config.py has to be edited accordingly.
In the config.py file you should configure the following:
- used network
- PEM accounts for exchange operations
- DEX deploy configuration
- DEX contract binaries paths

#### Deploy
The dex_deploy script is used to deploy a configured exchange setup.
An exchange setup consists of several elements usually gathered in a dedicated directory:
- deploy_structure.json - defines the exchange setup structure containing definitions for each contract type
- deployed_*.json - contains already deployed tokens/contracts for this specific exchange setup

To deploy a specific exchange setup, configure the desired exchange setup directory in config.py then run:
```
python3 deploy/dex_deploy.py --deploy-contracts=clean --deploy-tokens=clean
```
The flags `--deploy-contracts` and `--deploy-tokens` can be set to `clean` or `config` to either deploy a clean setup 
(ignoring the already deployed contracts) or add on top of an existing one (considering the already deployed contracts).

#### Scenarios
To run a defined scenario, just run the desired scenario script located in /scenarios directory, such as:
```
python3 scenarios/stress_create_positions.py
```

## Tools
### Contracts upgrader
The contracts_upgrader.py script is used to upgrade the exchange setup contracts to new versions or ease the experience of
performing steps over large/tailored number of contracts.

Usage example:
```
python3 tools/contracts_upgrader.py --disable-pair-creation
python3 tools/contracts_upgrader.py --fetch-pairs     # fetches all pairs registered in the router contract
python3 tools/contracts_upgrader.py --fetch-stakings  # fetches all stakings from the xexchange graphQL service
python3 tools/contracts_upgrader.py --fetch-pause-state   # fetches pause state for all previously fetched contracts
python3 tools/contracts_upgrader.py --pause-stakings
python3 tools/contracts_upgrader.py --pause-pairs
python3 tools/contracts_upgrader.py --upgrade-template --compare-state
python3 tools/contracts_upgrader.py --upgrade-pairs --compare-state
python3 tools/contracts_upgrader.py --deploy-pair-view
python3 tools/contracts_upgrader.py --resume-pairs    # brings pairs into their original state (needs fetch-pause-state beforehand)
python3 tools/contracts_upgrader.py --resume-stakings   # brings stakings into their original state (needs fetch-pause-state beforehand)
python3 tools/contracts_upgrader.py --enable-pair-creation
```