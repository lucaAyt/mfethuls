# mfethuls Tutorial

Step-by-step walkthroughs for both operating modes. Start with **Local mode** if you're a researcher working on your own machine. Use **Service mode** if you're running a shared lab server with team access and Metabase dashboards.

Prerequisites: Python 3.11+, a virtual environment, and instrument data files on disk.

---

## Local mode

Local mode runs entirely on your laptop — no Docker, no Postgres, no server. Everything is a single Python process. Use this for exploratory analysis, notebook work, and validating your registry before sharing.

### 1. Install

**Developer / Python users:**

```shell
python -m venv .venv
source .venv/bin/activate            # Linux/macOS
.venv\Scripts\activate               # Windows

pip install git+ssh://git@github.com/lucaAyt/mfethuls.git
```

Add optional extras if needed:

```shell
pip install "mfethuls[viz]"          # Matplotlib / Plotly / Streamlit
pip install "mfethuls[notebook]"     # Jupyter support
```

**Non-technical users (no Python required):**

See [docs/local_user_setup.md](local_user_setup.md) for the `uv`-based launcher guide. You only need to install `uv` and double-click `launch.bat`.

### 2. Set environment variables

Create a `.env` file (or export variables in your shell) with paths that match your machine:

```
MFETHULS_MODE=local
PATH_TO_DATA=/path/to/raw/instrument/data
PATH_TO_REGISTRY=/path/to/experiments_registry.csv
PATH_TO_LOCAL_STORAGE=/path/to/parquet/output
```

`PATH_TO_DATA` should be the root folder containing sub-folders per instrument type (`DSC/`, `TGA/`, etc.). See [registry_reference.md](registry_reference.md) for the expected layout.

Load the variables before running Python:

```shell
export $(cat .env | xargs)           # Linux/macOS
# On Windows, set variables manually or use python-dotenv in your script
```

### 3. Create your registry

Create `experiments_registry.csv` following the format in [registry_reference.md](registry_reference.md). A minimal starting template:

```csv
name,instrument_name,sample_id,run_id,description
CL_dsc_001,dsc_mettler_toledo,S001,R001,
CL_tga_001,tga,S001,R001,
CL_rheometer_freq,rheometer,S002,R001,oscillatory frequency sweep
```

The `name` column is the only user-facing identifier — it must be unique. mfethuls assigns an internal ID automatically at ingest time. See [registry_reference.md](registry_reference.md) for the full column reference including `raw_data_filename`.

### 4. Validate the registry (optional but recommended)

Before ingesting, check that every row is valid:

```python
import mfethuls
from mfethuls.registry_validator import validate_registry_dataframe
from mfethuls.experiments import read_tabular_content

df = read_tabular_content("/path/to/experiments_registry.csv")
result = validate_registry_dataframe(df, check_data_paths=True, data_root="/path/to/data")

for row in result["rows"]:
    if not row["valid"]:
        print(f"Row {row['row_number']} — {row['values']['name']}: {row['errors']}")

print(result["summary"])
# {'total': 3, 'valid': 3, 'invalid': 0}
```

### 5. Run an ingest

```python
import os
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.experiments import load_experiment_registry, get_experiment

# Load the registry into memory
load_experiment_registry("/path/to/experiments_registry.csv")

# Ingest a single experiment
exp = get_experiment("CL_dsc_001")
result = ingest_experiment_dataset(exp, storage_mode="local")

print(result["status"])          # "persisted"
print(result["storage_path"])    # path to the Parquet file
```

To ingest all registered experiments in a loop:

```python
from mfethuls.experiments import load_experiment_registry, _EXPERIMENT_REGISTRY
from mfethuls.config.loader import ingest_experiment_dataset

df = load_experiment_registry("/path/to/experiments_registry.csv")

for name, exp in _EXPERIMENT_REGISTRY.items():
    result = ingest_experiment_dataset(exp, storage_mode="local")
    print(f"{name}: {result['status']}")
```

### 6. Load a dataset for analysis

After ingest the data is stored as Parquet. Load it directly into a DataFrame:

```python
import pandas as pd

# Path uses the internal experiment_id (auto-assigned hex, internal only)
df = pd.read_parquet(result["storage_path"])
print(df.head())
print(df.dtypes)
```

Or use the mfethuls storage backend to query by the human-readable view name:

