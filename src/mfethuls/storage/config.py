"""Local storage locations, package version and dataset naming."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from ..settings import get_settings


def _get_package_version() -> str:
    try:
        return str(version("mfethuls"))
    except PackageNotFoundError:
        return "unknown"


def _get_storage_root() -> str:
    settings = get_settings()
    if settings.local_storage:
        root = os.path.abspath(settings.local_storage)
        os.makedirs(root, exist_ok=True)
        return root

    data_root = settings.data_root
    if data_root:
        root = os.path.abspath(os.path.join(data_root, "_storage"))
    else:
        root = os.path.abspath(os.path.join(os.getcwd(), ".mfethuls_storage"))

    os.makedirs(root, exist_ok=True)
    return root


# Need to check that file exists to decide 
# whether to initialise or connect
def catalog_path() -> str:
    """Where the DuckDB catalog is (``MFETHULS_DUCKDB_PATH``, else ``mfethuls.duckdb`` in the storage folder).

    For querying it directly: ``duckdb.connect(catalog_path(), read_only=True)``.
    """
    return _get_duckdb_path()


def _get_duckdb_path() -> str:
    path = get_settings().duckdb_path
    if not path:
        return os.path.join(_get_storage_root(), "mfethuls.duckdb")
    return path


def _dataset_basename(experiment) -> str:
    parts = [experiment.experiment_id]
    if experiment.sample_id:
        parts.append(experiment.sample_id)
    if experiment.run_id:
        parts.append(experiment.run_id)
    return "_".join(parts)


def _view_basename(experiment) -> str:
    parts = [experiment.name]
    if experiment.sample_id:
        parts.append(experiment.sample_id)
    if experiment.run_id:
        parts.append(experiment.run_id)
    return "_".join(parts)
