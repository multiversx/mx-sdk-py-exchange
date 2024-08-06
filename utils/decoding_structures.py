

LOCK_OPTIONS = {
    'lock_epochs': 'u64',
    'penalty_start_percentage': 'u64'
}

ENERGY_ENTRY = {
    'amount': 'bigint',
    'last_update_epoch': 'u64',
    'total_locked_tokens': 'biguint',
}

USER_CLAIM_PROGRESS = {
    'energy': ENERGY_ENTRY,
    'week': 'u32'
}

ESDT_TOKEN_PAYMENT = {
    'token_identifier': 'string',
    'token_nonce': 'u64',
    'token_amount': 'biguint'
}

LIQUID_LOCKING_UNLOCKED_TOKEN = {
    'token_identifier': 'string',
    'token_nonce': 'u64',
    'unbond_epoch': 'biguint',
    'unbond_epoch': 'u64',
}

LIQUID_LOCKING_LOCKED_TOKEN_AMOUNTS = {
    'locked_tokens': ESDT_TOKEN_PAYMENT
}

LIQUID_LOCKING_UNLOCKED_TOKEN_AMOUNTS = {
    'unlocked_tokens': LIQUID_LOCKING_UNLOCKED_TOKEN
}

USER_FARM_POSITION = {
    'total_farm_position': 'biguint',
    'allow_external_claim': 'u8'
}

FARM_TOKEN_ATTRIBUTES = {
    'reward_per_share': 'biguint',
    'entering_epoch': 'u64',
    'compounded_reward': 'biguint',
    'current_farm_amount': 'biguint',
    'original_owner': 'address',
}

STAKE_V1_TOKEN_ATTRIBUTES = {
    'reward_per_share': 'biguint',
    'compounded_reward': 'biguint',
    'current_farm_amount': 'biguint'
}

STAKE_V2_TOKEN_ATTRIBUTES = {
    'reward_per_share': 'biguint',
    'compounded_reward': 'biguint',
    'current_farm_amount': 'biguint',
    'original_owner': 'address'
}

STAKE_UNBOND_TOKEN_ATTRIBUTES = {
    'unlock_epoch': 'u64'
}

METASTAKE_TOKEN_ATTRIBUTES = {
    'lp_farm_token_nonce': 'u64',
    'lp_farm_token_amount': 'biguint',
    'staking_farm_token_nonce': 'u64',
    'staking_farm_token_amount': 'biguint'
}

LKMEX_ATTRIBUTES = {
    'unlock_schedule_list': {
        'unlock_epoch': 'u64',
        'unlock_percent': 'u64'
    },
    'merged': 'u8'
}

XMEX_ATTRIBUTES = {
    'original_token_id': 'string',
    'original_token_nonce': 'u64',
    'unlock_epoch': 'u64',
}

XMEXLP_ATTRIBUTES = {
    'lp_token_id': 'string',
    'lp_token_amount': 'biguint',
    'locked_tokens_id': 'string',
    'locked_tokens_nonce': 'u64',
    'locked_tokens_amount': 'biguint'
}

XMEXFARM_ATTRIBUTES = {
    'farm_token_id': 'string',
    'farm_token_nonce': 'u64',
    'farm_token_amount': 'biguint',
    'proxy_token_id': 'string',
    'proxy_token_nonce': 'u64',
    'proxy_token_amount': 'biguint'
}

TOTAL_REWARDS_FOR_WEEK = {
    'rewards_for_week_list': {
        'token_id': 'string',
        'nonce': 'u64',
        'amount': 'biguint'
    }
}

