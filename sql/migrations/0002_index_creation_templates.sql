-- 0002_index_creation_templates.sql
-- Template index creation statements. Run these once you have sufficient rows
-- or when read performance requires it. Use CONCURRENTLY in production to
-- avoid locking writes (must be run outside transactions).

-- Example indexes (uncomment and run when needed):
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_instrument_name ON datasets(instrument_name);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_instrument_type ON datasets(instrument_type);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_schema_version ON datasets(schema_version);
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_mfethuls_version ON datasets(mfethuls_version);

-- For JSONB fields you query often, consider a GIN index (adjust path as needed):
-- CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_datasets_schema_norm_gin ON datasets USING gin (schema_normalization);

-- Notes:
-- - `CONCURRENTLY` cannot be executed inside a transaction block.
-- - Running many indexes on write-heavy tables increases insert/update cost.
-- - Test index benefits with EXPLAIN ANALYZE on representative queries.
