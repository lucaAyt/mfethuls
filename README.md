# mfethuls

A Python framework for parsing, normalising, and managing data from laboratory instruments. Raw instrument exports are ingested against a shared experiment registry, normalised to a canonical schema, and stored as queryable Parquet datasets — accessible via a Streamlit dashboard, REST API, or notebooks.

---

## Instrument support

| Instrument | Models |
|---|---|
| DSC | Generic, Mettler Toledo, Perkin Elmer |
| TGA | Generic |
| FTIR | Bruker |
| UV-Vis | Shimadzu, Ocean Optics Flame (in-situ) |
| NMR | Bruker |
| Rheometer | Anton Paar |
| DMA | TA Q800 |
| SEC | Agilent |
| SAXS | Anton Paar |
| MS | Bruker |

Each parser normalises raw exports to a [canonical column schema](docs/reference/schema.md) — same column names and units regardless of instrument model.

---

## Install

```shell
pip install git+https://github.com/lucaAyt/mfethuls.git
```

Install extras as needed:

| Extra | Installs | Use when |
|---|---|---|
| `viz` | Plotly, Matplotlib, Kaleido, Streamlit | The app or notebook plotting |
| `notebook` | Jupyter, Marimo, Matplotlib, Plotly, seaborn | Interactive notebooks with plotting |

```shell
pip install "mfethuls[viz,notebook]"
```

---

## Getting started — notebooks and the app

No Docker, no database, no server. Set paths in `.env` (copy from `env_example`):

```
PATH_TO_DATA=/path/to/raw/instrument/data
PATH_TO_REGISTRY=/path/to/experiments_template.csv
PATH_TO_LOCAL_STORAGE=/path/to/parquet/output
```

`experiments_template.csv` in the repo root is a pre-filled registry template — open in Excel and adapt to your experiments. To try mfethuls without your own data, point `PATH_TO_DATA` at `examples/data/` and `PATH_TO_REGISTRY` at `examples/experiments_registry.csv` — example DSC, TGA, FTIR, and fluorescence in-situ files are included.

**Run the app:**

```shell
mfethuls-app
```

In the sidebar: ingest experiments, **Review & register** raw data that is not in the registry yet, **Clean up** after editing the registry, and browse, plot and export datasets.

Non-technical users on Windows: double-click `launch.bat`. A setup wizard collects paths on first run. Requires only [`uv`](https://docs.astral.sh/uv/). See [docs/guides/local_setup.md](docs/guides/local_setup.md).

**Python API:**

```python
import mfethuls

# Load one or more experiments
cs = mfethuls.load_experiments(["exp_001", "exp_002"])
df = cs.to_dataframe()   # tidy long-format DataFrame

# Load all experiments for a sample
cs = mfethuls.load_samples(["S001", "S002"])
```

**Plotting:**

```python
fig, ax = mfethuls.plot_experiments(cs)                  # publication figure (Matplotlib)
fig = mfethuls.plot_experiments(cs, backend="plotly")    # interactive, every data point (WebGL)
mfethuls.set_plot_backend("plotly")                      # make Plotly the default
```

Each instrument gets a suitable plot, with axis labels and units (*Temperature (°C)*, *Wavenumber (cm⁻¹)*). Experiments that share an x-axis are overlaid, otherwise each gets its own panel, and time-resolved spectra series are coloured by elapsed time. Matplotlib figures use a fixed publication style and save as vector SVG/PDF. See [docs/guides/plotting.md](docs/guides/plotting.md).

---

## For teams

A shared lab server (API, background ingest, Postgres, cloud storage, OneDrive sync and a shared app) is developed separately as **mfethuls-server**, which builds on this package.

---

## Data access for analysis

Three stores, each with a distinct role — see [docs/guides/data_analysis.md](docs/guides/data_analysis.md) for the full guide including DuckDB SQL recipes and model-building patterns.

---

## Docs

| Document | Contents |
|---|---|
| [docs/guides/quickstart.md](docs/guides/quickstart.md) | Start here — Tailscale dashboard access or local Python setup |
| [docs/guides/workflow.md](docs/guides/workflow.md) | End-to-end tutorial — registry → ingest → dashboard → notebook |
| [docs/guides/local_setup.md](docs/guides/local_setup.md) | Non-technical user guide — `uv` + launcher |
| [docs/guides/data_analysis.md](docs/guides/data_analysis.md) | Notebook access — Python API, DuckDB SQL, model building |
| [docs/guides/plotting.md](docs/guides/plotting.md) | Built-in plots, Matplotlib/Plotly backends, labels and units, dashboard plotting |
| [docs/reference/registry.md](docs/reference/registry.md) | Registry format, column reference, measurement profiles |
| [docs/reference/architecture.md](docs/reference/architecture.md) | System diagrams, ETL pipeline, storage design |
| [docs/reference/schema.md](docs/reference/schema.md) | Canonical column names, units, normalisation rules |

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Versions released before the change were published under the MIT License.

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). First-time contributors are asked to sign a Contributor License Agreement.
