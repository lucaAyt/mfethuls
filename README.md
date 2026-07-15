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

Each parser normalises raw exports to a [canonical column schema](SCHEMA_CONTRACT.md) — same column names and units regardless of instrument model.

---

## Install

```shell
pip install git+https://github.com/lucaAyt/mfethuls.git
```

Install extras as needed:

| Extra | Installs | Use when |
|---|---|---|
| `viz` | Plotly, Matplotlib, Kaleido, Streamlit | Streamlit dashboard or notebook plotting |
| `notebook` | Jupyter | Interactive notebooks |
| `service` | FastAPI, Uvicorn, SQLAlchemy, psycopg2 | Running the API + worker |
| `cloud` | boto3, azure-storage-blob | S3 or Azure Blob Parquet storage |
| `postgres` | SQLAlchemy, psycopg2 | Postgres metadata access from notebooks |

```shell
pip install "mfethuls[viz,notebook]"        # local analysis
pip install "mfethuls[service,cloud]"       # server deployment
```

---

## Local mode — notebooks and Streamlit

No Docker, no Postgres, no server. Set paths in `.env` (copy from `env_example`):

```
MFETHULS_MODE=local
PATH_TO_DATA=/path/to/raw/instrument/data
PATH_TO_REGISTRY=/path/to/experiments_template.csv
PATH_TO_LOCAL_STORAGE=/path/to/parquet/output
```

**Run the Streamlit explorer:**

```shell
streamlit run apps/Home.py
```

Non-technical users on Windows: double-click `launch.bat`. A setup wizard collects paths on first run. Requires only [`uv`](https://docs.astral.sh/uv/). See [docs/local_user_setup.md](docs/local_user_setup.md).

**Python API:**

```python
import mfethuls

# Load one or more experiments
cs = mfethuls.load_experiments(["exp_001", "exp_002"])
df = cs.to_dataframe()   # tidy long-format DataFrame

# Load all experiments for a sample
cs = mfethuls.load_samples(["S001", "S002"])
```

---

## Service mode — shared lab server

Runs a Docker Compose stack: FastAPI + background worker + Postgres + Streamlit. The team accesses the Streamlit dashboard over a private network (Tailscale recommended).

```shell
cp env_example .env   # fill in credentials and paths
docker compose up --build -d
```

**Workflow in the Streamlit dashboard:**

1. **Ingest sidebar → Sync from OneDrive** — pulls raw data and registry via rclone
2. **Select experiments** — multiselect from the registry
3. **Ingest experiments** — live progress bar polls until done
4. **Datasets tab** — browse, filter, and plot any ingested dataset
5. **Export** — SVG (server-side via kaleido) or interactive HTML

**REST API** (all endpoints require `Authorization: Bearer <token>`):

```shell
# Validate registry (reads from server PATH_TO_REGISTRY)
curl -s -X POST http://localhost:8000/registry/preview \
  -H "Authorization: Bearer <token>"

# Start ingest job
curl -s -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer <token>"

# Poll job status
curl -s http://localhost:8000/jobs/<job_id> \
  -H "Authorization: Bearer <token>" | jq '{status, progress}'

# List datasets
curl -s http://localhost:8000/datasets \
  -H "Authorization: Bearer <token>"
```

See [docs/api_reference.md](docs/api_reference.md) for the full reference. For cloud deployment on DigitalOcean + Tailscale see [docs/deployment.md](docs/deployment.md).

---

## Data access for analysis

Three stores, each with a distinct role — see [docs/data_scientist_guide.md](docs/data_scientist_guide.md) for the full guide including DuckDB SQL recipes and model-building patterns.

| Store | What's in it | How to query |
|---|---|---|
| **DuckDB** | Measurement data — one VIEW per experiment | `duckdb.connect(path).execute("SELECT * FROM exp_name")` |
| **Postgres** | Metadata — instrument, sample, provenance | `mfethuls.storage.notebook.list_datasets(pg_url)` |
| **Parquet** | Source of truth for measurement data | `pd.read_parquet(path)` |

---

## Docs

| Document | Contents |
|---|---|
| [docs/local_user_setup.md](docs/local_user_setup.md) | Non-technical user guide — `uv` + launcher |
| [docs/tutorial.md](docs/tutorial.md) | Step-by-step walkthroughs for local and service mode |
| [docs/data_scientist_guide.md](docs/data_scientist_guide.md) | Notebook access — Python API, DuckDB SQL, Postgres, model building |
| [docs/registry_reference.md](docs/registry_reference.md) | Registry format, column reference, measurement profiles |
| [docs/architecture.md](docs/architecture.md) | System diagrams, ETL pipeline, storage design |
| [docs/api_reference.md](docs/api_reference.md) | Full REST API reference |
| [docs/deployment.md](docs/deployment.md) | Cloud deployment guide |
| [SCHEMA_CONTRACT.md](SCHEMA_CONTRACT.md) | Canonical column names, units, normalisation rules |

---

## License

MIT — see [LICENSE](LICENSE).
