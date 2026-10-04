CREATE TABLE IF NOT EXISTS eu_act (
 celex text PRIMARY KEY, cellar_uuid text, eli text, act_type text, title text,
 document_date date, legal_status text, metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS eu_act_cellar_idx ON eu_act(cellar_uuid);
CREATE INDEX IF NOT EXISTS eu_act_type_idx ON eu_act(act_type);
CREATE INDEX IF NOT EXISTS eu_act_date_idx ON eu_act(document_date);
CREATE INDEX IF NOT EXISTS eu_act_title_ci_idx ON eu_act(lower(title));
CREATE TABLE IF NOT EXISTS eu_provision (
 provision_id text PRIMARY KEY, celex text NOT NULL REFERENCES eu_act(celex) ON DELETE CASCADE,
 cellar_uuid text, parent_id text, kind text NOT NULL, label text, logical_path text,
 text text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 search_vector tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('french',coalesce(label,'')),'A') ||
  setweight(to_tsvector('french',coalesce(text,'')),'B')
 ) STORED
);
CREATE INDEX IF NOT EXISTS eu_provision_celex_idx ON eu_provision(celex);
CREATE INDEX IF NOT EXISTS eu_provision_parent_idx ON eu_provision(parent_id);
CREATE INDEX IF NOT EXISTS eu_provision_kind_idx ON eu_provision(kind);
CREATE INDEX IF NOT EXISTS eu_provision_search_gin_idx ON eu_provision USING GIN(search_vector);
