-- R7.4.3: candidate pairing only; not a finding of gold-plating.
CREATE TABLE IF NOT EXISTS legal_obligation_pair (
 pair_id uuid PRIMARY KEY,
 eu_obligation_id uuid NOT NULL REFERENCES legal_obligation(obligation_id),
 fr_obligation_id uuid NOT NULL REFERENCES legal_obligation(obligation_id),
 eu_celex text NOT NULL,
 scope_origin text NOT NULL CHECK (scope_origin IN ('MANUAL_VERIFIED','NIM_RESOLVED')),
 scope_reference text NOT NULL,
 algorithm_version text NOT NULL,
 similarity numeric(5,4) NOT NULL CHECK (similarity BETWEEN 0 AND 1),
 decision text NOT NULL CHECK (decision IN ('CANDIDATE','REVIEW_REQUIRED')),
 features jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (eu_obligation_id,fr_obligation_id,algorithm_version,scope_origin,scope_reference),
 CHECK (eu_obligation_id <> fr_obligation_id)
);
CREATE INDEX IF NOT EXISTS legal_obligation_pair_eu_idx ON legal_obligation_pair(eu_obligation_id);
CREATE INDEX IF NOT EXISTS legal_obligation_pair_fr_idx ON legal_obligation_pair(fr_obligation_id);
COMMENT ON TABLE legal_obligation_pair IS 'Candidate EU-FR obligation correspondences; neither legal equivalence nor surtransposition findings.';
