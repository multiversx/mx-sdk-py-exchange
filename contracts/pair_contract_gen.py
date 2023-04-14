from multiversx_sdk_core import Address

from utils.contract_interactor import ContractInteractor, Payment
from utils.decode import d


class PairContractInteractor(ContractInteractor):
	def call_addInitialLiquidity(self, _payment: Payment):
		return self._call("addInitialLiquidity", [], 0, _payment)

	def call_addLiquidity(self, first_token_amount_min: int, second_token_amount_min: int, _payment: Payment):
		return self._call("addLiquidity", [first_token_amount_min, second_token_amount_min], 0, _payment)

	def call_removeLiquidity(self, first_token_amount_min: int, second_token_amount_min: int, _payment: Payment):
		return self._call("removeLiquidity", [first_token_amount_min, second_token_amount_min], 0, _payment)

	def call_removeLiquidityAndBuyBackAndBurnToken(self, token_to_buyback_and_burn: str, _payment: Payment):
		return self._call("removeLiquidityAndBuyBackAndBurnToken", [token_to_buyback_and_burn], 0, _payment)

	def call_swapNoFeeAndForward(self, token_out: str, destination_address: Address, _payment: Payment):
		return self._call("swapNoFeeAndForward", [token_out, destination_address], 0, _payment)

	def call_swapTokensFixedInput(self, token_out: str, amount_out_min: int, _payment: Payment):
		return self._call("swapTokensFixedInput", [token_out, amount_out_min], 0, _payment)

	def call_swapTokensFixedOutput(self, token_out: str, amount_out: int, _payment: Payment):
		return self._call("swapTokensFixedOutput", [token_out, amount_out], 0, _payment)

	def call_setLpTokenIdentifier(self, token_identifier: str):
		return self._call("setLpTokenIdentifier", [token_identifier], 0)

	def query_getTokensForGivenPosition(self, liquidity: int):
		return self._query("getTokensForGivenPosition", [liquidity], [EsdtTokenPayment_decoder, EsdtTokenPayment_decoder])

	def query_getReservesAndTotalSupply(self):
		return self._query("getReservesAndTotalSupply", [], [d.U(), d.U(), d.U()])

	def query_getAmountOut(self, token_in: str, amount_in: int):
		return self._query("getAmountOut", [token_in, amount_in], [d.U()])

	def query_getAmountIn(self, token_wanted: str, amount_wanted: int):
		return self._query("getAmountIn", [token_wanted, amount_wanted], [d.U()])

	def query_getEquivalent(self, token_in: str, amount_in: int):
		return self._query("getEquivalent", [token_in, amount_in], [d.U()])

	def query_getFeeState(self):
		return self._query("getFeeState", [], [d.Bool()])

	def call_whitelist(self, address: Address):
		return self._call("whitelist", [address], 0)

	def call_removeWhitelist(self, address: Address):
		return self._call("removeWhitelist", [address], 0)

	def call_addTrustedSwapPair(self, pair_address: Address, first_token: str, second_token: str):
		return self._call("addTrustedSwapPair", [pair_address, first_token, second_token], 0)

	def call_removeTrustedSwapPair(self, first_token: str, second_token: str):
		return self._call("removeTrustedSwapPair", [first_token, second_token], 0)

	def call_setupFeesCollector(self, fees_collector_address: Address, fees_collector_cut_percentage):
		return self._call("setupFeesCollector", [fees_collector_address, fees_collector_cut_percentage], 0)

	def call_setFeeOn(self, enabled, fee_to_address: Address, fee_token: str):
		return self._call("setFeeOn", [enabled, fee_to_address, fee_token], 0)

	def query_getFeeDestinations(self):
		return self._query("getFeeDestinations", [], [d.Tuple([d.Addr(), d.Str()])])

	def query_getTrustedSwapPairs(self):
		return self._query("getTrustedSwapPairs", [], [d.Tuple([TokenPair_decoder, d.Addr()])])

	def query_getWhitelistedManagedAddresses(self):
		return self._query("getWhitelistedManagedAddresses", [], [d.Addr()])

	def query_getFeesCollectorAddress(self):
		return self._query("getFeesCollectorAddress", [], [d.Addr()])

	def query_getFeesCollectorCutPercentage(self):
		return self._query("getFeesCollectorCutPercentage", [], [d.U64()])

	def call_setStateActiveNoSwaps(self):
		return self._call("setStateActiveNoSwaps", [], 0)

	def call_setFeePercents(self, total_fee_percent, special_fee_percent):
		return self._call("setFeePercents", [total_fee_percent, special_fee_percent], 0)

	def query_getLpTokenIdentifier(self):
		return self._query("getLpTokenIdentifier", [], [d.Str()])

	def query_getTotalFeePercent(self):
		return self._query("getTotalFeePercent", [], [d.U64()])

	def query_getSpecialFee(self):
		return self._query("getSpecialFee", [], [d.U64()])

	def query_getRouterManagedAddress(self):
		return self._query("getRouterManagedAddress", [], [d.Addr()])

	def query_getFirstTokenId(self):
		return self._query("getFirstTokenId", [], [d.Str()])

	def query_getSecondTokenId(self):
		return self._query("getSecondTokenId", [], [d.Str()])

	def query_getTotalSupply(self):
		return self._query("getTotalSupply", [], [d.U()])

	def query_getInitialLiquidtyAdder(self):
		return self._query("getInitialLiquidtyAdder", [], [d.Option(d.Addr())])

	def query_getReserve(self, token_id: str):
		return self._query("getReserve", [token_id], [d.U()])

	def call_updateAndGetTokensForGivenPositionWithSafePrice(self, liquidity: int):
		return self._call("updateAndGetTokensForGivenPositionWithSafePrice", [liquidity], 0)

	def call_updateAndGetSafePrice(self, input):
		return self._call("updateAndGetSafePrice", [input], 0)

	def call_setMaxObservationsPerRecord(self, max_observations_per_record):
		return self._call("setMaxObservationsPerRecord", [max_observations_per_record], 0)

	def call_setLockingDeadlineEpoch(self, new_deadline):
		return self._call("setLockingDeadlineEpoch", [new_deadline], 0)

	def call_setLockingScAddress(self, new_address: Address):
		return self._call("setLockingScAddress", [new_address], 0)

	def call_setUnlockEpoch(self, new_epoch):
		return self._call("setUnlockEpoch", [new_epoch], 0)

	def query_getLockingScAddress(self):
		return self._query("getLockingScAddress", [], [d.Addr()])

	def query_getUnlockEpoch(self):
		return self._query("getUnlockEpoch", [], [d.U64()])

	def query_getLockingDeadlineEpoch(self):
		return self._query("getLockingDeadlineEpoch", [], [d.U64()])

	def call_addAdmin(self, address: Address):
		return self._call("addAdmin", [address], 0)

	def call_removeAdmin(self, address: Address):
		return self._call("removeAdmin", [address], 0)

	def call_updateOwnerOrAdmin(self, previous_owner: Address):
		return self._call("updateOwnerOrAdmin", [previous_owner], 0)

	def query_getPermissions(self, address: Address):
		return self._query("getPermissions", [address], [d.U32()])

	def call_addToPauseWhitelist(self, address_list):
		return self._call("addToPauseWhitelist", [address_list], 0)

	def call_removeFromPauseWhitelist(self, address_list):
		return self._call("removeFromPauseWhitelist", [address_list], 0)

	def call_pause(self):
		return self._call("pause", [], 0)

	def call_resume(self):
		return self._call("resume", [], 0)

	def query_getState(self):
		return self._query("getState", [], [State_decoder])


