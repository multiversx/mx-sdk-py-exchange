"""
Farm Staking Integration Tests - Category 10: Delegation / On-Behalf Operations

Tests delegated (on-behalf) staking operations via stakeFarmOnBehalf.
Verifies that unauthorized callers are correctly rejected.

Coverage: 1 test (P2)
"""

import pytest
from events.farm_events import EnterFarmEvent
from utils.logger import get_logger
from tests.helpers import TransactionAssertions
from tests.integration.farm_staking import (
    _check_staking_has_code,
    _get_stake_amount,
)

logger = get_logger(__name__)


class TestDelegation:
    """Test suite for on-behalf delegation operations"""

    def test_on_behalf_unauthorized_fails(
        self,
        staking_contract,
        alice,
        bob,
        network_providers,
        blockchain_controller,
        ensure_esdt_amounts,
    ):
        """Non-whitelisted caller cannot perform on-behalf operations"""
        logger.info("TEST: On-behalf unauthorized fails")

        if not _check_staking_has_code(staking_contract, network_providers.proxy):
            pytest.skip("Staking contract bytecode not loaded on chain simulator")

        farming_token = staking_contract.farming_token
        stake_amount = _get_stake_amount(staking_contract, network_providers.proxy)

        # Fund bob with farming tokens
        ensure_esdt_amounts(bob, {farming_token: stake_amount})

        # Bob tries to stake on behalf of alice without being whitelisted
        bob.sync_nonce(network_providers.proxy)
        enter_event = EnterFarmEvent(
            farming_token=farming_token,
            farming_nonce=0,
            farming_amount=stake_amount,
            farm_token=staking_contract.farm_token,
            farm_nonce=0,
            farm_amount=0,
            on_behalf=alice.address.to_bech32(),
        )
        tx_hash = staking_contract.stake_farm_on_behalf(network_providers, bob, enter_event)
        blockchain_controller.wait_for_tx(tx_hash)

        TransactionAssertions.assert_transaction_failed(tx_hash, network_providers.proxy)

        logger.info("✓ Unauthorized on-behalf operation correctly rejected")
