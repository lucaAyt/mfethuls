# mfethuls

A Python framework for parsing, normalizing, and managing data from laboratory instruments. Raw instrument exports (DSC, TGA, FTIR, UV-Vis, SEC, NMR, Rheometer, DMA, SAXS, MS) are parsed against a shared experiment registry, normalized to a canonical schema, and stored as queryable Parquet datasets — accessible via REST API, Metabase dashboards, notebooks, or a local Streamlit explorer.

---

## Install

Work inside a virtual environment:

```shell
python -m venv .venv && source .venv/bin/activate   # Linux/macOS
python -m venv .venv && .venv\Scripts\activate       # Windows
```

Install from GitHub (SSH recommended):

```shell
pip install git+ssh://git@github.com/lucaAyt/mfethuls.git
```

For development, clone and install as editable:

```shell
git clone ssh://git@github.com/lucaAyt/mfethuls.git
cd mfethuls
pip install -e .
```

**Extras** — install only what you need:

| Extra | Installs | When to use |
|-------|----------|-------------|
| `service` | FastAPI, Uvicorn, SQLAlchemy, Psycopg2 | API + worker containers |
| `cloud` | boto3, azure-storage-blob | S3 / Azure Blob storage |
| `viz` | Matplotlib, Plotly, Kaleido | Plotting |
| `notebook` | Jupyter, IPython | Interactive notebooks |

```shell
pip install -e '.[service]'          # API + worker
pip install -e '.[service,cloud]'    # API + worker + cloud storage
pip install -e '.[viz,notebook]'     # Local analysis
```

---

## Configuration

Copy `env_example` to `.env` and edit before running anything:

```shell
cp env_example .env
```

Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `MFETHULS_MODE` | yes | `local` or `service` |
| `PATH_TO_DATA` | yes | Root folder containing raw instrument exports |
| `PATH_TO_REGISTRY` | yes | Path to the shared experiments CSV/XLSX |
| `PATH_TO_LOCAL_STORAGE` | yes | Where Parquet files are written |
| `MFETHULS_DUCKDB_PATH` | no | DuckDB catalog file path (default: inside storage root) |
| `MFETHULS_API_KEY` | service | Bearer token for API authentication — **required in service mode** |
| `MFETHULS_POSTGRES_ENABLED` | service | `true` to enable Postgres job queue + metadata |
| `MFETHULS_POSTGRES_USER` | service | Postgres credentials |
| `MFETHULS_POSTGRES_PASSWORD` | service | |
| `MFETHULS_POSTGRES_DB` | service | |
| `MFETHULS_POSTGRES_HOST` | service | |
| `MFETHULS_JOB_TIMEOUT_SECONDS` | no | Max seconds per ingest job (default: 1800) |

---

## Local mode (notebooks, CLI, Streamlit)

Local mode requires no Postgres and no Docker. Everything runs in a single Python process.

### Python API

```python
import mfethuls

# Load experiments from the shared registry
experiments = mfethuls.load_experiments(["exp_001", "exp_002"])

# Combine into a comparison set and get a tidy DataFrame
comparison = mfethuls.compare(experiments)
df = comparison.to_dataframe()
```

### Streamlit explorer

**For non-technical users** — double-click `launch.bat` (Windows) or run `bash launch.sh` (macOS/Linux). A first-run wizard collects your data paths. Requires only [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — see [docs/local_user_setup.md](docs/local_user_setup.md) for the full guide.

**For developers:**

```shell
streamlit run apps/streamlit_app.py
```

Provides a registry loader, ingest sidebar, dataset browser, and ad-hoc plotting.

### Notebooks

See `notebooks/` for worked examples. The `tutorial_basic_usecase` notebook covers the end-to-end local workflow.

---

## Service mode (Docker API + worker)

Service mode runs the full stack: FastAPI, background worker, Postgres job queue, DuckDB catalog, and Metabase dashboards.

### Start

```shell
docker compose up --build
```

### Authentication

All API endpoints (except `GET /health`) require a bearer token.

Set `MFETHULS_API_KEY` in your `.env`:

```
MFETHULS_API_KEY=your-secret-token
```

Include the header in every request:

```shell
-H "Authorization: Bearer your-secret-token"
```

### Workflow

**1. Validate your registry before ingesting:**

```shell
curl -s http://localhost:8000/registry/preview \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@path/to/experiments_template.csv" | jq '.summary'
```

**2. Start an ingest job:**

```shell
curl -s -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@path/to/experiments_template.csv"
```

Returns `{"job_id": "...", "status": "queued"}`.

**3. Poll job status:**

```shell
curl -s http://localhost:8000/jobs/<job_id> \
  -H "Authorization: Bearer your-secret-token" | jq '{status, progress}'
```

**4. List all jobs:**

```shell
curl -s "http://localhost:8000/jobs?status=completed&limit=10" \
  -H "Authorization: Bearer your-secret-token"
```

**5. Browse datasets:**

```shell
curl -s http://localhost:8000/datasets \
  -H "Authorization: Bearer your-secret-token"
```

**6. Fetch dataset rows (paginated):**

```shell
curl -s "http://localhost:8000/dataset/<table_name>?limit=100&offset=0" \
  -H "Authorization: Bearer your-secret-token"
```

**7. Delete a dataset from the catalog:**

```shell
curl -s -X DELETE http://localhost:8000/dataset/<table_name> \
  -H "Authorization: Bearer your-secret-token"
```

Note: `DELETE` removes the dataset from the DuckDB catalog and query layer. Parquet files on disk or object storage are not deleted and can be re-registered.

---

## Docs

| Document | Contents |
|----------|----------|
| [docs/local_user_setup.md](docs/local_user_setup.md) | Non-technical user guide — run Streamlit locally with `uv` |
| [docs/tutorial.md](docs/tutorial.md) | Step-by-step tutorials for local mode and service mode |
| [docs/registry_reference.md](docs/registry_reference.md) | Registry spreadsheet format, column reference, example CSV, measurement profiles |
| [docs/architecture.md](docs/architecture.md) | System context, deployment modes, data-flow diagrams |
| [docs/api_reference.md](docs/api_reference.md) | Full API endpoint reference with request/response examples |
| [docs/deployment.md](docs/deployment.md) | DigitalOcean + Tailscale cloud deployment guide |
| [docs/ingest_preview_contract.md](docs/ingest_preview_contract.md) | Detailed preview and ingest payload contracts |
| [docs/database_integration.md](docs/database_integration.md) | Postgres + Parquet + DuckDB design notes |
| [SCHEMA_CONTRACT.md](SCHEMA_CONTRACT.md) | Canonical column names, units, and normalization rules |
