# Workflow Tutorial

This tutorial walks through a complete mfethuls workflow from raw files to notebook analysis. By the end you will have ingested two DSC experiments, browsed them in the Streamlit dashboard, and queried the data in a notebook.

**Prerequisites:** completed [local setup](local_setup.md) — `uv` installed, repo cloned, `launch.bat` / `launch.sh` working.

> **Follow along with example data:** in the app, press **Try the example** on the welcome page (or run `from mfethuls.examples import create_workspace; create_workspace(register_all=True)` and point `PATH_TO_DATA` and `PATH_TO_REGISTRY` at the `data/` folder and registry it creates in `~/mfethuls-example`). The files used in this tutorial are included.

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

> **Shortcut:** once the app is running (step 2), the **Ingest** section in the sidebar lists raw data that is not in the registry yet. **Review & register** proposes the rows (instrument, file name, run) and only asks for what the files can't tell, such as the sample. See [Registering new data from the app](../reference/registry.md#registering-new-data-from-the-app). The steps below show the manual route.

Open `experiments_template.csv` (included in the repo root) in Excel. Delete the placeholder rows and add your two experiments:

```
name,instrument_name,sample_id,run_id,raw_data_filename,description,operator
LB_dsc_001,dsc,S001,R001,poly1,DSC run — polymer 1,LB
LB_dsc_002,dsc,S002,R001,poly2,DSC run — polymer 2,LB
```

Key points:
- `name` must be unique — it's what you'll see in the dashboard and notebooks. A lab-prefix + instrument + run number convention (`LB_dsc_001`) makes the list easy to scan.
- `instrument_name` must match exactly — see the [registry reference](../reference/registry.md) for the full list.
- `raw_data_filename` is the file stem. Use it when the filename differs from `name` (as here: file is `poly1.txt`, registry entry is `LB_dsc_001`).

Save the CSV. That's the only file you touch before ingesting.

---

## Step 2 — Launch the app

**Windows:** double-click `launch.bat`.

**macOS / Linux:**
```shell
bash launch.sh
```

Streamlit opens at `http://localhost:8501`. On first launch, press **Get started** to choose your data folder; the registry is made for you as `registry.xlsx` in it. Change either later under **⚙ Settings** → **Data folder and registry**. From then on, a getting-started checklist (and a compact tracker at the top of the sidebar) shows the next step.

---

## Step 3 — Select and ingest

In the Streamlit sidebar, expand **Ingest**. It lists the experiments of the registry you chose.

Select `LB_dsc_001` and `LB_dsc_002` from the multiselect (or tick **"Select all"** if these are the only rows), then click **"Ingest"**. A progress bar advances as each experiment is parsed, normalised, and written to Parquet.

If an experiment cannot be ingested (unknown instrument name, file not found, files that do not read as that instrument's data, …), it is listed with the reason and nothing is stored for it. Fix the registry and ingest again. **Ingest** in the app always reads the files again, so a corrected file or instrument is picked up (in Python, pass `refresh=True`).

When it finishes:
- Two Parquet files exist under `PATH_TO_LOCAL_STORAGE/dsc/<hex_id>/`
- Two views are registered in the DuckDB catalog: `LB_dsc_001_S001_R001`, `LB_dsc_002_S002_R001`

---

## Step 4 — Browse and plot

In the sidebar, expand **Datasets** and pick `LB_dsc_001` and `LB_dsc_002` in **"Select experiments to plot"** (each is listed with its sample and run; with several instruments, the **Instrument** buttons above narrow the list). The main page lists them with their instrument, sample and run, then shows row counts, a preview table and the **Plot** section.

- Choose the **X axis** (`temperature_C`) and **Y axis** (`heat_flow_mW`). Lines are coloured by experiment, and every data point is drawn. **Style by** next to **Colour by** tells a second column apart by line style (or marker shape in a scatter plot), e.g. colour by experiment and style by sample.
- Or switch on **Built-in instrument plot**: the DSC plot with one colour per heating/cooling segment and one line style per experiment.
- **Filter**, at the top of **Plot** next to the built-in plot toggle, plots only some rows: choose a column (those worth filtering on, such as the DSC segments `Heating_1`, `Cooling_1`, …, come first, and the button names the first, e.g. **Filter by profile**) and the values to keep. While it is on, the button is coloured and names what is kept (**Filter: Heating_1**), and a line under the chart says how many rows are shown, with **Clear**. **Log X**, **Log Y** and **Invert X** sit next to **Axis limits** above the chart, and with several experiments **Layout** draws them **Together**, **Offset** (shifted apart, with a spacing slider) or in **Panels** that share the x-axis, in both plots. **Normalise**, next to **Filter**, scales each experiment (max = 1, 0 to 1 or area = 1) to compare curves by their shape; the data itself is not changed.
- Zoom by dragging a box, and double-click to reset.

The toolbar above the chart has an **Axis limits** toggle (it opens min/max fields above the chart, so the axes stay visible) and a **Download** menu on the right for the figure as a vector **SVG** (publication style, editable in Inkscape, using your axis limits) or as interactive **HTML**. See the [plotting guide](plotting.md#streamlit-dashboard) for colour scales and data size.

---

## Step 5 — Query in a notebook

mfethuls ships a Marimo tutorial that walks through all the patterns below interactively, on its own copy of the example data. Open it from the app's welcome page (**Use it from Python**) or with:

```shell
mfethuls-tutorial
```

Or open a Jupyter or Marimo notebook of your own: mfethuls uses the folders you chose in the app (or set in `.env`). To point a notebook elsewhere for its session, call `mfethuls.settings.use_folders(data_root=..., registry_path=...)`.

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
fig, ax = mfethuls.plot_experiments(cs)                  # heat flow vs temperature, both runs overlaid
fig.savefig("dsc_comparison.svg", bbox_inches="tight")

mfethuls.plot_experiments(cs, backend="plotly")          # interactive version
```

### Or go direct with DuckDB

```python
import duckdb
from mfethuls.storage import catalog_path

conn = duckdb.connect(catalog_path(), read_only=True)

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

---

## What you now have

- A reproducible registry entry for each experiment
- Normalised Parquet files that can be read by anything (`pd.read_parquet`, DuckDB, Spark)
- DuckDB views for instant SQL access
- A reusable notebook pattern for feature extraction

From here, add more experiments to the registry and re-run ingest — existing datasets are untouched unless you pass `refresh=True`. The catalog grows incrementally.
