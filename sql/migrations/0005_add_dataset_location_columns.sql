-- 0005_add_dataset_location_columns.sql
-- Add explicit local/cloud storage location fields to the datasets table.
-- Safe to run multiple times.

ALTER TABLE datasets ADD COLUMN IF NOT EXISTS local_storage_path TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS cloud_storage_path TEXT;

-- Backfill the new fields from the existing canonical path and provenance.
UPDATE datasets
SET
    local_storage_path = COALESCE(
        local_storage_path,
        CASE
            WHEN provenance->'storage'->>'backend' IN ('s3', 'azure_blob') THEN NULL
            ELSE storage_path
        END
    ),
    cloud_storage_path = COALESCE(
        cloud_storage_path,
        CASE
            WHEN provenance->'storage'->>'backend' IN ('s3', 'azure_blob') THEN storage_path
            ELSE NULL
        END
    );
