CREATE TABLE IF NOT EXISTS coupons (
    id                  SERIAL PRIMARY KEY,
    code                VARCHAR(50) UNIQUE NOT NULL,
    description         VARCHAR(200),
    discount_type       VARCHAR(20) NOT NULL DEFAULT 'percentage',
    discount_value      DECIMAL(10,2) NOT NULL,
    applies_to          VARCHAR(20) DEFAULT 'all',
    applies_to_billing  VARCHAR(20) DEFAULT 'both',
    max_uses            INT,
    uses_count          INT DEFAULT 0,
    max_uses_per_user   INT DEFAULT 1,
    min_plan_price      DECIMAL(10,2),
    is_active           BOOLEAN DEFAULT true,
    starts_at           TIMESTAMP DEFAULT NOW(),
    expires_at          TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS coupon_plan_limits (
    id          SERIAL PRIMARY KEY,
    coupon_id   INT REFERENCES coupons(id) ON DELETE CASCADE,
    plan_slug   VARCHAR(50) NOT NULL,
    UNIQUE(coupon_id, plan_slug)
);

CREATE TABLE IF NOT EXISTS coupon_usage (
    id              SERIAL PRIMARY KEY,
    coupon_id       INT REFERENCES coupons(id) ON DELETE CASCADE,
    user_id         VARCHAR(100) NOT NULL,
    plan_slug       VARCHAR(50) NOT NULL,
    billing         VARCHAR(20) NOT NULL,
    discount_applied DECIMAL(10,2) NOT NULL,
    used_at         TIMESTAMP DEFAULT NOW()
);

ALTER TABLE pricing_plans ADD COLUMN IF NOT EXISTS discount_percentage DECIMAL(5,2) DEFAULT 0;
ALTER TABLE pricing_plans ADD COLUMN IF NOT EXISTS show_original_price BOOLEAN DEFAULT false;
ALTER TABLE pricing_plans ADD COLUMN IF NOT EXISTS discount_label VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_coupons_code ON coupons(code);
CREATE INDEX IF NOT EXISTS idx_coupons_active ON coupons(is_active);
CREATE INDEX IF NOT EXISTS idx_coupon_usage_user ON coupon_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_coupon_usage_coupon ON coupon_usage(coupon_id);

INSERT INTO coupons (code, description, discount_type, discount_value, applies_to, max_uses, is_active)
VALUES ('WELCOME20', '20% off for new users', 'percentage', 20, 'all', NULL, true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO coupons (code, description, discount_type, discount_value, applies_to, applies_to_billing, max_uses, is_active)
VALUES ('CREATOR5', '$5 off Creator monthly', 'fixed', 5, 'specific', 'monthly', 500, true)
ON CONFLICT (code) DO NOTHING;

INSERT INTO coupon_plan_limits (coupon_id, plan_slug)
SELECT id, 'creator' FROM coupons WHERE code = 'CREATOR5'
ON CONFLICT (coupon_id, plan_slug) DO NOTHING;

INSERT INTO coupons (code, description, discount_type, discount_value, applies_to, applies_to_billing, expires_at, is_active)
VALUES ('YEARLY50', '50% off any yearly plan', 'percentage', 50, 'all', 'yearly', NOW() + INTERVAL '30 days', true)
ON CONFLICT (code) DO NOTHING;
