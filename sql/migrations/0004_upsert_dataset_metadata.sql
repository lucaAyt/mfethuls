-- 0004_upsert_dataset_metadata.sql
-- Convert datasets metadata persistence to an upsert-friendly shape.
-- Safe to run multiple times.

-- Add refresh tracking if the column is missing.
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT now();

-- Backfill updated_at for existing rows.
UPDATE datasets
SET updated_at = COALESCE(updated_at, created_at, now());

-- Remove duplicate rows for the same canonical dataset key before adding the unique index.
WITH ranked AS (
    SELECT
        ctid,
        row_number() OVER (
            PARTITION BY experiment_id, dataset_name
            ORDER BY created_at DESC NULLS LAST, id DESC
        ) AS rn
    FROM datasets
)
DELETE FROM datasets d
USING ranked r
WHERE d.ctid = r.ctid
  AND r.rn > 1;

-- Enforce one canonical metadata row per dataset.
CREATE UNIQUE INDEX IF NOT EXISTS datasets_experiment_dataset_unique
    ON datasets (experiment_id, dataset_name);
