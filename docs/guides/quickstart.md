# Quickstart

Pick the path that matches how you're accessing mfethuls:

- **[Path A](#path-a--team-member-with-tailscale-access)** — your team has a shared lab server and you want to browse data in the browser. No Python required.
- **[Path B](#path-b--local-python-user)** — you want to run everything on your own machine.

---

## Path A — Team member with Tailscale access

You need: Tailscale installed and connected to the lab tailnet. That's it.

1. **Open the dashboard** in your browser:
   ```
   http://100.x.x.x:8501
   ```
   (Replace `100.x.x.x` with the Tailscale IP your admin gave you.)

2. **Sync data from OneDrive** — Ingest sidebar → click **"Sync from OneDrive"**. Wait for the spinner to finish. The experiment list populates automatically.

3. **Select experiments** — tick the ones you want to ingest in the multiselect.

4. **Ingest** — click **"Ingest experiments"**. A progress bar runs while the data is parsed. Completed experiments appear in the Datasets tab.

5. **Browse and plot** — Datasets tab → select a dataset → tweak the plot → download as SVG (or interactive HTML).

**No install, no Python, no config.**

---

## Path B — Local Python user

You have raw data files and a registry CSV on your machine.

### Install

```shell
pip install "mfethuls[viz,notebook]"
```

Or with uv (faster):
```shell
uv pip install "mfethuls[viz,notebook]"
```

### Configure paths

Copy the example env file and fill in your paths:

```shell
cp env_example .env
```

Edit `.env`:
```
MFETHULS_MODE=local
PATH_TO_DATA=/path/to/raw/instrument/data
PATH_TO_REGISTRY=/path/to/experiments_template.csv
PATH_TO_LOCAL_STORAGE=/path/to/parquet/output
```

`PATH_TO_DATA` should be the root folder containing instrument subfolders (`DSC/`, `TGA/`, etc.).

`experiments_template.csv` in the repo root is a pre-filled starting point — open it in Excel and replace the placeholder rows with your experiments.

### Launch

**Windows:** double-click `launch.bat`.

**macOS / Linux:**
```shell
bash launch.sh
```

The Streamlit dashboard opens at `http://localhost:8501`. From there, the flow is the same as Path A (steps 3–5 above), minus the sync step.

### Python API

For notebooks, import directly:

```python
import mfethuls

cs = mfethuls.load_experiments(["CL_dsc_001", "CL_dsc_002"])
df = cs.to_dataframe()   # tidy long-format DataFrame
```

For a complete notebook guide including DuckDB SQL queries and model-building patterns, see [docs/guides/data_analysis.md](data_analysis.md).

---

## Next steps

| If you want to… | Read |
|---|---|
| See the full workflow with a concrete example | [docs/guides/workflow.md](workflow.md) |
| Understand the registry format (columns, instruments, profiles) | [docs/reference/registry.md](../reference/registry.md) |
| Deploy to a shared lab server | [docs/guides/cloud_deployment.md](cloud_deployment.md) |
| Query data in notebooks | [docs/guides/data_analysis.md](data_analysis.md) |
| See all REST API endpoints | [docs/reference/api.md](../reference/api.md) |
