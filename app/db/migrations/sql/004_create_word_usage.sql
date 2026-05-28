CREATE TABLE IF NOT EXISTS word_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    words_delta INTEGER NOT NULL,
    words_balance_after BIGINT NOT NULL,
    event_type VARCHAR(50) NOT NULL
        CHECK (event_type IN (
            'monthly_grant',
            'signup_grant',
            'humanize_use',
            'admin_adjustment',
            'refund',
            'plan_upgrade_carry',
            'expiry'
        )),
    reference_id UUID,
    description TEXT,
    billing_period VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_word_usage_user ON word_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_word_usage_period ON word_usage(user_id, billing_period);
CREATE INDEX IF NOT EXISTS idx_word_usage_created ON word_usage(created_at DESC);

CREATE OR REPLACE VIEW user_word_balance AS
SELECT
    user_id,
    SUM(words_delta) AS words_available,
    MAX(created_at) AS last_updated
FROM word_usage
GROUP BY user_id;
