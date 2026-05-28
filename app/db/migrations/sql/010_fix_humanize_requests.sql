CREATE TABLE IF NOT EXISTS humanize_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    anonymous_session_id VARCHAR(255),
    input_text TEXT NOT NULL,
    output_text TEXT,
    mode VARCHAR(50) NOT NULL,
    word_count INTEGER NOT NULL,
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    status VARCHAR(50) DEFAULT 'completed' NOT NULL,
    is_anonymous BOOLEAN DEFAULT false NOT NULL,
    ai_model VARCHAR(100),
    feedback_score INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_humanize_user ON humanize_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_humanize_session ON humanize_requests(anonymous_session_id);
CREATE INDEX IF NOT EXISTS idx_humanize_created ON humanize_requests(created_at DESC);
