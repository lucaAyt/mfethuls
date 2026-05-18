# Database Integration Design

Goal: implement a pipeline where metadata is stored in Postgres and bulk tabular data is stored as Parquet files (local in dev, cloud object storage in prod). Postgres stores paths and searchable metadata (JSONB) while Parquet holds columnar data for analytics.

Benefits
- Scalable: Parquet + object storage decouple compute and storage
- Fast ad-hoc analysis when combined with DuckDB/Trino/Athena
- Postgres gives transactional metadata, indexing and joins for fast filtering

Recommended stack
- Postgres for metadata (JSONB) + indexes (GIN on JSONB)
- Parquet files for dataset storage (local for dev; S3/GCS/Azure for prod)
- DuckDB for local ad-hoc queries; Trino/Presto/Athena for prod-scale queries
- BI: Superset/Metabase over Postgres (metadata) + Trino for parquet analytics

Schema sketch (Postgres)

```sql
-- experiments table (one registry row)
CREATE TABLE experiments (
  id SERIAL PRIMARY KEY,
  name TEXT,
  experiment_id TEXT UNIQUE,
  instrument_name TEXT,
  instrument_type TEXT,
  sample_id TEXT,
  status TEXT,
  registry_measurement_profile TEXT,
  raw_registry_row JSONB,
  registered_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- datasets table (one parsed dataset)
CREATE TABLE datasets (
  id SERIAL PRIMARY KEY,
  experiment_id TEXT REFERENCES experiments(experiment_id),
  dataset_name TEXT,
  storage_path TEXT,
  storage_format TEXT DEFAULT 'parquet',
  rows INTEGER,
  cols INTEGER,
  min_x DOUBLE PRECISION,
  max_x DOUBLE PRECISION,
  measurement_profile TEXT,
  schema_normalization JSONB,
  provenance JSONB,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- measurement_profiles canonical mapping (optional)
CREATE TABLE measurement_profiles (
  canonical_name TEXT PRIMARY KEY,
  aliases JSONB
);

-- Indexes
CREATE INDEX idx_datasets_measurement_profile ON datasets(measurement_profile);
CREATE INDEX idx_experiments_sample_id ON experiments(sample_id);
CREATE INDEX idx_experiments_registry_profile ON experiments(registry_measurement_profile);
CREATE INDEX idx_experiments_raw_row_gin ON experiments USING GIN (raw_registry_row);
```

Storage layout
- Dev: `storage_root/<instrument_type>/<experiment_id>/<dataset_name>.parquet`
- Prod (S3): `s3://bucket/mfethuls/<instrument_type>/<year=YYYY>/<experiment_id>/<dataset_name>.parquet`

Provenance & metadata contracts
- Always persist both `registry_measurement_profile` (raw) and `measurement_profile` (canonical) on the `datasets` row
- Store `schema_normalization` containing applied schema, warnings, and renamed columns
- Store `provenance` with `parser_version`, `mfethuls_version`, and `storage` backend info

Next dev tasks (initial prototype)
1. Implement `LocalParquetStorage` (write parquet to local path)
2. Implement `PostgresMetadataBackend` (register experiments & datasets)
3. Wire the parser/factory to write parquet and call metadata backend when `--persist-metadata` is enabled
4. Provide a DuckDB helper to run queries over selected parquet paths

Notes
- We'll use SQLAlchemy for the Postgres backend; add to project dependencies when ready
- For S3 support, use `s3fs` + DuckDB or `pyarrow` to read/write parquet

```yaml
pyproject / deps suggestion:
- sqlalchemy
- psycopg2-binary
- s3fs (optional for S3)
- duckdb (optional)
```
