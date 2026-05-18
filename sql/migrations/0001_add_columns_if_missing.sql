-- 0001_add_columns_if_missing.sql
-- Idempotent migration to add new metadata columns to the `datasets` table.
-- Safe to run multiple times; does not alter existing columns.

-- Add textual columns added in recent schema changes
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS sample_id TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS run_id TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS experiment_name TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS measurement_profile TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS mfethuls_version TEXT;

-- Add JSONB column for schema_normalization if missing
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS schema_normalization JSONB;

-- Note: `provenance` JSONB column is expected to already exist from earlier releases.
-- If you maintain separate `experiments` table schemas, adjust accordingly.

-- Usage:
-- psql -h <host> -U <user> -d <db> -f sql/migrations/0001_add_columns_if_missing.sql
-- Or run inside Docker: docker exec -i <pg_container> psql -U <user> -d <db> -f - < sql/migrations/0001_add_columns_if_missing.sql
