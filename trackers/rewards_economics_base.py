"""
Shared machinery behind the rewards-bearing economics trackers.

The farm and staking trackers watch the same kind of contract: one that accrues rewards per block,
divides them across a token supply by a rewards-per-share figure, and guards that arithmetic with a
division safety constant. They had drifted into two copies of the same code — the invariant check
was byte-for-byte identical, and the tracking report differed only in which fields it named.

Both now live here once, driven by three declarations each subclass supplies:

- `_rewards_data_fetcher` — which fetcher the invariant check reads the four shared views from,
  since the two trackers hold theirs under different attribute names.
- `_TRACKING_HEADER` — the label opening the report, before the contract address.
- `_TRACKED_FIELDS` — the reported fields in print order, as (label, attribute) pairs.

`_track_event` captures the third shared shape: every tracked event checks invariants, checks the
properties specific to that event, checks the transaction's data, then refreshes.

Everything this class adds beyond the two methods it lifts is deliberately underscore-prefixed. The
Public Surface is frozen for the cleanup pass (ADR-0001), and a new public member here would appear
on every subclass at once; the class itself is package-private for the same reason.
"""

from collections.abc import Callable

from trackers.abstract_observer import Subscriber
from utils.utils_generic import log_step_fail, log_step_pass, log_substep


class _RewardsEconomicsBase(Subscriber):
    """A tracker for a contract that accrues rewards per block against a token supply."""

    # Opens the tracking report, followed by the contract's bech32 address.
    _TRACKING_HEADER: str = ""

    # Reported fields in print order: the label shown, and the attribute holding the value.
    _TRACKED_FIELDS: tuple[tuple[str, str], ...] = ()

    @property
    def _rewards_data_fetcher(self):
        """The fetcher for this contract's reward views. Subclasses point this at their own."""
        raise NotImplementedError

    def _refresh_tracking_data(self) -> None:
        """Re-read tracked state after an event. Subclasses use their own established method."""
        raise NotImplementedError

    def check_invariant_properties(self):
        """Report any tracked property that moved in a direction the contract should not allow."""
        data_fetcher = self._rewards_data_fetcher
        new_rewards_per_share = data_fetcher.get_data("getRewardPerShare")
        new_last_rewards_block_nonce = data_fetcher.get_data("getLastRewardBlockNonce")
        chain_rewards_per_block = data_fetcher.get_data("getPerBlockRewardAmount")
        chain_division_safety_constant = data_fetcher.get_data("getDivisionSafetyConstant")

        if self.rewards_per_share > new_rewards_per_share:
            log_step_fail("TEST CHECK FAIL: Rewards per share decreased!")
            log_substep(f"Old rewards per share: {self.rewards_per_share}")
            log_substep(f"New rewards per share: {new_rewards_per_share}")
        if self.last_rewards_block_nonce > new_last_rewards_block_nonce:
            log_step_fail("TEST CHECK FAIL: Last rewards block nonce decreased!")
            log_substep(f"Old rewards block nonce: {self.last_rewards_block_nonce}")
            log_substep(f"New rewards block nonce: {new_last_rewards_block_nonce}")
        if self.rewards_per_block != chain_rewards_per_block:
            log_step_fail("TEST CHECK FAIL: Rewards per block has changed!")
            log_substep(f"Old rewards per block: {self.rewards_per_block}")
            log_substep(f"New rewards per block: {chain_rewards_per_block}")
        if self.division_safety_constant != chain_division_safety_constant:
            log_step_fail("TEST CHECK FAIL: Division safety constant has changed!")
            log_substep(f"Old division safety constant: {self.division_safety_constant}")
            log_substep(f"New division safety constant: {chain_division_safety_constant}")

        log_step_pass("Checked invariant properties!")

    def report_current_tracking_data(self):
        """Print the tracked state as it currently stands, without re-reading the chain."""
        print(f"{self._TRACKING_HEADER}: {self.contract_address.bech32()}")
        for label, attribute in self._TRACKED_FIELDS:
            print(f"{label}: {getattr(self, attribute)}")

    def _track_event(
        self,
        properties_check: Callable[[], None],
        data_check: Callable[..., None],
        *data_check_args,
    ) -> None:
        """Run the checks every tracked event runs, then refresh the tracked state."""
        self.check_invariant_properties()
        properties_check()
        data_check(*data_check_args)
        self._refresh_tracking_data()
