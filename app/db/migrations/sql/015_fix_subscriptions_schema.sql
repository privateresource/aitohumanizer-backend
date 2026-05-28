ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS billing_interval VARCHAR(20) NOT NULL DEFAULT 'monthly';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS paddle_next_billed_at TIMESTAMPTZ;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS scheduled_change TEXT;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
ALTER TABLE subscriptions DROP COLUMN IF EXISTS billing_cycle;
ALTER TABLE subscriptions DROP COLUMN IF EXISTS cancel_at_period_end;
ALTER TABLE subscriptions DROP COLUMN IF EXISTS canceled_at;