AddLiquidityEvent_decoder = d.Tuple({
	"caller": d.Addr(),
	"first_token_id": d.Str(),
	"first_token_amount": d.U(),
	"second_token_id": d.Str(),
	"second_token_amount": d.U(),
	"lp_token_id": d.Str(),
	"lp_token_amount": d.U(),
	"lp_supply": d.U(),
	"first_token_reserves": d.U(),
	"second_token_reserves": d.U(),
	"block": d.U64(),
	"epoch": d.U64(),
	"timestamp": d.U64(),
})

EsdtTokenPayment_decoder = d.Tuple({
	"token_identifier": d.Str(),
	"token_nonce": d.U64(),
	"amount": d.U(),
})

RemoveLiquidityEvent_decoder = d.Tuple({
	"caller": d.Addr(),
	"first_token_id": d.Str(),
	"first_token_amount": d.U(),
	"second_token_id": d.Str(),
	"second_token_amount": d.U(),
	"lp_token_id": d.Str(),
	"lp_token_amount": d.U(),
	"lp_supply": d.U(),
	"first_token_reserves": d.U(),
	"second_token_reserves": d.U(),
	"block": d.U64(),
	"epoch": d.U64(),
	"timestamp": d.U64(),
})

State_decoder = d.U8()

SwapEvent_decoder = d.Tuple({
	"caller": d.Addr(),
	"token_id_in": d.Str(),
	"token_amount_in": d.U(),
	"token_id_out": d.Str(),
	"token_amount_out": d.U(),
	"fee_amount": d.U(),
	"token_in_reserve": d.U(),
	"token_out_reserve": d.U(),
	"block": d.U64(),
	"epoch": d.U64(),
	"timestamp": d.U64(),
})

SwapNoFeeAndForwardEvent_decoder = d.Tuple({
	"caller": d.Addr(),
	"token_id_in": d.Str(),
	"token_amount_in": d.U(),
	"token_id_out": d.Str(),
	"token_amount_out": d.U(),
	"destination": d.Addr(),
	"block": d.U64(),
	"epoch": d.U64(),
	"timestamp": d.U64(),
})

TokenPair_decoder = d.Tuple({
	"first_token": d.Str(),
	"second_token": d.Str(),
})

