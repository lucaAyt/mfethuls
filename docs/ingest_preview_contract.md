# Registry Preview and Ingest Contract

Detailed payload contracts for the two core ingest endpoints. For a full endpoint listing including `GET /datasets`, `GET /dataset/{name}`, and `DELETE /dataset/{name}` see [api_reference.md](api_reference.md).

All endpoints require `Authorization: Bearer <MFETHULS_API_KEY>`.

---

## POST /registry/preview

Parse an uploaded registry spreadsheet and return per-row validation. Runs the same checks that the worker runs before parsing — use this to catch problems before committing to an ingest.

**Request** `multipart/form-data`:
- `file`: CSV or XLSX upload (optional — omit to validate the server-side `PATH_TO_REGISTRY`)

**Response 200:**

```json
{
  "rows": [
    {
      "row_number": 1,
      "values": {
        "name": "CL_dsc_001",
        "experiment_id": "EXP001-240101",
        "instrument_name": "dsc_mettler_toledo",
        "sample_id": "S001-240101",
        "measurement_profile": null
      },
      "valid": true,
      "errors": [],
      "warnings": []
    },
    {
      "row_number": 2,
      "values": {
        "name": "CL_rheometer_003",
        "experiment_id": "EXP003-240101",
        "instrument_name": "rheometer",
        "measurement_profile": null
      },
      "valid": false,
      "errors": [
        {
          "field": "measurement_profile",
          "message": "Rheometer experiments require a measurement_profile (e.g. 'flow_curve', 'oscillatory_frequency_sweep')."
        }
      ],
      "warnings": []
    }
  ],
  "summary": {"total": 2, "valid": 1, "invalid": 1}
}
```

**Validation rules:**

| Check | Outcome |
|-------|---------|
| `name` missing | error |
| `experiment_id` not matching `EXP###-######` | error |
| `instrument_name` not in `instrument_params.json` | error |
| No parser registered for instrument + model | error |
| No schema JSON found for instrument | error |
| Profile rule violated (rheometer, DMA) | error |
| `instrument_name` blank | warning |
| `PATH_TO_DATA/<experiment_id>` folder absent | warning |

Warnings do not block ingest. Errors block ingest unless `allow_invalid=true` is passed.

---

## POST /ingest

Start a background ingest job. Runs the same validation as `/registry/preview`; rejects by default if any row is invalid.

**Request** `multipart/form-data`:
- `file`: CSV or XLSX upload (optional — omit to use the server-side `PATH_TO_REGISTRY`)

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage_mode` | string | `local` | `local`, `cloud`, or `both` |
| `cloud_provider` | string | — | `s3` or `azure` — required when mode is `cloud` or `both` |
| `allow_invalid` | bool | `false` | Submit even if registry has invalid rows |

**Response 202:**

```json
{
  "job_id": "a3f8c1e2d4b5...",
  "status": "queued",
  "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_<job_id>.parquet"
}
```

Response header: `Location: /jobs/<job_id>`

**Response 422** (invalid rows blocked):

```json
{
  "message": "Registry contains invalid rows",
  "summary": {"total": 5, "valid": 4, "invalid": 1},
  "invalid_rows": [
    {
      "row_number": 2,
      "values": {"name": "CL_bad", "experiment_id": "BADID", "instrument_name": "dsc"},
      "valid": false,
      "errors": [{"field": "experiment_id", "message": "..."}],
      "warnings": []
    }
  ]
}
```

---

## GET /jobs

List ingest jobs, newest first. Useful when the `job_id` from a previous submission has been lost.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `status` | string | — | Filter: `queued`, `running`, `completed`, `failed` |
| `limit` | int | `20` | Max results (1–100) |

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
    "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_<job_id>.parquet",
    "registry_table": "registry_a3f8c1e2d4b5",
    "datasets": [
      {
        "experiment_id": "EXP001-240101",
        "status": "persisted",
        "storage_path": "/data/mfethuls_storage/dsc_mettler_toledo/EXP001-240101/EXP001_240101_S001_R001.parquet",
        "dataset_id": "EXP001_240101_S001_R001"
      },
      {
        "experiment_id": "EXP002-240101",
        "status": "skipped"
      }
    ],
    "created_at": "2026-06-14T10:30:00",
    "updated_at": "2026-06-14T10:32:45"
  }
]
```

---

## GET /jobs/{job_id}

Get status and result for one job. Poll this until `status` is `completed` or `failed`.

**Response 200:**

```json
{
  "job_id": "a3f8c1e2d4b5...",
  "status": "running",
  "progress": 55,
  "message": "reading registry",
  "storage_mode": "local",
  "cloud_provider": null,
  "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_<job_id>.parquet",
  "registry_table": null,
  "datasets": null,
  "created_at": "2026-06-14T10:30:00",
  "updated_at": "2026-06-14T10:31:10"
}
```

**Per-experiment `status` values in `datasets`:**

| Value | Meaning |
|-------|---------|
| `persisted` | Parquet written + Postgres metadata saved |
| `registered` | Already cached — Parquet existed, DuckDB view re-registered |
| `skipped` | No `instrument_name` in registry row — cannot parse yet |
| `failed` | Parser error or storage error — other experiments continue |

**Job `status` lifecycle:**

```
queued → running → completed
                 → failed
```

`failed` at the job level means the entire job could not run (e.g. registry unreadable). Individual experiment failures set `status: failed` on that entry inside `datasets` but do not fail the whole job.

**Response 404:** job not found.
