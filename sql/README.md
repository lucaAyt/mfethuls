Database migration scripts

Location: `sql/migrations/`

0001_add_columns_if_missing.sql
- Idempotent `ALTER TABLE` statements to add new columns introduced by
  recent schema changes (sample_id, run_id, experiment_name, measurement_profile,
  mfethuls_version, schema_normalization).
- Safe to run multiple times.

0002_index_creation_templates.sql
- Template `CREATE INDEX` statements for future scaling.
- Intentionally left commented out; run when dataset sizes or query latency
  justify adding indexes.

0003_create_ingest_jobs.sql
- Creates the `ingest_jobs` table used by the control-plane job store.
- Safe to run multiple times.

0004_upsert_dataset_metadata.sql
- Adds `updated_at` to `datasets`, deduplicates legacy rows, and creates a
  unique index on `(experiment_id, dataset_name)` so refreshes upsert instead
  of inserting duplicates.
- Safe to run multiple times after the table exists.

0005_add_dataset_location_columns.sql
- Adds explicit `local_storage_path` and `cloud_storage_path` columns to
  `datasets` and backfills them from the canonical path and provenance when
  possible.
- Safe to run multiple times after the table exists.

How to run:

- Locally with `psql`:

```bash
psql -h <host> -U <user> -d <db> -f sql/migrations/0001_add_columns_if_missing.sql
```

- Inside Docker (example):

```bash
docker exec -i mfethuls-pg psql -U mfethuls -d mfethuls -f - < sql/migrations/0001_add_columns_if_missing.sql
```

Operational notes:

- Index creation with `CONCURRENTLY` must be run outside a transaction; you can
  run those commands from `psql` directly.
- Test migrations on a copy of production data before applying to live DBs.
- Consider adopting Alembic or another migration tool for ongoing schema management
  if the project will evolve frequently.
