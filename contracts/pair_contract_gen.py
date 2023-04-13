from multiversx_sdk_core import Address

from utils.contract_interactor import ContractInteractor
from utils.decode import d


class PairContractInteractor(ContractInteractor):
	def getTokensForGivenPosition(self, liquidity: int):
		return self._query("getTokensForGivenPosition", [liquidity], [EsdtTokenPayment_decoder, EsdtTokenPayment_decoder])

	def getReservesAndTotalSupply(self):
		return self._query("getReservesAndTotalSupply", [], [d.U(), d.U(), d.U()])

	def getAmountOut(self, token_in: str, amount_in: int):
		return self._query("getAmountOut", [token_in, amount_in], [d.U()])

	def getAmountIn(self, token_wanted: str, amount_wanted: int):
		return self._query("getAmountIn", [token_wanted, amount_wanted], [d.U()])

	def getEquivalent(self, token_in: str, amount_in: int):
		return self._query("getEquivalent", [token_in, amount_in], [d.U()])

	def getFeeState(self):
		return self._query("getFeeState", [], [d.Bool()])

	def getFeeDestinations(self):
		return self._query("getFeeDestinations", [], [d.Tuple([d.Addr(), d.Str()])])

	def getTrustedSwapPairs(self):
		return self._query("getTrustedSwapPairs", [], [d.Tuple([TokenPair_decoder, d.Addr()])])

	def getWhitelistedManagedAddresses(self):
		return self._query("getWhitelistedManagedAddresses", [], [d.Addr()])

	def getFeesCollectorAddress(self):
		return self._query("getFeesCollectorAddress", [], [d.Addr()])

	def getFeesCollectorCutPercentage(self):
		return self._query("getFeesCollectorCutPercentage", [], [d.U64()])

	def getLpTokenIdentifier(self):
		return self._query("getLpTokenIdentifier", [], [d.Str()])

	def getTotalFeePercent(self):
		return self._query("getTotalFeePercent", [], [d.U64()])

	def getSpecialFee(self):
		return self._query("getSpecialFee", [], [d.U64()])

	def getRouterManagedAddress(self):
		return self._query("getRouterManagedAddress", [], [d.Addr()])

	def getFirstTokenId(self):
		return self._query("getFirstTokenId", [], [d.Str()])

	def getSecondTokenId(self):
		return self._query("getSecondTokenId", [], [d.Str()])

	def getTotalSupply(self):
		return self._query("getTotalSupply", [], [d.U()])

	def getInitialLiquidtyAdder(self):
		return self._query("getInitialLiquidtyAdder", [], [d.Option(d.Addr())])

	def getReserve(self, token_id: str):
		return self._query("getReserve", [token_id], [d.U()])

	def getLockingScAddress(self):
		return self._query("getLockingScAddress", [], [d.Addr()])

	def getUnlockEpoch(self):
		return self._query("getUnlockEpoch", [], [d.U64()])

	def getLockingDeadlineEpoch(self):
		return self._query("getLockingDeadlineEpoch", [], [d.U64()])

	def getPermissions(self, address: Address):
		return self._query("getPermissions", [address], [d.U32()])

	def getState(self):
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

