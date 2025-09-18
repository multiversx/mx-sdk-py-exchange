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
This is a constant work in progress and should be treated as such.
Some modules need a lot of cleanup & refactors and some may even not be functional/used anylonger due to
too many improvements or mxpy migrations that weren't worth propagating fully.
It was meant to be used only internally anyway, but I'm a merciful god.
Therefore, please thread with extreme care.

## Operation
### Virtual environment

Create a virtual environment and install the dependencies:

```bash
python3 -m venv ./.venv
source ./.venv/bin/activate
pip install -r ./requirements.txt --upgrade
```

### Prerequisites
Start by initializing the root python path to execute scripts from:
```bash
export PYTHONPATH=.
```

### Config
To configure the exchange setup and operation, the `config` module has to be edited accordingly.
The config module `config/__init__.py` exposes operation parameters to control aspects like:
- used network
- PEM accounts for exchange operations
- DEX deploy configuration
- DEX contract binaries paths
- operational directory paths
- logging settings

#### Environment variables
Environments can be easily changed to the preconfigured ones using envar/.env file:
```bash
export MX_DEX_ENV=mainnet
```
Available preconfigured environments: 
  - mainnet
  - devnet
  - testnet
  - shadowfork4
  - chainsim
  - custom

Almost all config operation parameters can be overriden via envars/.env file.
```bash
export DEFAULT_PROXY=https://custom-gateway.example.com
export DEFAULT_OWNER=wallets/custom.pem
export DEFAULT_CONFIG_SAVE_PATH=deploy/configs-custom
export FORCE_CONTINUE_PROMPT=true
export LOG_LEVEL=INFO
```

#### .env File Support
Create a `.env` file in your project root to set whichever exposed configuration values:

```env
# Environment selection
MX_DEX_ENV=devnet

# Network configuration
DEFAULT_PROXY=https://devnet-gateway.multiversx.com
```

An `env.example` file is available in root directory.

#### Environment Variable Priority

1. **Environment Variables** (highest priority)
2. **`.env` File**
3. **Environment-specific defaults**
4. **Base defaults** (lowest priority)


### Deploy
The dex_deploy script is used to deploy a configured exchange setup.
An exchange setup consists of several elements usually gathered in a dedicated directory:
- deploy_structure.json - defines the exchange setup structure containing definitions for each contract type
- deployed_*.json - contains already deployed tokens/contracts for this specific exchange setup

To deploy a specific exchange setup, configure the desired exchange setup directory in config.py then run:
```bash
python3 deploy/dex_deploy.py --deploy-contracts=clean --deploy-tokens=clean
```
The flags `--deploy-contracts` and `--deploy-tokens` can be set to `clean` or `config` to either deploy a clean setup 
(ignoring the already deployed contracts) or add on top of an existing one (considering the already deployed contracts).

### Scenarios
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