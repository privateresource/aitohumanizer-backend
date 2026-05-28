CREATE TABLE IF NOT EXISTS humanize_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id VARCHAR(255),
    input_text TEXT,
    output_text TEXT,
    input_word_count INTEGER,
    output_word_count INTEGER,
    words_charged INTEGER,
    humanize_mode VARCHAR(30) DEFAULT 'standard',
    provider_id UUID,
    provider_name VARCHAR(100),
    model_name VARCHAR(150),
    fallback_triggered BOOLEAN DEFAULT false,
    status VARCHAR(20)
        CHECK (status IN ('success','failed','rate_limited','quota_exceeded')),
    error_message TEXT,
    duration_ms INTEGER,
    is_anonymous BOOLEAN DEFAULT false,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_humanize_user ON humanize_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_humanize_session ON humanize_requests(session_id);
CREATE INDEX IF NOT EXISTS idx_humanize_created ON humanize_requests(created_at DESC);
