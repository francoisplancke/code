CREATE TABLE legal_obligation_evidence_check (
    obligation_id uuid PRIMARY KEY
        REFERENCES legal_obligation(obligation_id)
        ON DELETE CASCADE,

    status text NOT NULL
        CHECK (status IN (
            'VERIFIED',
            'INVALID',
            'SOURCE_MISSING',
            'ERROR'
        )),

    source_checksum text,
    obligation_fingerprint text NOT NULL,
    validator_version text NOT NULL,

    issues jsonb NOT NULL DEFAULT '[]'::jsonb,
    checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX legal_obligation_evidence_check_status_idx
    ON legal_obligation_evidence_check(status);