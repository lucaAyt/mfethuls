# Data Analysis Guide — Querying Lab Data in Notebooks

This guide covers every way to access mfethuls data programmatically: the Python API, DuckDB SQL and direct Parquet reads. Written for data scientists doing model building, statistical analysis, or exploratory work in notebooks — not for experimentalists running ingests.

---

## Where the data lives

```
┌──────────────────────────────────────────────────────────────────┐
│  DuckDB  (mfethuls.duckdb)                                       │
│  The catalog and one view per dataset                            │
│                                                                  │
│  dataset_registry          → catalogue of all datasets           │
│  VIEW CL_dsc_001_S001_R001 → SELECT * reads the Parquet file     │
│  VIEW CL_tga_002_S002_R001 → …                                   │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Parquet files  (PATH_TO_LOCAL_STORAGE/<instrument>/<hex_id>/)   │
│  Source of truth — DuckDB views read directly from these         │
│  Can be read with pd.read_parquet() or duckdb without the DB     │
└──────────────────────────────────────────────────────────────────┘
```

**Rule of thumb:** find experiments in the catalog (`list_datasets()` or the `dataset_registry` table), then load their numbers through the Python API or the DuckDB views.

---

## Install

```shell
pip install "mfethuls[notebook,viz]"
# or with uv:
uv pip install "mfethuls[notebook,viz]"
```

The `notebook` extra installs Marimo, which the tutorial uses. If you prefer Jupyter, install it yourself (`pip install jupyterlab`): the Python API and DuckDB patterns below work the same in both.

---

## Check what's been ingested

```python
from mfethuls.storage.notebook import list_datasets

list_datasets()[["experiment_name", "instrument_name", "sample_id", "registered_at"]]
```

---

## Access pattern 1 — Python API (simplest)

The Python API handles registry loading and data retrieval in one call.

mfethuls uses the data folder and registry chosen in the app (**Get started** / **⚙ Settings**), or set in `.env`. To use other folders in a notebook, for this session only:

```python
import mfethuls
from mfethuls.settings import use_folders

use_folders(data_root="/path/to/data", registry_path="/path/to/registry.xlsx")
```

(Setting `os.environ` does not work once folders are saved in the app: saved folders take precedence.)

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

### Inspect the registry

Both functions read the registry file on each call, so edits to it apply straight away. To look at it yourself, or to reuse one copy across calls:

```python
registry = mfethuls.Registry.load()      # PATH_TO_REGISTRY, or pass a path
registry.frame                           # the spreadsheet as read
registry.problems                        # rows that were skipped or have warnings, and why
[exp.name for exp in registry.for_samples(["S001"])]

cs = mfethuls.load_experiments(["CL_dsc_001"], registry=registry)
```

Descriptions and extra columns always come from the current registry, also for data loaded from storage.

### Plot directly

```python
fig, ax = mfethuls.plot_experiments(cs)                  # Matplotlib, publication style
fig = mfethuls.plot_experiments(cs, backend="plotly")    # interactive
```

The plot is chosen per instrument (heat flow vs temperature for DSC, a spectrum for FTIR, …). See the [plotting guide](plotting.md) for comparison modes, labels and units, and saving figures.

---

## Access pattern 2 — DuckDB SQL (full SQL on measurement data)

Use DuckDB when you need aggregations, joins across experiments, or want to build feature vectors with SQL.

```python
import duckdb

from mfethuls.storage import catalog_path

conn = duckdb.connect(catalog_path(), read_only=True)
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
# Useful if the DuckDB file is unavailable but you know the Parquet path
df = conn.execute("""
    SELECT * FROM read_parquet('/path/to/mfethuls_storage/DSC/<hex_id>/CL_dsc_001.parquet')
""").df()

# Or scan an entire instrument folder at once
df = conn.execute("""
    SELECT * FROM read_parquet('/path/to/mfethuls_storage/DSC/**/*.parquet', hive_partitioning=false)
""").df()
```

---

---

## Column reference by instrument

Each instrument produces a normalised set of columns after ingest. The canonical names are defined in [docs/reference/schema.md](../reference/schema.md).

| Instrument | Key columns |
|---|---|
| DSC | `temperature_C`, `heat_flow_mW` and/or `heat_flow_W_g`, `time_s`, `sample_mass_mg` (when the file states it) |
| TGA | `temperature_C`, `mass_mg`, `mass_pct` (% of initial mass), `time_s` |
| Tensile tester | `strain_mm` or `strain_pct`, `shear_stress_mpa` or `stress_mpa`, `sheet`, `test_date` |
| FTIR | `wavenumber_cm_inv`, `absorbance_a_u`, `transmittance_pct` |
| UV-Vis | `wavelength_nm`, `absorbance_a_u` |
| Rheometer | `angular_frequency_rad_s`, `storage_modulus_pa`, `loss_modulus_pa`, `tan_delta` |
| SEC | `retention_time_min`, `detector_response_a_u`, `detector_name` |
| NMR | `chemical_shift_ppm`, `intensity_a_u`, `nucleus`, `solvent` (select one with `data[data["nucleus"] == "13C"]`) |
| DMA | `temperature_C`, `frequency_hz`, `storage_modulus_mpa`, `loss_modulus_mpa`, `tan_delta` |

All datasets also carry `experiment_name`, `experiment_id` (internal hex, system-assigned), `sample_id`, `run_id` from the registry.

---

## Tips for model building

**Normalise before concatenating** — instruments report in different units even within the same type. Check which quantity each run swept (DMA and rheometer: `mfethuls.plotting.sweeps.sweep_axis`) and its units before comparing signals.

**Use `experiment_name` as the join key** — it is human-readable and present in the catalog and the data. `experiment_id` is an internal hex assigned by the system and not needed outside the storage layer.

**Filter in the catalog, then load** — the catalog is cheap to query for discovery; loading reads potentially large Parquet files. Do not load all datasets and filter in Python.

**Re-ingest is safe** — the `refresh=True` flag on ingest re-parses and overwrites Parquet files. DuckDB views and the catalog are updated in place. Existing DataFrames you've already loaded are not affected.
