ALTER TABLE search_requests
    ADD COLUMN IF NOT EXISTS template_group TEXT NULL;
ALTER TABLE search_requests
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_search_requests_unprocessed
    ON search_requests (created_at ASC)
    WHERE processed_at IS NULL;
