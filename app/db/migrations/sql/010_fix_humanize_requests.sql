CREATE TABLE IF NOT EXISTS humanize_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    anonymous_session_id VARCHAR(255),
    input_text TEXT NOT NULL,
    output_text TEXT,
    mode VARCHAR(50) NOT NULL DEFAULT 'standard',
    word_count INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    status VARCHAR(50) DEFAULT 'completed' NOT NULL,
    is_anonymous BOOLEAN DEFAULT false NOT NULL,
    ai_model VARCHAR(100),
    feedback_score INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS anonymous_session_id VARCHAR(255);
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS mode VARCHAR(50) NOT NULL DEFAULT 'standard';
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS word_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS tokens_used INTEGER;
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS processing_time_ms INTEGER;
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS ai_model VARCHAR(100);
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS feedback_score INTEGER;
ALTER TABLE humanize_requests
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE humanize_requests
SET anonymous_session_id = session_id
WHERE anonymous_session_id IS NULL AND session_id IS NOT NULL;

UPDATE humanize_requests
SET mode = humanize_mode
WHERE mode = 'standard' AND humanize_mode IS NOT NULL;

UPDATE humanize_requests
SET word_count = input_word_count
WHERE word_count = 0 AND input_word_count IS NOT NULL;

UPDATE humanize_requests
SET ai_model = model_name
WHERE ai_model IS NULL AND model_name IS NOT NULL;

UPDATE humanize_requests
SET processing_time_ms = duration_ms
WHERE processing_time_ms IS NULL AND duration_ms IS NOT NULL;

UPDATE humanize_requests
SET updated_at = created_at
WHERE updated_at IS NULL;

ALTER TABLE humanize_requests
    DROP CONSTRAINT IF EXISTS humanize_requests_status_check;
ALTER TABLE humanize_requests
    ADD CONSTRAINT humanize_requests_status_check CHECK (status IN ('success', 'failed', 'rate_limited', 'quota_exceeded', 'completed'));

CREATE INDEX IF NOT EXISTS idx_humanize_user ON humanize_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_humanize_session ON humanize_requests(anonymous_session_id);
CREATE INDEX IF NOT EXISTS idx_humanize_created ON humanize_requests(created_at DESC);
