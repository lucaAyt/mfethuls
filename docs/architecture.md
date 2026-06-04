# mfethuls architecture

mfethuls bridges laboratory instrument exports and analysis-ready datasets: a **registry** (spreadsheet) describes experiments; an **ETL pipeline** parses and normalizes data; **storage and query layers** expose Parquet, metadata, and SQL.

## System context

```mermaid
flowchart TB
  subgraph people [People]
    RS[Experimentalist]
    DS[Data scientist]
    MAINT[Maintainer]
  end

  subgraph inputs [Inputs]
    REG[Registry CSV/XLSX]
    RAW[Raw instrument files]
    CFG[instrument_params.json + schemas]
  end

  subgraph mfethuls [mfethuls]
    R[Registry layer]
    E[ETL engine]
    S[Storage layer]
    U[User interfaces]
  end

  subgraph outputs [Outputs]
    PQ[Parquet datasets]
    META[Metadata JSON + Postgres]
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

| Role | Owns |
|------|------|
| Experimentalist | Registry rows, descriptions, measurement profiles |
| Maintainer | Parsers, schema JSON, instrument config |
| Data scientist | Queries, notebooks, downstream BI |

## Deployment modes

```mermaid
flowchart LR
  subgraph local [MFETHULS_MODE=local]
    NB[Notebooks / CLI]
    ST[Streamlit explorer]
    LP[Local Parquet]
    LD[(DuckDB file)]
    NB --> LP
    ST --> LP
    LP --> LD
  end

  subgraph service [MFETHULS_MODE=service]
    API[FastAPI]
    WK[Worker]
    PG[(Postgres jobs + metadata)]
    API --> PG
    WK --> PG
    API --> LD2[(DuckDB file)]
    WK --> LD2
    WK --> LP2[Parquet local/cloud]
  end
```

- **Local:** no Postgres required; ingest writes Parquet and registers DuckDB views on disk.
- **Service:** API queues jobs in Postgres; worker runs the same ingest pipeline; API queries DuckDB **read-only per request**; worker **closes DuckDB after each job** so both can share one database file.

## End-to-end ingest pipeline

```mermaid
sequenceDiagram
  participant User
  participant API as FastAPI
  participant PG as Postgres
  participant Worker
  participant ETL as ETL core
  participant Store as Storage

  User->>API: POST /registry/preview
  API->>API: validate_registry_dataframe
  API-->>User: rows + errors/warnings + summary

  User->>API: POST /ingest
  API->>API: validate (strict unless allow_invalid)
  API->>PG: create_job
  API-->>User: 202 job_id

  Worker->>PG: claim job
  Worker->>Worker: load_experiment_registry
  loop Each experiment name
    Worker->>ETL: ingest_experiment_dataset
    ETL->>Store: Parquet + metadata.json
    ETL->>Store: register DuckDB view
    ETL->>PG: upsert dataset metadata optional
  end
  Worker->>Store: register registry parquet view
  Worker->>Worker: close DuckDB
  Worker->>PG: job completed

  User->>API: GET /jobs/job_id
  API-->>User: progress + per-experiment status

  User->>API: GET /datasets or POST /queries
  API->>Store: duckdb_session read_only
  API-->>User: views or SQL result
```

## ETL core (single experiment)

```mermaid
flowchart TD
  A[Experiment from registry] --> B[RegistryValidator]
  B -->|fail| X[Error before parse]
  B -->|ok| C[Resolve paths under PATH_TO_DATA]
  C --> D[Parser type + model]
  D --> E[Raw DataFrames from files]
  E --> F[apply_dataframe_schema]
  F --> G[Dataset data + metadata]
  G --> H{Characterizer?}
  H -->|DSC| I[Optional profiling]
  H -->|other| J[Skip]
  I --> K[StorageManager]
  J --> K
  K --> L[Local / S3 / Azure Parquet]
  K --> M[.metadata.json sidecar]
  K --> N[Postgres datasets row]
  K --> O[DuckDB register_parquet]
```

**Key modules:**

| Step | Module |
|------|--------|
| Registry load | `experiments.py` — `experiment_from_registry_record`, `load_experiment_registry` |
| Validation | `registry_validator.py` — `validate_registry_dataframe`, `RegistryValidator.validate_experiment` |
| Orchestration | `config/loader.py` — `ingest_experiment_dataset`, `load_experiment_dataset` |
| Parse | `factory.py`, `parsers/*` |
| Normalize | `schema_normalization.py`, `config/schemas/*.json` |
| Persist | `storage/manager.py`, `storage/backends.py`, `storage/metadata.py` |
| Query catalog | `storage/duckdb_backend.py` |

## Registry validation (preview = worker pre-checks)

```mermaid
flowchart TD
  ROW[Spreadsheet row] --> EFR[experiment_from_registry_record]
  EFR -->|structural errors| INV[valid=false]
  EFR -->|Experiment built| VE[RegistryValidator.validate_experiment]
  VE -->|instrument parser schema profile| INV2[valid=false]
  VE -->|ok| WARN{Optional warnings}
  WARN --> DATA[PATH_TO_DATA/exp_id folder missing?]
  WARN --> INST[missing instrument_name?]
  DATA --> OK[valid=true]
  INST --> OK
```

## Storage layout

```mermaid
flowchart LR
  subgraph files [Filesystem / object store]
    ROOT[PATH_TO_LOCAL_STORAGE or bucket]
    ROOT --> I1[instrument_name/]
    I1 --> E1[experiment_id/]
    E1 --> P1["*.parquet"]
    E1 --> M1["*.metadata.json"]
  end

  subgraph duckdb [DuckDB file MFETHULS_DUCKDB_PATH]
    REGT[dataset_registry table]
    V1[view: dataset table names]
    REGT --> V1
  end

  subgraph postgres [Postgres service mode]
    JOBS[ingest_jobs]
    DATASETS[datasets metadata]
  end

  P1 --> V1
  P1 --> DATASETS
```

## User interfaces

| Interface | Mode | Purpose |
|-----------|------|---------|
| `mfethuls` CLI / notebooks | local | Load, compare, plot experiments |
| `apps/streamlit_app.py` | local | Ingest sidebar, browse DuckDB, ad-hoc plots |
| FastAPI (`mfethuls/api`) | service | Preview, ingest jobs, list datasets, SQL |
| Worker (`mfethuls/worker.py`) | service | Background ingest |
| External BI | either | Connect to DuckDB file, Postgres `datasets`, or Parquet paths |

## Package map

```
src/mfethuls/
  experiments.py      # Registry model + load
  registry_validator.py
  factory.py            # Paths + parse_experiment
  parsers/              # Instrument parsers
  schema_normalization.py
  dataset.py            # Dataset contract
  config/loader.py      # Ingest orchestration
  storage/              # Parquet, Postgres, DuckDB, jobs
  api/                  # FastAPI routes
  worker.py             # Job processor
  plotting/             # Optional viz (viz extra)
```

## Related docs

- [ROADMAP.md](../ROADMAP.md) — product priorities
- [SCHEMA_CONTRACT.md](../SCHEMA_CONTRACT.md) — canonical columns
- [ingest_preview_contract.md](ingest_preview_contract.md) — API payloads
- [database_integration.md](database_integration.md) — Postgres + Parquet design notes