```python
from mfethuls.storage import load_dataset_from_storage

# View name is built from experiment name + sample_id + run_id
df = load_dataset_from_storage("CL_dsc_001_S001_R001")
```

### 7. Compare experiments

```python
import mfethuls

# Load specific experiments by name
experiments = mfethuls.load_experiments(["CL_dsc_001", "CL_dsc_002"])

# Build a comparison set and get a tidy long-format DataFrame
comparison = mfethuls.compare(experiments)
df = comparison.to_dataframe()
print(df.groupby("experiment_name")["temperature_C"].describe())
```

### 8. Streamlit explorer

The Streamlit app provides a visual interface for local mode — load the registry, run ingests, browse datasets, and plot.

**Using the launcher (recommended for non-technical users):**

Double-click `launch.bat` (Windows) or run `bash launch.sh` (macOS/Linux). See [docs/local_user_setup.md](local_user_setup.md) for first-run setup.

**Using the CLI directly:**

```shell
streamlit run apps/streamlit_app.py
```

Open `http://localhost:8501` in your browser.

- **Sidebar → Registry**: load your CSV/XLSX and preview validation
- **Sidebar → Ingest**: run ingest for selected experiments
- **Datasets tab**: browse registered datasets by name, sample, and run
- **Plot tab**: ad-hoc scatter/line plots across multiple experiments

---

## Service mode

Service mode runs the full lab server stack. A FastAPI handles HTTP requests from the team, a background worker processes ingest jobs, Postgres tracks job state, DuckDB provides the query catalog, and Metabase serves dashboards. All API requests require a bearer token.

### 1. Prerequisites

- Docker and Docker Compose installed
- The repository cloned: `git clone ssh://git@github.com/lucaAyt/mfethuls.git`
- Your registry CSV and raw data accessible to the containers

### 2. Configure `.env`

```shell
cp env_example .env
```

Edit `.env`:

```
MFETHULS_MODE=service

# Paths — these must be accessible inside Docker containers
PATH_TO_DATA=/data/raw
PATH_TO_REGISTRY=/data/registry/experiments_registry.csv
PATH_TO_LOCAL_STORAGE=/data/parquet

# API security — generate a secure token
MFETHULS_API_KEY=your-secret-token-here

# Postgres (used for job queue and metadata)
MFETHULS_POSTGRES_ENABLED=true
MFETHULS_POSTGRES_USER=mfethuls
MFETHULS_POSTGRES_PASSWORD=change-me
MFETHULS_POSTGRES_DB=mfethuls
MFETHULS_POSTGRES_HOST=postgres
MFETHULS_POSTGRES_PORT=5432
```

Generate a secure API key:

```shell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Never commit `.env` to version control — it contains credentials.

### 3. Start the stack

```shell
docker compose up --build
```

Services that start:
- `mfethuls-api` on port 8000 — REST API
- `mfethuls-worker` — background job processor
- `postgres` on port 5432 — job queue and metadata
- `metabase` on port 3000 — BI dashboards
- `caddy` on port 443 — TLS reverse proxy (optional)

Check that everything is healthy:

```shell
curl http://localhost:8000/health
# {"status": "ok"}
```

### 4. Validate your registry

Before starting an ingest, check the registry for errors:

```shell
curl -s http://localhost:8000/registry/preview \
  -H "Authorization: Bearer your-secret-token-here" \
  -F "file=@/local/path/to/experiments_registry.csv" | jq '.summary'
```

```json
{"total": 12, "valid": 11, "invalid": 1}
```

To see which row failed:

```shell
curl -s http://localhost:8000/registry/preview \
  -H "Authorization: Bearer your-secret-token-here" \
  -F "file=@/local/path/to/experiments_registry.csv" \
  | jq '.rows[] | select(.valid == false)'
```

Fix any errors before proceeding. Common causes:
- `instrument_name` not matching a known name from the table in [registry_reference.md](registry_reference.md)
- Missing `name` column value
- Duplicate `name` values within the registry

### 5. Start an ingest job

Upload the registry and start processing:

```shell
curl -s -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer your-secret-token-here" \
  -F "file=@/local/path/to/experiments_registry.csv" \
  | jq .
```

```json
{
  "job_id": "a3f8c1e2d4b567...",
  "status": "queued",
  "job_registry_storage_path": "/app/.mfethuls_registry/job_registry_record_for_a3f8c1e2d4b567.parquet"
}
```

The job is now queued. The worker picks it up within seconds.

### 6. Poll the job

Save the `job_id` and poll until the status is `completed` or `failed`:

```shell
JOB_ID="a3f8c1e2d4b567..."

