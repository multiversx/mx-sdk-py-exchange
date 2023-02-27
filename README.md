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
```