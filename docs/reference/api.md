# API Reference

Full reference for the mfethuls service-mode REST API (`MFETHULS_MODE=service`).

Base URL: `http://localhost:8000` (or your configured host behind Caddy).

---

## Authentication

All endpoints except `GET /health` require a bearer token.

```
Authorization: Bearer <MFETHULS_API_KEY>
```

The token is set via the `MFETHULS_API_KEY` environment variable. Generate a secure value:

```shell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Responses when auth fails:**

| Situation | Status | Body |
|-----------|--------|------|
| Header absent or token wrong | 401 | `{"detail": "Invalid or missing bearer token."}` |
| `MFETHULS_API_KEY` not set | 500 | RuntimeError — server misconfiguration |

---

## Endpoints

### `GET /health`

Health check. Public — no auth required. Used by Docker health checks and load balancers.

**Response 200:**
```json
{"status": "ok"}
```

---

### `POST /registry/preview`

Parse and validate a registry spreadsheet. Returns per-row results without starting an ingest.

**Request:** `multipart/form-data`
- `file` (optional): CSV or XLSX upload. If omitted, reads `PATH_TO_REGISTRY` from the server.

**Response 200:**
```json
{
  "rows": [
    {
      "row_number": 1,
      "values": {
        "name": "CL_dsc_001",
        "instrument_name": "dsc_mettler_toledo",
        "sample_id": "S001",
        "run_id": "R001"
      },
      "valid": true,
      "errors": [],
      "warnings": []
    },
    {
      "row_number": 2,
      "values": {
        "name": "CL_tga_002",
        "instrument_name": "tga_unknown"
      },
      "valid": false,
      "errors": [
        {
          "field": "instrument_name",
          "message": "Unknown instrument_name 'tga_unknown'. See instrument_params.json for valid names."
        }
      ],
      "warnings": []
    }
  ],
  "summary": {"total": 2, "valid": 1, "invalid": 1}
}
```

**What counts as invalid:**
- Missing required field `name` or `instrument_name`
- Duplicate `name` values in the registry
- `instrument_name` not in `instrument_params.json`
- Registered parser not found for instrument
- Profile rules violated (e.g. rheometer oscillatory sweep missing `measurement_profile`)

**What counts as a warning:**
- `instrument_name` absent (experiment is visible but cannot be analysed)
- Raw data file not found under `PATH_TO_DATA` (data path check)

---

### `POST /ingest`

Start a background ingest job. Validates the registry first; rejects if invalid rows exist (unless `allow_invalid=true`). Reads the registry from `PATH_TO_REGISTRY` on the server.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage_mode` | string | `local` | `local`, `cloud`, or `both` |
| `cloud_provider` | string | — | `s3` or `azure` (required when `storage_mode` is `cloud` or `both`) |
| `allow_invalid` | bool | `false` | Submit even if registry has invalid rows |
| `experiments` | string | — | Comma-separated experiment names to ingest; omit for all |
| `refresh` | bool | `false` | Force re-parse even if Parquet cache exists |

**Response 202:**
```json
{
  "job_id": "a3f8c1e2d4b5...",
  "status": "queued",
  "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_<job_id>.parquet"
}
```

Header: `Location: /jobs/<job_id>`

**Response 422** (when `allow_invalid=false` and registry has errors):
```json
{
  "message": "Registry contains invalid rows",
  "summary": {"total": 3, "valid": 2, "invalid": 1},
  "invalid_rows": [...]
}
```

---

### `POST /sync`

Pull raw data and registry from OneDrive using rclone. Blocks until the sync completes (up to several minutes for large data sets).

Requires rclone to be installed on the server and `RCLONE_REMOTE`, `RCLONE_SOURCE_PATH`, `RCLONE_REGISTRY_PATH` set in `.env`. See [cloud_deployment.md](../guides/cloud_deployment.md) for setup.

**Response 200:**
```json
{"status": "sync_complete"}
```

**Response 500:** rclone not installed, sync script not found, or rclone exited with an error (body contains last 500 chars of stderr).

---

### `GET /jobs`

List ingest jobs, newest first.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | — | Filter by status: `queued`, `running`, `completed`, `failed` |
| `limit` | int | `20` | Number of results (1–100) |

**Response 200:**
```json
[
  {
    "job_id": "a3f8c1e2d4b5...",
    "status": "completed",
    "progress": 100,
    "message": "ingest completed",
    "storage_mode": "local",
    "cloud_provider": null,
    "datasets": [
      {
        "name": "CL_dsc_001",
        "status": "persisted",
        "storage_path": "...",
        "table_name": "CL_dsc_001_S001_R001"
      }
    ],
    "created_at": "2026-06-14T10:30:00",
    "updated_at": "2026-06-14T10:32:45"
  }
]
```

