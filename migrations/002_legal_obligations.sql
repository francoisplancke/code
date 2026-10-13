-- R7.4.1: derived, auditable legal obligations. Run after LEGI and EU imports.
-- PostgreSQL source texts remain authoritative; no cascade delete from source documents.
CREATE TABLE IF NOT EXISTS legal_obligation_run (
    run_id uuid PRIMARY KEY,
    pipeline_version text NOT NULL,
    extractor_kind text NOT NULL CHECK (extractor_kind IN ('DETERMINISTIC','LLM','HYBRID','HUMAN')),
    provider text,
    model text,
    prompt_version text,
    parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS legal_obligation (
    obligation_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES legal_obligation_run(run_id),
    jurisdiction text NOT NULL CHECK (jurisdiction IN ('FR','EU')),
    -- FR references the immutable LEGI version; EU references the parsed provision.
    legi_version_id uuid REFERENCES version(id) ON DELETE RESTRICT,
    eu_provision_id text REFERENCES eu_provision(provision_id) ON DELETE RESTRICT,
    source_checksum text NOT NULL CHECK (length(source_checksum) > 0),
    source_excerpt text NOT NULL CHECK (length(btrim(source_excerpt)) > 0),
    -- Offsets are optional, but must be supplied together; zero-based, end exclusive.
    span_start integer,
    span_end integer,
    actor text,
    modality text NOT NULL CHECK (modality IN ('OBLIGATION','PROHIBITION','PERMISSION','EXEMPTION')),
    action text NOT NULL CHECK (length(btrim(action)) > 0),
    object text,
    conditions jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(conditions) = 'array'),
    exceptions jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(exceptions) = 'array'),
    deadline text,
    frequency text,
    threshold text,
    territorial_scope text,
    temporal_scope text,
    confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    review_status text NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN ('UNREVIEWED','ACCEPTED','REJECTED','NEEDS_REVIEW')),
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence) = 'array'),
    raw_output jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((jurisdiction = 'FR' AND legi_version_id IS NOT NULL AND eu_provision_id IS NULL)
        OR (jurisdiction = 'EU' AND eu_provision_id IS NOT NULL AND legi_version_id IS NULL)),
    CHECK ((span_start IS NULL AND span_end IS NULL)
        OR (span_start >= 0 AND span_end > span_start))
);
CREATE INDEX IF NOT EXISTS legal_obligation_run_idx ON legal_obligation(run_id);
CREATE INDEX IF NOT EXISTS legal_obligation_fr_source_idx ON legal_obligation(legi_version_id) WHERE jurisdiction = 'FR';
CREATE INDEX IF NOT EXISTS legal_obligation_eu_source_idx ON legal_obligation(eu_provision_id) WHERE jurisdiction = 'EU';
CREATE INDEX IF NOT EXISTS legal_obligation_review_idx ON legal_obligation(review_status);
CREATE INDEX IF NOT EXISTS legal_obligation_modality_idx ON legal_obligation(modality);
COMMENT ON TABLE legal_obligation IS 'R7.4.1 derived hypotheses, not authoritative legal facts; human review required.';
COMMENT ON COLUMN legal_obligation.source_checksum IS 'Hash of source text used by the extractor; allows detection of stale derived obligations.';
