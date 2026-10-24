CREATE TABLE IF NOT EXISTS legal_extraction_cascade (
    jurisdiction text NOT NULL CHECK (jurisdiction IN ('EU','FR')),
    source_id text NOT NULL,
    source_checksum text NOT NULL,
    policy_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED','CREDIT_EXHAUSTED')),
    attempts integer NOT NULL DEFAULT 0,
    claimed_at timestamptz,
    completed_at timestamptz,
    local_run_id uuid,
    deepseek_run_id uuid,
    gemini_run_id uuid,
    agreement text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_error text,
    PRIMARY KEY (jurisdiction,source_id,source_checksum,policy_version)
);
CREATE INDEX IF NOT EXISTS legal_extraction_cascade_status_idx ON legal_extraction_cascade(status);
