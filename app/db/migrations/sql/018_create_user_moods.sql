CREATE TABLE IF NOT EXISTS user_moods (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    prompt VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_moods_user ON user_moods(user_id);

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '0', 99 FROM pricing_plans WHERE slug = 'free'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '0', 99 FROM pricing_plans WHERE slug = 'starter'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '10', 99 FROM pricing_plans WHERE slug = 'creator'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '25', 99 FROM pricing_plans WHERE slug = 'pro'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '50', 99 FROM pricing_plans WHERE slug = 'unlimited'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'max_custom_moods', '0', 99 FROM pricing_plans WHERE slug = 'guest'
ON CONFLICT (plan_id, feature_key) DO NOTHING;
