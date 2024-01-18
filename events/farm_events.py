

class EnterFarmEvent:
    def __init__(self,
                 farming_token: str, farming_nonce: int, farming_amount,
                 farm_token: str, farm_nonce: int, farm_amount):
        self.farming_tk = farming_token
        self.farming_tk_nonce = farming_nonce
        self.farming_tk_amount = farming_amount
        self.farm_tk = farm_token
        self.farm_tk_nonce = farm_nonce
        self.farm_tk_amount = farm_amount


class ExitFarmEvent:
    def __init__(self, farm_token: str, amount: int, nonce: int, attributes: str, exit_amount: int = 0):
        self.farm_token = farm_token
        self.amount = amount
        self.nonce = nonce
        self.attributes = attributes    # hex
        self.exit_amount = exit_amount


class ClaimRewardsFarmEvent:
    def __init__(self, amount: int, nonce: int, attributes: str, user: str = None):
        self.amount = amount
        self.nonce = nonce
        self.attributes = attributes
        self.user = user

class CompoundRewardsFarmEvent:
    def __init__(self, amount: int, nonce: int):
        self.amount = amount
        self.nonce = nonce


class MigratePositionFarmEvent:
    def __init__(self, amount: int, nonce: int):
        self.amount = amount
        self.nonce = nonce


class SetTokenBalanceEvent:
    def __init__(self, token: str, balance: int, nonce: int):
        self.token = token
        self.balance = balance
        self.nonce = nonce
