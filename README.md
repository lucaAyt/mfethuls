# mfethuls

From scattered instrument files to analysis-ready data. mfethuls is a Python framework that reads, cleans and organises experimental data: raw instrument exports are ingested against an experiment registry, normalised to a canonical schema and stored as traceable, queryable Parquet datasets. Use it from the app (`mfethuls-app`, no code needed), the command line (`mfethuls`), notebooks, or SQL. Experimentalists get consistent, comparable data and publication-ready figures; data scientists get harmonised data from every instrument to build features and models on.

[![PyPI](https://img.shields.io/pypi/v/mfethuls)](https://pypi.org/project/mfethuls/)
[![Python](https://img.shields.io/pypi/pyversions/mfethuls)](https://pypi.org/project/mfethuls/)
[![Tests](https://github.com/lucaAyt/mfethuls/actions/workflows/tests.yml/badge.svg)](https://github.com/lucaAyt/mfethuls/actions/workflows/tests.yml)
[![License](https://img.shields.io/pypi/l/mfethuls)](https://github.com/lucaAyt/mfethuls/blob/master/LICENSE)
---

## Instrument support

| Instrument | Models |
|---|---|
| DSC | Generic, Mettler Toledo (current and older STARe export), Perkin Elmer |
| TGA | Generic |
| FTIR | Bruker |
| UV-Vis | Shimadzu, Ocean Optics Flame (in-situ) |
| Fluorescence | Ocean Optics Flame (in-situ) |
| NMR | Bruker |
| Rheometer | Anton Paar |
| DMA | TA Q800 |
| SEC | Agilent |
| SAXS | Anton Paar |
| MS | Bruker |
| Tensile tester | ZwickRoell testXpert (Excel) |

Other instruments that export text or Excel files can be added from the app without code: see [adding an instrument](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/instruments.md).

Each instrument's reader normalises raw exports to a [canonical column schema](https://github.com/lucaAyt/mfethuls/blob/master/docs/reference/schema.md) — same column names and units regardless of instrument model.

---

## Install

**Not a Python user?** Follow [docs/guides/local_setup.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/local_setup.md): one small tool (`uv`) installs everything, Python included, and the app then starts with a double-click.

**With pip** (Python 3.11 or newer): install mfethuls in a [virtual environment](https://docs.python.org/3/tutorial/venv.html), so it and its dependencies stay separate from your other Python projects:

```shell
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install "mfethuls[viz,notebook]"
```

**With [uv](https://docs.astral.sh/uv/)**, which installs Python and creates the environment for you, and makes the `mfethuls`, `mfethuls-app` and `mfethuls-tutorial` commands available everywhere:

```shell
# 1. Install uv (once)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
curl -LsSf https://astral.sh/uv/install.sh | sh                                     # macOS/Linux

# 2. Install mfethuls (open a new terminal first, so the uv command is found)
uv tool install "mfethuls[viz,notebook]"
```

Keep both extras: `viz` runs the app, `notebook` opens the tutorial (**Use it from Python** on the app's welcome page).

The latest development version: `pip install "mfethuls[viz,notebook] @ git+https://github.com/lucaAyt/mfethuls.git"`. The extras:

| Extra | Installs | Use when |
|---|---|---|
| `viz` | Plotly, Matplotlib, Kaleido, Streamlit | The app or notebook plotting |
| `notebook` | Marimo, Matplotlib, Plotly, seaborn | Interactive notebooks with plotting (the tutorial is a Marimo notebook) |

---

## Getting started

No Docker, no database, no server. Start the app:

```shell
mfethuls-app
```

The welcome page offers three ways in:

- **Get started**: choose your data folder (one subfolder per instrument). The registry (one row per experiment) is made for you as `registry.xlsx` in that folder; to use another one, e.g. shared on OneDrive, open **Use a different registry**. The choice is saved in `~/.mfethuls/settings.json`, so notebooks use the same folders; change it any time under **⚙ Settings**.
- **Try the example**: explore example DSC, TGA, FTIR and fluorescence data, copied to `~/mfethuls-example`. Your own data is not touched.
- **Use it from Python**: the tutorial notebook (below).

A getting-started checklist then walks through registering (**Ingest** → **Review & register**), ingesting, selecting and plotting (**Colour by**, **Style by**, axis limits, SVG/HTML export); a compact tracker stays at the top of the sidebar, next to 🏠 (back to the welcome page) and ⚙. A folder named unlike its instrument (`DMA data`) is offered in **Review & register**, where you choose its instrument; file and folder names may contain spaces.

Non-technical users: double-click `launch.bat` (Windows) or run `bash launch.sh`; it needs only [`uv`](https://docs.astral.sh/uv/). See [docs/guides/local_setup.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/local_setup.md). Folders can also come from `.env` (copy `env_example`); folders saved in the app take precedence. `experiments_template.csv` in the repo root has an example row for every supported instrument.

**Python API:** a guided tutorial (a marimo notebook on its own copy of the example data) opens with `mfethuls-tutorial`, or **Use it from Python** on the app's welcome page.

```python
import mfethuls

# Load one or more experiments
cs = mfethuls.load_experiments(["exp_001", "exp_002"])
df = cs.to_dataframe()   # tidy long-format DataFrame

# Load all experiments for a sample
cs = mfethuls.load_samples(["S001", "S002"])
```

**Command line:** the same tasks as the app, for terminals and scripts. See [docs/guides/command_line.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/command_line.md).

```shell
mfethuls settings --data-folder D:\lab-data --registry D:\lab-data\experiments.xlsx
mfethuls validate --check-files
mfethuls ingest --all
mfethuls plot exp_001 exp_002 -o comparison.svg
mfethuls cleanup --apply
```

**Plotting:**

```python
fig, ax = mfethuls.plot_experiments(cs)                  # publication figure (Matplotlib)
fig = mfethuls.plot_experiments(cs, backend="plotly")    # interactive, every data point (WebGL)
mfethuls.set_plot_backend("plotly")                      # make Plotly the default
```

Each instrument gets a suitable plot, with axis labels and units (*Temperature (°C)*, *Wavenumber (cm⁻¹)*). Experiments that share an x-axis are overlaid, otherwise each gets its own panel, and time-resolved spectra series are coloured by elapsed time. Matplotlib figures use a fixed publication style and save as vector SVG/PDF. See [docs/guides/plotting.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/plotting.md).

---

## For teams

A shared lab server (API, background ingest, Postgres, cloud storage, OneDrive sync and a shared app) is developed separately as **mfethuls-server**, which builds on this package.

---

## Data access for analysis

Ingested data is stored as one Parquet file per experiment (with a `.metadata.json` sidecar), in the storage folder (`_storage` inside the data folder by default). A DuckDB catalog (`mfethuls.duckdb`) lists every dataset and has one SQL view per dataset over its Parquet file. Load data through the Python API, query it with SQL (`mfethuls.storage.catalog_path()` gives the catalog file), or read the Parquet files directly. See [docs/guides/data_analysis.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/data_analysis.md) for SQL recipes and model-building patterns.

---

## Docs

### Guides

How to do things, step by step.

| Guide | Contents |
|---|---|
| [docs/guides/quickstart.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/quickstart.md) | Start here: install, the app's first run, and using mfethuls from Python |
| [docs/guides/local_setup.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/local_setup.md) | Non-technical user guide — `uv` + launcher |
| [docs/guides/workflow.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/workflow.md) | End-to-end tutorial — registry → ingest → dashboard → notebook |
| [docs/guides/command_line.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/command_line.md) | The `mfethuls` command: settings, ingest, clean up, export and plot from a terminal or script |
| [docs/guides/data_analysis.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/data_analysis.md) | Notebook access — Python API, DuckDB SQL, model building |
| [docs/guides/plotting.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/plotting.md) | Built-in plots, Matplotlib/Plotly backends, labels and units, dashboard plotting |
| [docs/guides/instruments.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/guides/instruments.md) | Adding an instrument from one of its files, without code — instrument definitions |

### Reference

What each format and part is, to look things up.

| Reference | Contents |
|---|---|
| [docs/reference/registry.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/reference/registry.md) | Registry format, column reference, instrument folders |
| [docs/reference/schema.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/reference/schema.md) | Canonical column names, units, normalisation rules |
| [docs/reference/architecture.md](https://github.com/lucaAyt/mfethuls/blob/master/docs/reference/architecture.md) | System diagrams, ETL pipeline, storage design |

---

## License

Apache License 2.0 — see [LICENSE](https://github.com/lucaAyt/mfethuls/blob/master/LICENSE) and [NOTICE](https://github.com/lucaAyt/mfethuls/blob/master/NOTICE). Versions released before the change were published under the MIT License.

Contributions are welcome; see [CONTRIBUTING.md](https://github.com/lucaAyt/mfethuls/blob/master/CONTRIBUTING.md). First-time contributors are asked to sign the [Contributor License Agreement](https://github.com/lucaAyt/mfethuls/blob/master/CLA.md).
