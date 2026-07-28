# Workflow Tutorial

This tutorial walks through a complete mfethuls workflow from raw files to notebook analysis. By the end you will have ingested two DSC experiments, browsed them in the Streamlit dashboard, and queried the data in a notebook.

**Prerequisites:** completed [local setup](local_setup.md) — `uv` installed, repo cloned, `launch.bat` / `launch.sh` working.

> **Follow along with example data:** point `PATH_TO_DATA` at `examples/data/` and `PATH_TO_REGISTRY` at `examples/experiments_registry.csv` (both at the repo root) when the setup wizard asks — the files used in this tutorial are included.

---

## The scenario

You have just run two DSC experiments on two polymer samples. The instrument exported two `.txt` files into your `DSC/` folder:

```
PATH_TO_DATA\
  DSC\
    poly1.txt    ← sample S001, first run
    poly2.txt    ← sample S002, first run
```

Your goal: get these into mfethuls, compare the heat flow curves, and extract the peak temperature as a feature for downstream modelling.

---

## Step 1 — Add experiments to the registry

Open `experiments_template.csv` (included in the repo root) in Excel. Delete the placeholder rows and add your two experiments:

```
name,instrument_name,sample_id,run_id,raw_data_filename,description,operator
LB_dsc_001,dsc_mettler_toledo,S001,R001,poly1,DSC run — polymer 1,LB
LB_dsc_002,dsc_mettler_toledo,S002,R001,poly2,DSC run — polymer 2,LB
```

Key points:
- `name` must be unique — it's what you'll see in the dashboard and notebooks. A lab-prefix + instrument + run number convention (`LB_dsc_001`) makes the list easy to scan.
- `instrument_name` must match exactly — see the [registry reference](../reference/registry.md) for the full list.
- `raw_data_filename` is the file stem. Use it when the filename differs from `name` (as here: file is `poly1.txt`, registry entry is `LB_dsc_001`).

Save the CSV. That's the only file you touch before ingesting.

> **Service mode:** instead of editing locally, update the shared registry on OneDrive. Then use the Ingest sidebar → "Sync from OneDrive" before proceeding.

---

## Step 2 — Launch the app

**Windows:** double-click `launch.bat`.

**macOS / Linux:**
```shell
bash launch.sh
```

Streamlit opens at `http://localhost:8501`. On first launch the setup wizard will have asked for your paths — if you need to change them, edit `.env` directly or delete it to re-run the wizard.

---

## Step 3 — Select and ingest

In the Streamlit sidebar, expand **Ingest**. Enter the path to your registry CSV in the text input — the experiment list loads automatically from the file.

Select `LB_dsc_001` and `LB_dsc_002` from the multiselect (or tick **"Select all"** if these are the only rows), then click **"Ingest"**. A progress bar advances as each experiment is parsed, normalised, and written to Parquet.

If a row has a validation error (unknown instrument name, file not found, etc.), it will surface as an error message after the ingest attempt. Fix the registry CSV and ingest again — already-successful experiments are skipped unless you tick **"Re-parse even if cached"**.

When it finishes:
- Two Parquet files exist under `PATH_TO_LOCAL_STORAGE/dsc_mettler_toledo/<hex_id>/`
- Two views are registered in the DuckDB catalog: `LB_dsc_001_S001_R001`, `LB_dsc_002_S002_R001`

> **Service mode:** click **"Sync from OneDrive"** first to pull data from OneDrive, then select experiments and click **"Ingest experiments"**. To validate a registry without ingesting, use `POST /registry/preview` from the API — see [reference/api.md](../reference/api.md).

---

## Step 4 — Browse and plot

Switch to the **Datasets** tab. Your two experiments appear in the list. Select `LB_dsc_001_S001_R001` — a scatter plot of `heat_flow_mW` vs `temperature_C` renders immediately.

Use the axis dropdowns to explore other columns. The toolbar camera button exports the current view as an SVG (editable in Inkscape). The **Export** section below the plot offers a side-by-side SVG and interactive HTML download.

Select both datasets and click **"Compare"** to overlay them on the same axes.

---

## Step 5 — Query in a notebook

The repo includes `notebooks/local_tutorial.py` — a Marimo notebook that walks through all the patterns below interactively. Open it with:

```shell
uv run --extra notebook marimo edit notebooks/local_tutorial.py
```

Or open a Jupyter or Marimo notebook of your own in the same project directory (`.env` is loaded automatically).

### Check what's been ingested

```python
from mfethuls.storage.notebook import list_datasets

list_datasets()
#    experiment_name       table_name               registered_at
# 0  LB_dsc_001      LB_dsc_001_S001_R001   2026-07-28 09:14:01
# 1  LB_dsc_002      LB_dsc_002_S002_R001   2026-07-28 09:14:02
```

### Load experiments with the Python API

```python
import mfethuls

cs = mfethuls.load_experiments(["LB_dsc_001", "LB_dsc_002"])
df = cs.to_dataframe()

print(df.columns.tolist())
# ['temperature_C', 'heat_flow_mW', 'time_s', 'experiment_name', 'sample_id', 'run_id', ...]

df.groupby("experiment_name")["heat_flow_mW"].describe()
```

### Plot

```python
mfethuls.plot_experiments(cs, x="temperature_C", y="heat_flow_mW")
```

### Or go direct with DuckDB

```python
import duckdb
import os

conn = duckdb.connect(os.environ["MFETHULS_DUCKDB_PATH"], read_only=True)

df = conn.execute("""
    SELECT experiment_name, temperature_C, heat_flow_mW
    FROM "LB_dsc_001_S001_R001"
    UNION ALL
    SELECT experiment_name, temperature_C, heat_flow_mW
    FROM "LB_dsc_002_S002_R001"
""").df()

# Extract peak heat flow per experiment
features = df.groupby("experiment_name")["heat_flow_mW"].min().reset_index()
features.columns = ["experiment_name", "peak_heat_flow_mW"]
print(features)
```

> **Service mode:** replace the DuckDB path with a Postgres URL for metadata queries, or mount the block volume over SSHFS to connect to DuckDB directly. See [data analysis guide](data_analysis.md) for the full options.

---

## What you now have

- A reproducible registry entry for each experiment
- Normalised Parquet files that can be read by anything (`pd.read_parquet`, DuckDB, Spark)
- DuckDB views for instant SQL access
- A reusable notebook pattern for feature extraction

From here, add more experiments to the registry and re-run ingest — existing datasets are untouched unless you pass `refresh=True`. The catalog grows incrementally.
