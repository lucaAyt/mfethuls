"""Storage configuration helpers and environment resolution."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Dict, Optional


def _get_package_version() -> str:
    try:
        return str(version("mfethuls"))
    except PackageNotFoundError:
        return "unknown"


def _get_storage_root() -> str:
    for key in ("PATH_TO_LOCAL_STORAGE", "PATH_TO_STORAGE", "MFETHULS_STORAGE_ROOT"):
        value = os.environ.get(key)
        if value:
            root = os.path.abspath(value)
            os.makedirs(root, exist_ok=True)
            return root

    data_root = os.environ.get("PATH_TO_DATA")
    if data_root:
        root = os.path.abspath(os.path.join(data_root, "_storage"))
    else:
        root = os.path.abspath(os.path.join(os.getcwd(), ".mfethuls_storage"))

    os.makedirs(root, exist_ok=True)
    return root


# Need to check that file exists to decide 
# whether to initialise or connect
def _get_duckdb_path() -> str:
    path = os.environ.get("MFETHULS_DUCKDB_PATH")
    if not path:
        return os.path.join(_get_storage_root(), "mfethuls.duckdb")
    return path


def _normalize_prefix(prefix: Optional[str]) -> str:
    if not prefix:
        return ""
    return prefix.strip("/")


def _join_storage_key(*parts: Optional[str]) -> str:
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    return "/".join(cleaned)


def _get_s3_config() -> Dict[str, Optional[str]]:
    return {
        "bucket": os.environ.get("MFETHULS_S3_BUCKET"),
        "prefix": _normalize_prefix(os.environ.get("MFETHULS_S3_PREFIX")),
        "region": os.environ.get("MFETHULS_S3_REGION"),
        "endpoint": os.environ.get("MFETHULS_S3_ENDPOINT"),
    }


def _get_s3_endpoint_url() -> Optional[str]:
    config = _get_s3_config()
    region = config.get("region")
    endpoint = config.get("endpoint")
    if endpoint:
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        if region and not endpoint.startswith(f"{region}."):
            return f"https://{region}.{endpoint}"
        return f"https://{endpoint}"
    if region:
        return f"https://{region}.digitaloceanspaces.com"
    return None


def _get_duckdb_s3_config() -> Dict[str, Optional[str]]:
    return {
        "region": os.environ.get("MFETHULS_S3_REGION"),
        "endpoint": os.environ.get("MFETHULS_S3_ENDPOINT"),
        "access_key_id": os.environ.get("MFETHULS_S3_ACCESS_KEY"),
        "secret_access_key": os.environ.get("MFETHULS_S3_SECRET_KEY"),
    }


def _get_duckdb_s3_endpoint_host(region: Optional[str], endpoint: Optional[str]) -> Optional[str]:
    resolved_region = (region or "").strip()
    resolved_endpoint = (endpoint or "").strip()

    if not resolved_endpoint:
        return f"{resolved_region}.digitaloceanspaces.com" if resolved_region else None

    if resolved_endpoint.startswith(("http://", "https://")):
        resolved_endpoint = resolved_endpoint.split("//", 1)[1]

    if resolved_endpoint.endswith("digitaloceanspaces.com"):
        return f"{resolved_region}.digitaloceanspaces.com" if resolved_region else resolved_endpoint

    return resolved_endpoint


def _get_azure_blob_config() -> Dict[str, Optional[str]]:
    return {
        "connection_string": os.environ.get("MFETHULS_AZURE_CONNECTION_STRING"),
        "account": os.environ.get("MFETHULS_AZURE_ACCOUNT"),
        "container": os.environ.get("MFETHULS_AZURE_CONTAINER"),
        "prefix": _normalize_prefix(os.environ.get("MFETHULS_AZURE_PREFIX")),
        "key": os.environ.get("MFETHULS_AZURE_KEY"),
        "sas_token": os.environ.get("MFETHULS_AZURE_SAS_TOKEN"),
    }


def get_postgres_db_url() -> Optional[str]:
    from ..config.mode import is_service_mode
    if not is_service_mode():
        return None
    enabled = os.environ.get("MFETHULS_POSTGRES_ENABLED", "").lower()
    if enabled not in {"1", "true", "yes"}:
        return None

    user = os.environ.get("MFETHULS_POSTGRES_USER")
    password = os.environ.get("MFETHULS_POSTGRES_PASSWORD")
    host = os.environ.get("MFETHULS_POSTGRES_HOST", "localhost")
    port = os.environ.get("MFETHULS_POSTGRES_PORT")
    database = os.environ.get("MFETHULS_POSTGRES_DB")

    if not (user and password and database):
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "MFETHULS_POSTGRES_ENABLED is true but required credentials are missing. "
            "Provide either MFETHULS_POSTGRES_URL or all of: "
            "MFETHULS_POSTGRES_USER, MFETHULS_POSTGRES_PASSWORD, MFETHULS_POSTGRES_DB. "
            "Postgres registration disabled."
        )
        return None

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _dataset_basename(experiment) -> str:
    parts = [experiment.experiment_id]
    if experiment.sample_id:
        parts.append(experiment.sample_id)
    if experiment.run_id:
        parts.append(experiment.run_id)
    return "_".join(parts)
