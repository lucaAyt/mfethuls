# Data Scientist Guide — Querying and Analysing Lab Data

This guide covers every way to access mfethuls data programmatically: the Python API, DuckDB SQL, Postgres metadata, and direct Parquet reads. It is written for data scientists who want to build models, run statistical analysis, or do exploratory work in notebooks — not for experimentalists running ingests.

---

## Where the data lives

Three stores, each with a distinct role:

```
┌──────────────────────────────────────────────────────────────────┐
│  DuckDB  (mfethuls.duckdb)                                       │
│  Measurement data — the actual numbers from instruments          │
│                                                                  │
│  dataset_registry          → catalogue of all datasets           │
│  VIEW CL_dsc_001_S001_R001 → SELECT * reads the Parquet file     │
│  VIEW CL_tga_002_S002_R001 → …                                   │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Postgres  (mfethuls DB)                                         │
│  Metadata — who, what, when, how                                 │
│                                                                  │
│  datasets table →  experiment_name, sample_id, run_id,          │
│                    instrument_name, instrument_model,            │
│                    measurement_profile, rows, cols,              │
│                    storage_path, provenance (JSONB)              │
│  ingest_jobs   →  full audit trail of every ingest run          │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Parquet files  (/data/mfethuls_storage/<instrument>/<hex_id>/)  │
│  Source of truth — DuckDB views read directly from these         │
│  Can be read with pd.read_parquet() or duckdb without the DB     │
└──────────────────────────────────────────────────────────────────┘
```

**Rule of thumb:**
- Need numbers (temperatures, intensities, counts)? → DuckDB or Parquet
- Need to filter or discover by sample, instrument, date? → Postgres
- Building a model across many experiments? → Join Postgres (filter) + DuckDB (load data)

---

## Remote access — connecting from your laptop

### Postgres

Postgres is accessible directly over Tailscale — port 5432 is exposed by the Droplet:

```python
PG_URL = "postgresql://mfethuls:<password>@100.x.x.x:5432/mfethuls"
```

### DuckDB

DuckDB is a **file**, not a server. You cannot connect to it remotely the way you can Postgres. Options:

**Option A — Mount the volume over SSHFS (Linux/macOS)**

```shell
brew install macfuse sshfs     # macOS
sudo apt install sshfs         # Ubuntu

sshfs root@100.x.x.x:/mnt/mfethuls-data ~/mfethuls-data -o follow_symlinks
```

Then connect:

```python
import duckdb
conn = duckdb.connect("~/mfethuls-data/mfethuls.duckdb", read_only=True)
```

**Option B — Run the notebook on the Droplet**

```shell
ssh root@100.x.x.x
cd /opt/mfethuls
docker compose exec streamlit bash
jupyter notebook --ip=0.0.0.0 --no-browser
```

Then tunnel to port 8888 via SSH and open in your browser.

**Option C — REST API for data rows + Postgres for metadata (no file access needed)**

```python
import requests
import pandas as pd

API_URL = "http://100.x.x.x:8000"
API_KEY = "<your-api-key>"
headers = {"Authorization": f"Bearer {API_KEY}"}

def fetch_dataset(name: str, limit: int = 10_000) -> pd.DataFrame:
    r = requests.get(f"{API_URL}/dataset/{name}", headers=headers, params={"limit": limit})
    r.raise_for_status()
    payload = r.json()
    cols = [c["name"] for c in payload["columns"]]
    return pd.DataFrame(payload["rows"], columns=cols)

df = fetch_dataset("CL_dsc_001_S001_R001")
```

---

## Install

```shell
pip install "mfethuls[notebook,viz]"
# or with uv:
uv pip install "mfethuls[notebook,viz]"
```

---

## Access pattern 1 — Python API (simplest, works locally or remotely)

The Python API handles registry loading and data retrieval in one call. Works in both local mode (files on disk) and service mode (files on the Droplet volume).

```python
import os
import mfethuls

# Point at data (local or SSHFS mount)
os.environ["PATH_TO_DATA"] = "/path/to/data"
os.environ["PATH_TO_REGISTRY"] = "/path/to/experiments_template.csv"
os.environ["MFETHULS_DUCKDB_PATH"] = "/path/to/mfethuls.duckdb"
```

### Load specific experiments

