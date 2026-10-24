-- R7.4.3.2: completed processing is not necessarily a usable reference.
-- Preserve existing rows and statuses; do not retroactively relabel them.
ALTER TABLE legal_extraction_cascade
  DROP CONSTRAINT IF EXISTS legal_extraction_cascade_status_check;
ALTER TABLE legal_extraction_cascade
  ADD CONSTRAINT legal_extraction_cascade_status_check
  CHECK (status IN ('RUNNING','COMPLETED','NEEDS_REVIEW','FAILED','CREDIT_EXHAUSTED'));
