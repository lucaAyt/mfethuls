"""Storage configuration helpers and environment resolution."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Dict, Optional

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
def _get_duckdb_path() -> str:
    path = get_settings().duckdb_path
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
    s3 = get_settings().s3
    return {
        "bucket": s3.bucket,
        "prefix": _normalize_prefix(s3.prefix),
        "region": s3.region,
        "endpoint": s3.endpoint,
        "access_key_id": s3.access_key_id,
        "secret_access_key": s3.secret_access_key,
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
    s3 = get_settings().s3
    return {
        "region": s3.region,
        "endpoint": s3.endpoint,
        "access_key_id": s3.access_key_id,
        "secret_access_key": s3.secret_access_key,
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
    azure = get_settings().azure
    return {
        "connection_string": azure.connection_string,
        "account": azure.account,
        "container": azure.container,
        "prefix": _normalize_prefix(azure.prefix),
        "key": azure.key,
        "sas_token": azure.sas_token,
    }


def get_postgres_db_url() -> Optional[str]:
    settings = get_settings()
    if not settings.is_service_mode:
        return None
    postgres = settings.postgres
    if not postgres.enabled:
        return None

    user, password, host = postgres.user, postgres.password, postgres.host
    port, database = postgres.port, postgres.database

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


def _view_basename(experiment) -> str:
    parts = [experiment.name]
    if experiment.sample_id:
        parts.append(experiment.sample_id)
    if experiment.run_id:
        parts.append(experiment.run_id)
    return "_".join(parts)
