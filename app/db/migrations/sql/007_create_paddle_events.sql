CREATE TABLE IF NOT EXISTS paddle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paddle_event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    processed BOOLEAN DEFAULT false,
    processed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
