# Workflow Tutorial

This tutorial walks through a complete mfethuls workflow from raw files to notebook analysis. By the end you will have ingested three DSC experiments, browsed them in the Streamlit dashboard, and queried the data in a notebook.

**Prerequisites:** completed [local setup](local_setup.md) — `uv` installed, repo cloned, `launch.bat` / `launch.sh` working.

---

## The scenario

You have just run three DSC experiments on two polymer samples. The instrument exported three `.txt` files into your `DSC/` folder:

```
C:\Lab\RawData\
  DSC\
    CL_dsc_001.txt    ← sample S001, first run
    CL_dsc_002.txt    ← sample S002, first run
    CL_dsc_003.txt    ← sample S002, second run (repeat)
```

Your goal: get these into mfethuls, compare the heat flow curves, and extract the peak temperature as a feature for downstream modelling.

---

## Step 1 — Add experiments to the registry

Open your registry CSV (`experiments_template.csv`) in Excel or a text editor and add three rows:

```
name,instrument_name,sample_id,run_id,description,operator
CL_dsc_001,dsc_mettler_toledo,S001,R001,baseline scan,Maria
CL_dsc_002,dsc_mettler_toledo,S002,R001,baseline scan,Maria
CL_dsc_003,dsc_mettler_toledo,S002,R002,repeat — higher ramp rate,Maria
```

Key points:
- `name` must be unique and matches what you'll see in the dashboard and notebooks.
- `instrument_name` must match exactly — see the [registry reference](../reference/registry.md) for the full list.
- `raw_data_filename` is left blank here because the file names match the `name` column. If your instrument auto-generates a different filename, fill that column in.

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

Select `CL_dsc_001`, `CL_dsc_002`, and `CL_dsc_003` from the multiselect (or tick **"Select all"** if these are the only rows), then click **"Ingest"**. A progress bar advances as each experiment is parsed, normalised, and written to Parquet.

If a row has a validation error (unknown instrument name, file not found, etc.), it will surface as an error message after the ingest attempt. Fix the registry CSV and ingest again — already-successful experiments are skipped unless you tick **"Re-parse even if cached"**.

When it finishes:
- Three Parquet files exist under `PATH_TO_LOCAL_STORAGE/dsc_mettler_toledo/<hex_id>/`
- Three views are registered in the DuckDB catalog: `CL_dsc_001_S001_R001`, `CL_dsc_002_S002_R001`, `CL_dsc_003_S002_R002`

> **Service mode:** click **"Sync from OneDrive"** first to pull data from OneDrive, then select experiments and click **"Ingest experiments"**. To validate a registry without ingesting, use `POST /registry/preview` from the API — see [reference/api.md](../reference/api.md).

---

## Step 4 — Browse and plot

Switch to the **Datasets** tab. Your three experiments appear in the list. Select `CL_dsc_001_S001_R001` — a scatter plot of `heat_flow_mW` vs `temperature_C` renders immediately.

Use the axis dropdowns to explore other columns. The toolbar camera button exports the current view as an SVG (editable in Inkscape). The **Export** section below the plot offers a side-by-side SVG and interactive HTML download.

Select multiple datasets and click **"Compare"** to overlay them on the same axes — useful for checking whether `CL_dsc_002` and `CL_dsc_003` agree.

---

## Step 5 — Query in a notebook

Open a Jupyter or Marimo notebook in the same project directory (`.env` is loaded automatically).

### Check what's been ingested

```python
from mfethuls.storage.notebook import list_datasets

list_datasets()
#    experiment_name          table_name              registered_at
# 0  CL_dsc_001        CL_dsc_001_S001_R001   2026-07-22 09:14:01
# 1  CL_dsc_002        CL_dsc_002_S002_R001   2026-07-22 09:14:02
# 2  CL_dsc_003        CL_dsc_003_S002_R002   2026-07-22 09:14:03
```

### Load experiments with the Python API

```python
import mfethuls

cs = mfethuls.load_experiments(["CL_dsc_001", "CL_dsc_002", "CL_dsc_003"])
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

# Stack all three experiments
df = conn.execute("""
    SELECT experiment_name, temperature_C, heat_flow_mW
    FROM "CL_dsc_001_S001_R001"
    UNION ALL
    SELECT experiment_name, temperature_C, heat_flow_mW
    FROM "CL_dsc_002_S002_R001"
    UNION ALL
    SELECT experiment_name, temperature_C, heat_flow_mW
    FROM "CL_dsc_003_S002_R002"
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
