-- 0003_create_ingest_jobs.sql
-- Create ingest_jobs table for control-plane job tracking.
-- Safe to run multiple times.

CREATE TABLE IF NOT EXISTS ingest_jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    progress INT NOT NULL DEFAULT 0,
    message TEXT,
    storage_mode TEXT,
    cloud_provider TEXT,
    registry_storage_path TEXT,
    registry_table TEXT,
    datasets JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
