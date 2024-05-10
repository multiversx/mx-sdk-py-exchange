from pathlib import Path

from contracts.simple_lock_energy_contract import SimpleLockEnergyContract
from testutils.mock_network_provider import MockNetworkProvider
from utils.utils_chain import Account

testdata_folder = Path(__file__).parent.parent / "testdata"


def test_deploy_contract():
    account = Account(pem_file=testdata_folder / "alice.pem")
    bytecode_path = testdata_folder / "dummy.wasm"
    bytecode = bytecode_path.read_bytes()
    network_provider = MockNetworkProvider()

    contract = SimpleLockEnergyContract(
        base_token="TEST-987654"
    )

    tx_hash, contract_address = contract.contract_deploy(
        proxy=network_provider,
        deployer=account,
        bytecode_path=bytecode_path,
        args=[
            "TEST-123456",
            "erd1qqqqqqqqqqqqqpgqaxa53w6uk43n6dhyt2la6cd5lyv32qn4396qfsqlnk",
            42,
            [360, 720, 1440],
            [5000, 7000, 8000]
        ]
    )

    assert tx_hash == "cbde33c54afde0a215961568755167c60255a95c70f1a8d91f0b29dc0baa37c2"
    assert contract_address == "erd1qqqqqqqqqqqqqpgqak8zt22wl2ph4tswtyc39namqx6ysa2sd8ss4xmlj3"

    tx_on_network = network_provider.get_transaction(tx_hash)
    assert tx_on_network.data == f"{bytecode.hex()}@0500@0504@544553542d393837363534@544553542d313233343536@00000000000000000500e9bb48bb5cb5633d36e45abfdd61b4f9191502758974@2a@0168@1388@02d0@1b58@05a0@1f40"