```python
cs = mfethuls.load_experiments(["CL_dsc_001", "CL_dsc_002", "CL_dsc_003"])

# Tidy long-format DataFrame — one row per measurement point
df = cs.to_dataframe()
print(df.columns.tolist())
# ['comparison_label', 'temperature_C', 'heat_flow_mW', ...,
#  'experiment_name', 'sample_id', 'run_id', 'instrument_name']

df.groupby("experiment_name")["heat_flow_mW"].describe()
```

### Load all experiments for a sample

```python
cs = mfethuls.load_samples(
    ["S001", "S002"],
    registry_path="/path/to/experiments_template.csv"
)
df = cs.to_dataframe()
```

### Plot directly

```python
mfethuls.plot_experiments(
    cs,
    x="temperature_C",
    y="heat_flow_mW",
)
```

---

## Access pattern 2 — DuckDB SQL (full SQL on measurement data)

Use DuckDB when you need aggregations, joins across experiments, or want to build feature vectors with SQL.

```python
import duckdb

conn = duckdb.connect("/path/to/mfethuls.duckdb", read_only=True)
```

### Discover available datasets

```python
registry = conn.execute("SELECT * FROM dataset_registry ORDER BY registered_at DESC").df()
print(registry[["table_name", "experiment_name", "registered_at"]])
```

### Query a single experiment

```python
df = conn.execute('SELECT * FROM "CL_dsc_001_S001_R001"').df()
```

### Aggregate across experiments dynamically

```python
# Get all DSC view names from the registry
dsc_views = conn.execute("""
    SELECT table_name, experiment_name
    FROM dataset_registry
    WHERE experiment_name LIKE 'CL_dsc%'
""").df()

# Stack them into one DataFrame
frames = []
for _, row in dsc_views.iterrows():
    df = conn.execute(f"""
        SELECT
            '{row["experiment_name"]}' AS experiment_name,
            temperature_C,
            heat_flow_mW
        FROM "{row["table_name"]}"
    """).df()
    frames.append(df)

combined = pd.concat(frames, ignore_index=True)
```

### Build feature vectors for modelling

```python
# Example: peak heat flow per experiment as a feature
features = conn.execute("""
    SELECT experiment_name, MAX(heat_flow_mW) AS peak_heat_flow
    FROM (
        SELECT 'CL_dsc_001_S001_R001' AS experiment_name, temperature_C, heat_flow_mW
        FROM "CL_dsc_001_S001_R001"
        UNION ALL
        SELECT 'CL_dsc_002_S001_R001', temperature_C, heat_flow_mW
        FROM "CL_dsc_002_S001_R001"
    )
    GROUP BY experiment_name
""").df()
```

For a large number of experiments, build the UNION ALL dynamically from the registry query above.

### Query Parquet directly (no DuckDB file needed)

```python
# Useful if the DuckDB file is unavailable but you have the Parquet path from Postgres
df = conn.execute("""
    SELECT * FROM read_parquet('/path/to/mfethuls_storage/DSC/<hex_id>/CL_dsc_001.parquet')
""").df()

# Or scan an entire instrument folder at once
df = conn.execute("""
    SELECT * FROM read_parquet('/path/to/mfethuls_storage/DSC/**/*.parquet', hive_partitioning=false)
""").df()
```

---

## Access pattern 3 — Postgres metadata

Use Postgres for discovery and filtering — find the right experiments before loading data.

```python
from mfethuls.storage.notebook import list_datasets
import pandas as pd

PG_URL = "postgresql://mfethuls:<password>@100.x.x.x:5432/mfethuls"

# All datasets as a DataFrame
meta = list_datasets(PG_URL, limit=1000)
print(meta.columns.tolist())
# ['id', 'experiment_id', 'sample_id', 'run_id', 'experiment_name',
#  'instrument_name', 'instrument_type', 'instrument_model',
#  'rows', 'cols', 'measurement_profile', 'schema_version',
#  'storage_path', 'provenance', 'created_at', ...]
```

### Filter by instrument

```python
dsc_meta = meta[meta["instrument_name"].str.startswith("dsc")]
tga_meta = meta[meta["instrument_name"] == "tga"]
```

### Filter by sample

```python
sample_meta = meta[meta["sample_id"].isin(["S001", "S002"])]
```

### Raw SQL via SQLAlchemy (for complex queries)

