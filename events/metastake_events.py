class EnterMetastakeEvent:
    def __init__(self, metastaking_token: str, metastaking_nonce: int, metastaking_amount: int,
                 metastake_token: str, metastake_nonce: int, metastake_amount: int,
                 original_caller: str = ""):
        self.metastaking_tk = metastaking_token
        self.metastaking_tk_nonce = metastaking_nonce
        self.metastaking_tk_amount = metastaking_amount
        self.metastake_tk = metastake_token
        self.metastake_tk_nonce = metastake_nonce
        self.metastake_tk_amount = metastake_amount
        self.original_caller = original_caller


class ExitMetastakeEvent:
    def __init__(self, metastake_tk: str, amount: int, nonce: int, attributes, whole_metastake_amount: int,
                 farm_tk_details: dict, original_caller: str = ""):
        self.metastake_token = metastake_tk
        self.amount = amount
        self.nonce = nonce
        self.metastake_token_attributes = attributes
        self.whole_metastake_token_amount = whole_metastake_amount
        self.farm_token_details = farm_tk_details
        self.original_caller = original_caller


class ClaimRewardsMetastakeEvent:
    def __init__(self, amount: int, nonce: int, farm_tk_details: dict, original_caller: str = ""):
        self.amount = amount
        self.nonce = nonce
        self.farm_token_details = farm_tk_details
        self.original_caller = original_caller


class MergeMetastakeWithStakeEvent:
    def __init__(self, metastake_tk: str, metastake_tk_nonce: int, metastake_tk_amount: int,
                 stake_tk: str, stake_tk_nonce: int, stake_tk_amount: int):
        self.metastake_tk = metastake_tk
        self.metastake_tk_nonce = metastake_tk_nonce
        self.metastake_tk_amount = metastake_tk_amount
        self.stake_tk = stake_tk
        self.stake_tk_nonce = stake_tk_nonce
        self.stake_tk_amount = stake_tk_amount
