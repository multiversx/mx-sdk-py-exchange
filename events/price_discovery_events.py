
class DepositPDLiquidityEvent:
    def __init__(self,
                 deposit_token: str,
                 deposit_token_amount: int
                 ):
        self.deposit_token = deposit_token
        self.amount = deposit_token_amount


class WithdrawPDLiquidityEvent:
    def __init__(self,
                 deposit_lp_token: str,
                 deposit_lp_token_nonce: int,
                 deposit_lp_token_amount: int
                 ):
        self.deposit_lp_token = deposit_lp_token
        self.nonce = deposit_lp_token_nonce
        self.amount = deposit_lp_token_amount


class RedeemPDLPTokensEvent:
    def __init__(self,
                 deposit_lp_token: str,
                 deposit_lp_token_nonce: int,
                 deposit_lp_token_amount: int
                 ):
        self.deposit_lp_token = deposit_lp_token
        self.nonce = deposit_lp_token_nonce
        self.amount = deposit_lp_token_amount
