# Upgrade procedure for v3.1 release

## Prerequisites

[ ] Add some egld into owner account.
[ ] Make some space for the repo and source downloads
[ ] Clone https://github.com/multiversx/mx-sdk-py-exchange 
[ ] python3 -m venv .venv
[ ] source .venv/bin/activate
[ ] pip3 install -r requirements.txt
[ ] Edit config.py

1. export PYTHONPATH=.
2. python3 tools/runner.py stakings contract fetch-all
3. python3 tools/runner.py farms contract fetch-all
4. python3 tools/runner.py all fetch-pause-state
5. python3 tools/runner.py farms contract pause-all
6. python3 tools/runner.py stakings contract pause-all
7. python3 tools/runner.py energy-factory contract pause
8. python3 tools/runner.py farms contract upgrade-all --compare-states --bytecode=https://github.com/multiversx/mx-exchange-sc/releases/download/v3.1.1/farm-with-locked-rewards.wasm
9. python3 tools/runner.py stakings contract upgrade --all --compare-states --bytecode=https://github.com/multiversx/mx-exchange-sc/releases/download/v3.1.1/farm-staking.wasm
10. python3 tools/runner.py energy-factory contract upgrade --bytecode=https://github.com/multiversx/mx-exchange-sc/releases/download/v3.1.1/energy-factory.wasm
11. python3 tools/runner.py generic contract upgrade --compare-states --address=erd1qqqqqqqqqqqqqpgqu64gygjs5ted4rupaewaszyhaxl9lv7m2jpsw47nzr --bytecode=https://github.com/multiversx/mx-exchange-sc/releases/download/v3.1.1/locked-token-wrapper.wasm
12. python3 tools/runner.py router contract upgrade --compare-states --address=erd1qqqqqqqqqqqqqpgqq66xk9gfr4esuhem3jru86wg5hvp33a62jps2fy57p --bytecode=https://github.com/multiversx/mx-exchange-sc/releases/download/v3.1.1/router.wasm
13. python3 tools/runner.py router contract resume
14. python3 tools/runner.py energy-factory contract resume
15. python3 tools/runner.py farms contract resume-all
16. python3 tools/runner.py stakings contract resume-all
