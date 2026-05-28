CREATE TABLE IF NOT EXISTS pricing_plans (
    id SERIAL PRIMARY KEY,
    legacy_plan_id UUID REFERENCES plans(id) ON DELETE SET NULL,
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    tagline VARCHAR(255),
    monthly_price_usd NUMERIC(10,2) DEFAULT 0.00,
    annual_price_usd NUMERIC(10,2) DEFAULT 0.00,
    original_price_usd NUMERIC(10,2),
    paddle_monthly_price_id VARCHAR(100),
    paddle_annual_price_id VARCHAR(100),
    badge_text VARCHAR(50),
    display_order INTEGER DEFAULT 99,
    is_active BOOLEAN DEFAULT true,
    is_featured BOOLEAN DEFAULT false,
    is_public BOOLEAN DEFAULT true,
    is_free BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS plan_tool_limits (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES pricing_plans(id) ON DELETE CASCADE,
    tool VARCHAR(50) NOT NULL,
    max_requests_per_month INTEGER DEFAULT -1,
    max_requests_per_day INTEGER DEFAULT -1,
    max_words_per_request INTEGER DEFAULT 3000,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(plan_id, tool)
);

CREATE TABLE IF NOT EXISTS plan_features (
    id SERIAL PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES pricing_plans(id) ON DELETE CASCADE,
    feature_key VARCHAR(100) NOT NULL,
    feature_value VARCHAR(255) DEFAULT 'true',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(plan_id, feature_key)
);

CREATE TABLE IF NOT EXISTS user_usage (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool VARCHAR(50) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    requests_used INTEGER DEFAULT 0,
    words_used INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, tool, period_start)
);

CREATE INDEX IF NOT EXISTS idx_user_usage_user_period ON user_usage(user_id, tool, period_start);

INSERT INTO pricing_plans (name, slug, tagline, description, monthly_price_usd, annual_price_usd, original_price_usd, badge_text, display_order, is_active, is_public, is_free, is_featured)
VALUES
    ('Guest', 'guest', 'Try before you sign up', 'Anonymous preview — 1 request per session', 0.00, 0.00, NULL, NULL, 0, true, false, true, false),
    ('Free', 'free', 'Always free — no card needed', 'Get started at no cost forever', 0.00, 0.00, NULL, NULL, 1, true, false, true, false),
    ('Starter', 'starter', 'Less than a coffee. Literally.', 'Try before you scale', 4.00, 40.00, NULL, NULL, 2, true, true, false, false),
    ('Creator', 'creator', 'Most popular for a reason.', 'For bloggers, freelancers & marketers', 9.00, 90.00, 14.00, 'Most Popular', 3, true, true, false, true),
    ('Pro', 'pro', 'For serious creators.', 'For agencies, SEO writers & content teams', 19.00, 190.00, NULL, 'Best for Teams', 4, true, true, false, false),
    ('Unlimited', 'unlimited', 'Cheapest unlimited on the market.', 'For agencies & power users', 29.00, 290.00, NULL, 'Best Value', 5, true, true, false, false)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', 1, 1, 200, true FROM pricing_plans WHERE slug = 'guest'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', 2, 1, 200, true FROM pricing_plans WHERE slug = 'free'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', 15000, -1, 1500, true FROM pricing_plans WHERE slug = 'starter'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', -1, -1, 3000, true FROM pricing_plans WHERE slug = 'creator'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', -1, -1, 3000, true FROM pricing_plans WHERE slug = 'pro'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'humanize', -1, -1, 3000, true FROM pricing_plans WHERE slug = 'unlimited'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'paraphrase', -1, -1, 3000, true FROM pricing_plans WHERE slug IN ('starter', 'creator', 'pro', 'unlimited')
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'paraphrase', 1, 1, 200, true FROM pricing_plans WHERE slug = 'free'
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'grammar_check', -1, -1, 5000, true FROM pricing_plans WHERE slug IN ('free', 'starter', 'creator', 'pro', 'unlimited')
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_tool_limits (plan_id, tool, max_requests_per_month, max_requests_per_day, max_words_per_request, enabled)
SELECT id, 'ai_detector', -1, -1, 3000, true FROM pricing_plans WHERE slug IN ('pro', 'unlimited')
ON CONFLICT (plan_id, tool) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'words_per_month', '500', 1 FROM pricing_plans WHERE slug = 'free'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'words_per_month', '15000', 1 FROM pricing_plans WHERE slug = 'starter'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'words_per_month', '75000', 1 FROM pricing_plans WHERE slug = 'creator'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'words_per_month', '250000', 1 FROM pricing_plans WHERE slug = 'pro'
ON CONFLICT (plan_id, feature_key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key, feature_value, sort_order)
SELECT id, 'words_per_month', 'unlimited', 1 FROM pricing_plans WHERE slug = 'unlimited'
ON CONFLICT (plan_id, feature_key) DO NOTHING;
