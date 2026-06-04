# mfethuls

## 🚀 About

A scalable, extensible Python framework for parsing, characterizing, and handling data from laboratory instruments.

## 📌 Roadmap

The pinned top-level objectives live in [ROADMAP.md](ROADMAP.md).
The normalization and canonical schema rules live in [SCHEMA_CONTRACT.md](SCHEMA_CONTRACT.md).
System architecture and data-flow diagrams: [docs/architecture.md](docs/architecture.md).

## 🔧 Install
It is recommended to build from within a virtual environment:<br> 
https://docs.python.org/3/library/venv.html

The package is pip installable (ssh recommended):
```shell
# ssh
pip install git+ssh://git@github.com/lucaAyt/mfethuls.git
```
```shell
# https
pip install git+https://git@github.com/lucaAyt/mfethuls.git
```
To setup ssh keys see the following:<br>
https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent

For development installation, the following is recommended:
```shell
# For development purposes it is best to clone and then pip install as an editable.
git clone ssh://git@github.com/lucaAyt/mfethuls.git
cd mfethuls
pip install -e .
```

For API and worker containers, use the slimmer runtime extras:
```shell
pip install -e '.[service]'
```

Add plotting or notebook tooling only when needed locally:
```shell
pip install -e '.[viz]'
pip install -e '.[notebook]'
```

## 🚁 Usage


- For usage you will need to edit the `env_example` file after installation and save as `.env` in the same location.
- Consult the notebook ``notebooks\tutorial_basic_usecase`` for an example.
- For developers, please work on a suitable branch and send a pull request.

### Service mode (Docker API + worker)

1. Copy `env_example` to `.env` and set `MFETHULS_POSTGRES_ENABLED=true` with credentials matching `docker-compose.yml`.
2. Run `docker compose up --build`.
3. Smoke-check the API:

```shell
curl http://localhost:8000/health
curl -X POST http://localhost:8000/registry/preview -F "file=@path/to/experiments_template.csv"
curl -X POST http://localhost:8000/ingest -F "file=@path/to/experiments_template.csv"
curl http://localhost:8000/jobs/<job_id>
curl http://localhost:8000/datasets
```

Ingest requires Postgres (`MFETHULS_POSTGRES_ENABLED=true`). The API opens DuckDB read-only per request; the worker closes DuckDB after each job so both can share `MFETHULS_DUCKDB_PATH`.

## 📁 Package layout (dev)

- `mfethuls/api`: FastAPI app wiring (`app.py`), route handlers (`routes.py`), schemas, and helpers.
- `mfethuls/storage`: storage backends, metadata persistence, DuckDB query backend, and storage manager.
- `mfethuls/plotting`: optional plotting helpers used by the CLI and notebooks when the `viz` extra is installed.

API entrypoint:
```python
from mfethuls.api import app
```

## 📃 License

MIT

## Notes
This package is still under development and is in no way a production ready service.