```python
from sqlalchemy import create_engine, text

engine = create_engine(PG_URL)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT experiment_name, instrument_name, sample_id, run_id, rows, measurement_profile
        FROM datasets
        WHERE instrument_name = 'dsc_mettler_toledo'
          AND sample_id = 'S001'
        ORDER BY created_at DESC
    """))
    df = pd.DataFrame(result.mappings().all())
```

### Inspect the ingest audit trail

```python
with engine.connect() as conn:
    jobs = conn.execute(text("""
        SELECT job_id, status, created_at, updated_at,
               jsonb_array_length(datasets) AS experiment_count
        FROM ingest_jobs
        ORDER BY created_at DESC
        LIMIT 20
    """))
    pd.DataFrame(jobs.mappings().all())
```

---

## Access pattern 4 — Joining metadata + measurement data

The most powerful pattern for model building: use Postgres to select the right experiments, then load their data via DuckDB or the API.

```python
from mfethuls.storage.notebook import list_datasets
import mfethuls
import duckdb
import pandas as pd

PG_URL  = "postgresql://mfethuls:<password>@100.x.x.x:5432/mfethuls"
DDB_PATH = "/path/to/mfethuls.duckdb"

# Step 1 — Discover experiments of interest via Postgres
meta = list_datasets(PG_URL, limit=1000)
target = meta[
    (meta["instrument_name"] == "dsc_mettler_toledo") &
    (meta["sample_id"].isin(["S001", "S002", "S003"]))
]

# Step 2 — Load measurement data for those experiments
conn = duckdb.connect(DDB_PATH, read_only=True)
registry = conn.execute("SELECT table_name, experiment_name FROM dataset_registry").df()

# Only load experiments that are both in Postgres metadata AND in DuckDB
available = set(registry["experiment_name"])
experiment_names = [n for n in target["experiment_name"] if n in available]

frames = []
for _, row in registry[registry["experiment_name"].isin(experiment_names)].iterrows():
    df = conn.execute(f'SELECT *, \'{row["experiment_name"]}\' AS experiment_name FROM "{row["table_name"]}"').df()
    frames.append(df)

measurements = pd.concat(frames, ignore_index=True)

# Step 3 — Join with metadata for labels, grouping keys etc.
enriched = measurements.merge(
    target[["experiment_name", "sample_id", "run_id", "instrument_model", "measurement_profile"]],
    on="experiment_name",
    how="left"
)

print(enriched.shape)
print(enriched.groupby(["sample_id", "measurement_profile"])["heat_flow_mW"].describe())
```

---

## Column reference by instrument

Each instrument produces a normalised set of columns after ingest. The canonical names are defined in `SCHEMA_CONTRACT.md` at the repo root. Key examples:

| Instrument | Key columns |
|---|---|
| DSC | `temperature_C`, `heat_flow_mW`, `time_s` |
| TGA | `temperature_C`, `mass_mg`, `mass_pct`, `time_s` |
| FTIR | `wavenumber_cm`, `absorbance`, `transmittance` |
| UV-Vis | `wavelength_nm`, `absorbance` |
| Rheometer | `angular_frequency_rad_s`, `storage_modulus_Pa`, `loss_modulus_Pa`, `tan_delta` |
| SEC | `elution_volume_mL`, `signal_mV`, `molecular_weight_Da` |
| NMR | `ppm`, `intensity` |
| DMA | `temperature_C`, `frequency_Hz`, `storage_modulus_MPa`, `tan_delta` |

All datasets also carry `experiment_name`, `experiment_id` (internal hex), `sample_id`, `run_id` from the registry.

---

## Tips for model building

**Normalise before concatenating** — instruments report in different units even within the same type. Check `measurement_profile` from Postgres — it tells you which experimental protocol was used and whether signals are directly comparable.

**Use `experiment_name` as the join key** — it is stable across re-ingests, human-readable, and present in both DuckDB views and Postgres metadata. `experiment_id` is an internal hex and not needed outside the storage layer.

**Filter in Postgres, load in DuckDB** — Postgres is cheap to query for discovery; DuckDB loads potentially large Parquet files. Do not load all datasets and filter in Python.

**Re-ingest is safe** — the `refresh=True` flag on ingest re-parses and overwrites Parquet files. DuckDB views and Postgres metadata are updated in place. Existing DataFrames you've already loaded are not affected.