curl -s http://localhost:8000/jobs/$JOB_ID \
  -H "Authorization: Bearer your-secret-token-here" \
  | jq '{status, progress, message}'
```

```json
{
  "status": "running",
  "progress": 55,
  "message": "reading registry"
}
```

When done:

```json
{
  "status": "completed",
  "progress": 100,
  "message": "ingest completed"
}
```

Check per-experiment results:

```shell
curl -s http://localhost:8000/jobs/$JOB_ID \
  -H "Authorization: Bearer your-secret-token-here" \
  | jq '.datasets[] | {name, status}'
```

```json
[
  {"name": "CL_dsc_001", "status": "persisted"},
  {"name": "CL_tga_001", "status": "persisted"},
  {"name": "CL_rheometer_freq", "status": "skipped"}
]
```

`skipped` means the row had no `instrument_name` set and cannot be parsed yet — it is not an error.

### 7. Browse datasets

List all registered datasets:

```shell
curl -s http://localhost:8000/datasets \
  -H "Authorization: Bearer your-secret-token-here" \
  | jq '.[].name'
```

Fetch rows from a specific dataset (paginated):

```shell
curl -s "http://localhost:8000/dataset/CL_dsc_001_S001_R001?limit=50&offset=0" \
  -H "Authorization: Bearer your-secret-token-here" \
  | jq '{columns: [.columns[].name], row_count: .pagination.returned_rows}'
```

### 8. List previous jobs

If you submitted multiple jobs or need to find an old job ID:

```shell
# List the last 10 completed jobs
curl -s "http://localhost:8000/jobs?status=completed&limit=10" \
  -H "Authorization: Bearer your-secret-token-here" \
  | jq '.[].job_id'
```

### 9. Remove a dataset

If a dataset needs to be re-ingested after a parser fix, remove it from the catalog first:

```shell
curl -s -X DELETE http://localhost:8000/dataset/CL_dsc_001_S001_R001 \
  -H "Authorization: Bearer your-secret-token-here"
```

```json
{"deleted": "CL_dsc_001_S001_R001"}
```

This removes the DuckDB view and catalog entry only. The Parquet file on disk is not deleted. Re-run an ingest to re-register it.

### 10. Connect Metabase

Metabase connects through the Quack gateway which provides read-only SQL access to DuckDB.

1. Open `http://localhost:3000` in your browser
2. Complete the Metabase setup wizard
3. Add a new database connection: **DuckDB** (via the Quack driver)
   - Host: `mfethuls-quack` (internal Docker hostname)
   - Port: `8080` (or as configured in `docker-compose.yml`)
4. Browse tables — each ingested dataset appears as a table named after the experiment (e.g. `CL_dsc_001_S001_R001`)
5. Create questions and dashboards using the normalised column names from [SCHEMA_CONTRACT.md](../SCHEMA_CONTRACT.md)

---

## Common issues

**`instrument_name` not recognised**

The value must exactly match a name from `instrument_params.json`. Run `POST /registry/preview` to see the specific error. Valid names: `dsc`, `dsc_mettler_toledo`, `dsc_perkin_elmer`, `uv_vis`, `uv_insitu`, `rheometer`, `tga`, `nmr`, `ftir`, `sec`, `dma`, `saxs`, `ms`.

**Raw data file not found**

The system walks `PATH_TO_DATA/<instrument_folder>/` to find a file whose stem matches `raw_data_filename` (or `name` if absent). Check that the file exists somewhere inside the instrument folder and that the stem matches exactly (case-sensitive on Linux).

**Job stuck in `running` for a long time**

The default timeout is 30 minutes (`MFETHULS_JOB_TIMEOUT_SECONDS=1800`). For large registries (100+ experiments), increase this. If the job timed out it will appear as `failed` with a timeout message in the `message` field.

**401 Unauthorized on every request**

Check that `MFETHULS_API_KEY` is set in your `.env` and that your request includes `Authorization: Bearer <that-same-value>`. The token is case-sensitive and must match exactly.

**Parquet already exists / `registered` status**

`registered` means the Parquet file already existed from a previous ingest — the worker re-registered the DuckDB view but did not re-parse. To force a re-parse: delete the Parquet file manually and run ingest again.