---

### `GET /jobs/{job_id}`

Get status and result for a specific job.

**Response 200:**
```json
{
  "job_id": "a3f8c1e2d4b5...",
  "status": "running",
  "progress": 42,
  "message": "reading registry",
  "storage_mode": "local",
  "cloud_provider": null,
  "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_<job_id>.parquet",
  "registry_table": null,
  "datasets": null,
  "created_at": "2026-06-14T10:30:00",
  "updated_at": "2026-06-14T10:30:05"
}
```

**Job status lifecycle:**

```
queued → running → completed
                 → failed
```

`progress` is an integer 0–100. Per-experiment results appear in `datasets` once the job completes.

**Response 404:** job not found.

---

### `GET /datasets`

List all datasets registered in the DuckDB catalog.

**Response 200:**
```json
[
  {
    "table_name": "CL_dsc_001_S001_R001",
    "name": "CL_dsc_001",
    "storage_mode": "local",
    "queryable": true,
    "storage_path": "/data/mfethuls_storage/dsc_mettler_toledo/<internal_id>/CL_dsc_001_S001_R001.parquet",
    "registered_at": "2026-06-14T10:32:45"
  }
]
```

`table_name` is the DuckDB view name (based on `name + sample_id + run_id`) and is used in `GET /dataset/{table_name}` and `DELETE /dataset/{table_name}`.

---

### `GET /dataset/{table_name}`

Fetch rows from a registered dataset with pagination.

**Path parameter:** `table_name` — the value from `GET /datasets` (e.g. `CL_dsc_001_S001_R001`).

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | `100` | Rows per page (min 1) |
| `offset` | int | `0` | Row offset for pagination |

**Response 200:**
```json
{
  "query_id": "uuid",
  "status": "completed",
  "columns": [
    {"name": "temperature_C", "type": "float64"},
    {"name": "heat_flow_mW", "type": "float64"}
  ],
  "rows": [
    [25.0, -0.4],
    [26.0, -0.5]
  ],
  "pagination": {
    "limit": 100,
    "offset": 0,
    "returned_rows": 2
  },
  "execution_ms": 12
}
```

**Response 400:** dataset not found, or query error.

---

### `DELETE /dataset/{table_name}`

Remove a dataset from the DuckDB catalog and drop its view.

**Important:** this removes the dataset from the query layer only. The underlying Parquet file on disk or object storage is **not deleted** and can be re-registered by running a new ingest.

**Response 200:**
```json
{"deleted": "CL_dsc_001_S001_R001"}
```

**Response 404:** dataset not found in catalog.

---

## Error format

All errors follow FastAPI's standard format:

```json
{"detail": "human-readable message"}
```

Or for structured errors (e.g. validation failures):

```json
{
  "detail": {
    "message": "...",
    "summary": {...},
    "invalid_rows": [...]
  }
}
```

---

## Environment variables quick reference

| Variable | Description |
|----------|-------------|
| `MFETHULS_MODE` | `local` or `service` |
| `MFETHULS_API_KEY` | Bearer token — required in service mode |
| `PATH_TO_DATA` | Root folder for raw instrument files |
| `PATH_TO_REGISTRY` | Shared experiments registry CSV/XLSX |
| `PATH_TO_LOCAL_STORAGE` | Root folder for Parquet output |
| `MFETHULS_DUCKDB_PATH` | DuckDB catalog file path |
| `MFETHULS_POSTGRES_ENABLED` | `true` to enable Postgres |
| `MFETHULS_POSTGRES_USER` | Postgres credentials |
| `MFETHULS_POSTGRES_PASSWORD` | |
| `MFETHULS_POSTGRES_DB` | |
| `MFETHULS_POSTGRES_HOST` | |
| `MFETHULS_POSTGRES_PORT` | Default `5432` |
| `MFETHULS_JOB_TIMEOUT_SECONDS` | Max seconds per job (default `1800`) |
| `MFETHULS_S3_REGION` | S3 / DigitalOcean Spaces region |
| `MFETHULS_S3_ENDPOINT` | S3-compatible endpoint URL |
| `MFETHULS_S3_ACCESS_KEY` | S3 access key |
| `MFETHULS_S3_SECRET_KEY` | S3 secret key |
| `RCLONE_REMOTE` | rclone remote name (e.g. `onedrive`) |
| `RCLONE_SOURCE_PATH` | OneDrive path to raw data folder |
| `RCLONE_REGISTRY_PATH` | OneDrive path to registry CSV |
