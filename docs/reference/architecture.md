# mfethuls architecture

mfethuls bridges laboratory instrument exports and analysis-ready datasets: a **registry** (spreadsheet) describes experiments; an **ETL pipeline** parses and normalizes raw data; **storage and query layers** expose Parquet, metadata, and SQL to users and BI tools.

---

## System context

```mermaid
flowchart TB
  subgraph people [People]
    RS[Experimentalist]
    DS[Data scientist]
    MAINT[Maintainer]
  end

  subgraph inputs [Inputs]
    REG[Registry CSV/XLSX\nshared OneDrive / local]
    RAW[Raw instrument files\nDSC, TGA, FTIR, SEC ...]
    CFG[instrument_params.json\n+ schema JSON files]
  end

  subgraph mfethuls [mfethuls]
    R[Registry layer]
    E[ETL engine]
    S[Storage layer]
    U[User interfaces]
  end

  subgraph outputs [Outputs]
    PQ[Parquet datasets]
    META[Metadata — Postgres + .json sidecars]
    DDB[(DuckDB catalog)]
  end

  RS --> REG
  RS --> RAW
  MAINT --> CFG
  REG --> R
  RAW --> E
  CFG --> E
  R --> E
  E --> S
  S --> PQ
  S --> META
  S --> DDB
  U --> S
  DS --> U
  DS --> DDB
```

| Role | Responsibilities |
|------|-----------------|
| Experimentalist | Registry rows, descriptions, measurement profiles, raw data files |
| Maintainer | Parsers, schema JSON, instrument config |
| Data scientist | Queries, notebooks, downstream BI, comparison sets |

---

## Deployment modes

```mermaid
flowchart LR
  subgraph local ["Local mode (MFETHULS_MODE=local)"]
    NB[Notebooks / CLI]
    ST[Streamlit explorer]
    LP[Local Parquet]
    LD[(DuckDB file)]
    NB --> LP
    ST --> LP
    LP --> LD
  end

  subgraph service ["Service mode (MFETHULS_MODE=service)"]
    USER[User / Browser]
    AUTH[Auth middleware\nBearer token]
    API[FastAPI :8000]
    WK[Worker]
    PG[(Postgres\njobs + metadata)]
    LD2[(DuckDB file)]
    LP2[Parquet local/cloud]
    ST[Streamlit :8501]

    USER --> ST
    ST -->|Authorization: Bearer| AUTH
    AUTH --> API
    API --> PG
    WK --> PG
    API -->|read-only\nper request| LD2
    WK -->|brief write\nend of job| LD2
    WK --> LP2
  end
```

**Local mode:** no Postgres required; ingest writes Parquet and registers DuckDB views on disk. Single-process — no lock contention.

**Service mode:** API queues jobs in Postgres; worker runs the ingest pipeline; API holds DuckDB read-only for milliseconds per request; worker holds a write lock only at the end of each job (batch view registration). Streamlit connects directly to DuckDB via the shared data volume.

---

## End-to-end ingest pipeline

```mermaid
sequenceDiagram
  participant User
  participant API as FastAPI + Auth
  participant PG as Postgres
  participant Worker
  participant ETL as ETL core
  participant Store as Storage (Parquet + Postgres)
  participant DDB as DuckDB

  User->>API: POST /registry/preview
  API->>API: validate_registry_dataframe
  API-->>User: rows + errors/warnings + summary

  User->>API: POST /ingest (Bearer token)
  API->>API: validate registry (strict unless allow_invalid)
  API->>PG: create_job (queued)
  API-->>User: 202 {job_id}

  loop Poll until done
    User->>API: GET /jobs/{job_id}
    API-->>User: {status, progress, datasets}
  end

  Worker->>PG: claim_next_job (FOR UPDATE SKIP LOCKED)
  Worker->>Worker: clear_experiment_registry()
  Worker->>Worker: load_experiment_registry(PATH_TO_REGISTRY)

  loop Each experiment — no DuckDB connection held
    Worker->>ETL: ingest_experiment_dataset(query_backend=None)
    ETL->>Store: write Parquet file
    ETL->>Store: write .metadata.json sidecar
    ETL->>PG: upsert dataset metadata (optional)
  end

  Note over Worker,DDB: Brief write window — milliseconds
  Worker->>DDB: open write connection
  Worker->>DDB: batch register_parquet() for all experiments
  Worker->>DDB: close write connection

  Worker->>PG: update job → completed

  User->>API: GET /datasets
  API->>DDB: duckdb_session(read_only=True)
  API-->>User: list of registered datasets

  User->>API: GET /dataset/{name}?limit=100
  API->>DDB: duckdb_session(read_only=True)
  API-->>User: paginated rows + column types
```

