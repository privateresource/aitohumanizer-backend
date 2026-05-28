CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) DEFAULT 'string'
        CHECK (value_type IN ('string','integer','boolean','float','json')),
    description TEXT,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO system_config (key, value, value_type, description) VALUES
    -- Word limits
    ('anon_free_words', '200', 'integer', 'Words for one-time no-signup demo'),
    ('anon_session_limit_req', '1', 'integer', 'Max requests anonymous session'),
    ('free_plan_words_month', '500', 'integer', 'Free plan monthly word grant'),
    ('signup_grant_words', '500', 'integer', 'Words given at signup (free tier)'),
    -- Rate limits
    ('rate_limit_anon_per_hour', '3', 'integer', 'Anonymous requests per IP/hour'),
    ('rate_limit_user_per_min', '10', 'integer', 'Authenticated requests per min'),
    -- LLM
    ('fallback_enabled', 'true', 'boolean', 'Enable LLM fallback globally'),
    ('log_requests', 'true', 'boolean', 'Log humanize requests to DB'),
    ('log_responses', 'false', 'boolean', 'Log LLM response text (off in prod)'),
    -- Billing
    ('paddle_environment', 'sandbox', 'string', 'sandbox | production'),
    -- Security
    ('block_prompt_injection', 'true', 'boolean', 'Strip prompt injection patterns'),
    ('maintenance_mode', 'false', 'boolean', 'Enable maintenance mode'),
    -- Skill
    ('skill_file_path', 'BackEnd/SKILL.md', 'string', 'Path to SKILL.md (READ-ONLY)'),
    ('use_skill_as_system_prompt', 'true', 'boolean', 'Inject SKILL.md as system prompt'),
    -- Site
    ('social_proof_user_count', '12400', 'integer', 'User count shown on landing page'),
    ('launch_pricing_deadline', '', 'string', 'ISO date for urgency countdown (optional)')
ON CONFLICT (key) DO NOTHING;
