CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    tagline VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    is_featured BOOLEAN DEFAULT false,
    is_free_tier BOOLEAN DEFAULT false,
    words_per_month BIGINT NOT NULL,
    words_per_request INTEGER NOT NULL,
    humanize_modes JSONB DEFAULT '["standard"]',
    has_bypass_preview BOOLEAN DEFAULT false,
    has_priority_queue BOOLEAN DEFAULT false,
    has_api_access BOOLEAN DEFAULT false,
    api_daily_limit INTEGER DEFAULT 0,
    has_ai_detector BOOLEAN DEFAULT false,
    has_dedicated_support BOOLEAN DEFAULT false,
    team_seats INTEGER DEFAULT 1,
    monthly_price_usd NUMERIC(10,2),
    annual_price_usd NUMERIC(10,2),
    original_price_usd NUMERIC(10,2),
    paddle_monthly_price_id VARCHAR(100),
    paddle_annual_price_id VARCHAR(100),
    features_list JSONB DEFAULT '[]',
    display_order INTEGER DEFAULT 99,
    badge_text VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO plans (name, slug, tagline, description, is_free_tier,
    words_per_month, words_per_request, humanize_modes,
    monthly_price_usd, annual_price_usd, original_price_usd,
    has_bypass_preview, has_priority_queue, has_api_access, has_ai_detector,
    team_seats, is_featured, display_order, badge_text, features_list)
VALUES
(
    'Free', 'free', 'Always free — no card needed',
    'Get started at no cost forever', true,
    500, 200, '["standard"]',
    0.00, 0.00, NULL,
    false, false, false, false, 1, false, 0, NULL,
    '["500 words/month","200 words per request","Standard humanizer","Web app"]'
),
(
    'Starter', 'starter', 'Less than a coffee. Literally.',
    'Try before you scale', false,
    15000, 1500, '["standard"]',
    4.00, 40.00, NULL,
    false, false, false, false, 1, false, 1, NULL,
    '["15,000 words/month","1,500 words per request","DeepSeek V4-Flash engine","Standard mode","Web app access","Email support"]'
),
(
    'Creator', 'creator', 'Most popular for a reason.',
    'For bloggers, freelancers & marketers', false,
    75000, 3000, '["standard","academic","casual"]',
    9.00, 90.00, 14.00,
    true, true, false, false, 1, true, 2, 'Most Popular',
    '["75,000 words/month","3,000 words per request","V4-Flash + V3 Pro quality","3 humanize modes","Bypass score preview","Priority queue","Priority email support"]'
),
(
    'Pro', 'pro', 'For serious creators.',
    'For agencies, SEO writers & content teams', false,
    250000, 3000, '["standard","academic","casual","turbo"]',
    19.00, 190.00, NULL,
    true, true, true, true, 1, false, 3, 'Best for Teams',
    '["250,000 words/month","3,000 words per request","All modes + Turbo (V3)","Built-in AI detector check","API access (1,000 req/day)","Priority support"]'
),
(
    'Unlimited', 'unlimited', 'Cheapest unlimited on the market.',
    'For agencies & power users', false,
    -1, 3000, '["standard","academic","casual","turbo"]',
    29.00, 290.00, NULL,
    true, true, true, true, 2, false, 4, 'Best Value',
    '["Unlimited words/month*","3,000 words per request","Everything in Pro","Full API access (unlimited)","2 team seats","Dedicated support","*Fair-use 5M words/mo soft cap"]'
)
ON CONFLICT (slug) DO NOTHING;