**Key design decision:** the worker holds no DuckDB connection while parsing experiments. Only after all Parquet files are written does it open a write connection to batch-register views — keeping the exclusive write lock window to milliseconds rather than minutes.

---

## Authentication

```mermaid
flowchart LR
  REQ[Incoming request] --> HLT{Path = /health?}
  HLT -->|yes| PASS[Route handler — no auth]
  HLT -->|no| MW[verify_token dependency]
  MW -->|MFETHULS_API_KEY not set| ERR500[500 RuntimeError — misconfigured]
  MW -->|missing / wrong token| ERR401[401 Unauthorized]
  MW -->|valid Bearer token| ROUTE[Route handler]
```

All routes registered through the main router require a valid `Authorization: Bearer <token>` header. The token is compared against `MFETHULS_API_KEY` at request time. `GET /health` is registered directly on `app` and is always public — this allows Docker and load-balancer health checks to work without credentials.

**Best practice:** generate a long random token and store it in your `.env`. Never commit the token to version control.

```shell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## ETL core — single experiment

```mermaid
flowchart TD
  A[Experiment from registry] --> B[RegistryValidator]
  B -->|structural error| X[skip — logged as warning]
  B -->|ok| C[Assign experiment_id via manifest\nauto-generate hex UUID on first ingest]
  C --> D[Find raw file via os.walk\nmatches raw_data_filename stem]
  D --> E[Select parser by instrument + model]
  E --> F[collect_dataframe_from_paths\nper-file error isolation]
  F --> G[apply_dataframe_schema\nalias mapping + dtype coercion]
  G --> H[Dataset: data + metadata]
  H --> I{Characterizer?}
  I -->|DSC| J[Optional peak profiling]
  I -->|TGA| JT[Compute mass_pct from mass_mg]
  I -->|other| K[Skip]
  J --> L[StorageManager]
  JT --> L
  K --> L
  L --> M[Local / S3 / Azure Parquet]
  L --> N[.metadata.json sidecar]
  L --> O[Postgres datasets row\noptional]
