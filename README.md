# mfethuls

## 🚀 About

A scalable, extensible Python framework for parsing, characterizing, and handling data from laboratory instruments.

## 📌 Roadmap

The pinned top-level objectives live in [ROADMAP.md](ROADMAP.md).
The normalization and canonical schema rules live in [SCHEMA_CONTRACT.md](SCHEMA_CONTRACT.md).

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

## 🚁 Usage


- For usage you will need to edit the `env_example` file after installation and save as `.env` in the same location.
- Consult the notebook ``notebooks\tutorial_basic_usecase`` for an example.
- For developers, please work on a suitable branch and send a pull request.

## 📁 Package layout (dev)

- `mfethuls/api`: FastAPI app wiring (`app.py`), route handlers (`routes.py`), schemas, and helpers.
- `mfethuls/storage`: storage backends, metadata persistence, DuckDB query backend, and storage manager.

API entrypoint:
```python
from mfethuls.api import app
```

## 📃 License

MIT

## Notes
This package is still under development and is in no way a production ready service.
