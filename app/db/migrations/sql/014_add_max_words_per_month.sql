ALTER TABLE pricing_plans ADD COLUMN IF NOT EXISTS max_words_per_month INTEGER DEFAULT -1;

UPDATE pricing_plans SET max_words_per_month = 500 WHERE slug = 'free' AND max_words_per_month = -1;
UPDATE pricing_plans SET max_words_per_month = 15000 WHERE slug = 'starter' AND max_words_per_month = -1;
UPDATE pricing_plans SET max_words_per_month = 75000 WHERE slug = 'creator' AND max_words_per_month = -1;
UPDATE pricing_plans SET max_words_per_month = 250000 WHERE slug = 'pro' AND max_words_per_month = -1;
UPDATE pricing_plans SET max_words_per_month = -1 WHERE slug = 'unlimited' AND max_words_per_month = -1;
UPDATE pricing_plans SET max_words_per_month = -1 WHERE slug = 'guest' AND max_words_per_month = -1;