```

| Step | Module |
|------|--------|
| Registry load | `experiments.py` — `load_experiment_registry`, `experiment_from_registry_record` |
| Validation | `registry_validator.py` — `validate_registry_dataframe`, `RegistryValidator` |
| ID assignment | `manifest.py` — `FileManifestBackend` / `PostgresManifestBackend` |
| Path resolution | `manifest.py` — `find_data_files()` walks instrument folder by `raw_data_filename` stem |
| Orchestration | `config/loader.py` — `ingest_experiment_dataset` |
| Parse | `factory.py`, `parsers/` |
| Normalize | `schema_normalization.py`, `config/schemas/*.json` |
| Characterize | `characterizers/dsc.py` (peak profiling), `characterizers/tga.py` (mass_pct) |
| Persist | `storage/manager.py`, `storage/backends.py`, `storage/metadata.py` |
| Query catalog | `storage/duckdb_backend.py` — views named after `experiment.name` |

---

## Registry validation (preview = same checks as pre-ingest)

```mermaid
flowchart TD
  ROW[Spreadsheet row] --> EFR[experiment_from_registry_record]
  EFR -->|missing name / duplicate name| INV[valid=false, errors]
  EFR -->|Experiment built| VE[RegistryValidator.validate_experiment_details]
  VE -->|instrument not in config| INV2[valid=false, errors]
  VE -->|parser not registered| INV3[valid=false, errors]
  VE -->|profile rule violated| INV4[valid=false, errors]
  VE -->|ok| WARN{Warnings only}
  WARN --> DATA[raw data file not found under PATH_TO_DATA?]
  WARN --> INST[instrument_name absent?]
  DATA --> OK[valid=true]
  INST --> OK
```

`POST /registry/preview` and `POST /ingest` run the same validation. The difference is that preview always returns results; ingest blocks submission when `allow_invalid=false` (default) and any row is invalid.

---

## Storage layout

```mermaid
flowchart LR
  subgraph files [Filesystem / object store]
    ROOT[PATH_TO_LOCAL_STORAGE\nor S3/Azure bucket]
    ROOT --> I1[instrument_name/]
    I1 --> E1[internal_hex_id/\nauto-assigned, never user-facing]
    E1 --> P1["name_sample_run.parquet"]
    E1 --> M1["name_sample_run.metadata.json"]
  end

  subgraph duckdb [DuckDB — MFETHULS_DUCKDB_PATH]
    REGT[dataset_registry table\ntable_name, storage_path, experiment_name, registered_at]
    V1["VIEW named after experiment\ne.g. CL_dsc_001_S001_R001"]
    REGT --> V1
  end

  subgraph postgres [Postgres — service mode]
    JOBS[ingest_jobs\nstatus, progress, datasets JSONB]
    DATASETS[datasets\nmetadata, provenance, schema version]
  end

  P1 --> V1
  P1 -.->|optional| DATASETS
```

**Parquet files are the source of truth.** DuckDB views are derived from them and can be rebuilt at any time by re-registering. The `dataset_registry` table inside DuckDB is the only mutable state that is hard to reconstruct — everything else (Parquet, Postgres metadata) survives a DuckDB file deletion.

---

## DuckDB concurrency model

```mermaid
sequenceDiagram
  participant API
  participant Worker
  participant DDB as DuckDB file

  Note over API,DDB: Normal operation — reads and writes do not overlap

  API->>DDB: open read-only (milliseconds)
  API->>DDB: SELECT from dataset_registry / view
  API->>DDB: close

  Worker->>Worker: parse all experiments, write Parquet
  Note over Worker,DDB: Write lock held only here ↓
  Worker->>DDB: open write (milliseconds)
  Worker->>DDB: batch INSERT into dataset_registry + CREATE VIEW
  Worker->>DDB: close
  Note over Worker,DDB: Write lock released ↑

  API->>DDB: open read-only (next request — no contention)
```

DuckDB uses an OS-level exclusive file lock for write connections. A read connection while a write connection is open will fail. The worker is designed so the write lock is held only during the final batch registration step — after all Parquet files are written — making the window milliseconds rather than minutes.

---

## User interfaces

| Interface | Mode | Purpose |
|-----------|------|---------|
| Notebooks / CLI | local | Load, compare, plot experiments via Python API |
| `apps/Home.py` | local + service | Ingest sidebar, dataset browser, ad-hoc plots |
| FastAPI (`api/`) | service | Preview, ingest, job management, dataset access |
| Worker (`worker.py`) | service | Background ingest processor |

---

## Package layout

```
src/mfethuls/
  experiments.py          # Registry model, load_experiment_registry, clear_experiment_registry
  registry_validator.py   # Pre-parse validation + profile matching
  manifest.py             # experiment_id assignment + find_data_files (os.walk matcher)
  factory.py              # parse_experiment + instrument_data_path_constructor
  schema_normalization.py # Column aliasing + dtype coercion
  dataset.py              # Dataset dataclass
  comparison.py           # ComparisonSet for multi-experiment analysis
  characterizers/
    dsc.py                # DSC peak profiling
    tga.py                # TGA mass_pct computation from mass_mg
  config/
    loader.py             # Ingest orchestration — ingest_experiment_dataset
    instrument_params.json
    schemas/              # Per-instrument JSON schema files
  parsers/                # Instrument-specific file readers
  storage/
    backends.py           # Local, S3, Azure Parquet backends
    config.py             # _dataset_basename, _view_basename helpers
    duckdb_backend.py     # DuckDB catalog — register, query, remove datasets
    metadata.py           # PostgresMetadataBackend
    job_store.py          # Postgres job queue (FIFO, FOR UPDATE SKIP LOCKED)
    manager.py            # StorageManager composition layer
  api/
    app.py                # FastAPI wiring + auth dependency
    auth.py               # verify_token bearer token dependency
    routes.py             # Route handlers
  worker.py               # Background job processor + timeout
  plotting/               # Optional viz (viz extra)
```

---

## Related docs

- [guides/quickstart.md](../guides/quickstart.md) — entry point for new users
- [guides/data_analysis.md](../guides/data_analysis.md) — notebook access patterns: Python API, DuckDB SQL, Postgres metadata, model building
- [reference/registry.md](registry.md) — registry spreadsheet format and column reference
- [reference/api.md](api.md) — complete endpoint reference with examples
- [reference/schema.md](schema.md) — canonical column names and normalization rules
