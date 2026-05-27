"""Storage backend implementations (local, S3, Azure)."""

from __future__ import annotations

import io
import json
import os
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..dataset import Dataset
from ..experiments import Experiment
from .config import (
    _dataset_basename,
    _get_azure_blob_config,
    _get_s3_config,
    _get_s3_endpoint_url,
    _get_storage_root,
    _join_storage_key,
    _normalize_prefix,
)
from .provenance import _build_provenance_metadata, _json_default
from .types import DataStorageBackend

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
    from botocore.config import Config  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None  # type: ignore
    ClientError = None  # type: ignore
    Config = None  # type: ignore

try:
    from azure.storage.blob import BlobServiceClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BlobServiceClient = None  # type: ignore


def _get_boto3():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "boto3", boto3)


def _get_client_error():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "ClientError", ClientError)


def _get_config():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "Config", Config)


def _get_blob_service_client():
    import sys

    storage_module = sys.modules.get("mfethuls.storage")
    return getattr(storage_module, "BlobServiceClient", BlobServiceClient)


class LocalParquetStorage(DataStorageBackend):
    """Local filesystem storage for datasets and metadata."""

    def __init__(self, root: str | None = None) -> None:
        self.root = os.path.abspath(root or _get_storage_root())
        os.makedirs(self.root, exist_ok=True)

    def _experiment_dir(self, experiment: Experiment) -> str:
        instrument_dir = os.path.join(self.root, experiment.instrument_name)
        experiment_dir = os.path.join(instrument_dir, experiment.experiment_id)
        os.makedirs(experiment_dir, exist_ok=True)
        return experiment_dir

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        experiment_dir = self._experiment_dir(experiment)
        base = _dataset_basename(experiment)
        parquet_path = os.path.join(experiment_dir, f"{base}.parquet")
        meta_path = os.path.join(experiment_dir, f"{base}.metadata.json")
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_path, _ = self.dataset_paths(experiment)
        return os.path.exists(parquet_path)

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_path, meta_path = self.dataset_paths(experiment)
        dataset.data.to_parquet(parquet_path, index=False)

        metadata_to_store = dict(dataset.metadata)
        metadata_to_store.setdefault("experiment_id", experiment.experiment_id)
        metadata_to_store.setdefault("sample_id", experiment.sample_id)
        metadata_to_store.setdefault("run_id", experiment.run_id)
        metadata_to_store.setdefault("instrument_name", experiment.instrument_name)
        metadata_to_store["provenance"] = _build_provenance_metadata(
            experiment,
            dataset,
            parquet_path,
            meta_path,
            storage_backend="local_filesystem",
        )

        with open(meta_path, "w", encoding="utf8") as handle:
            json.dump(metadata_to_store, handle, default=_json_default)

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_path, meta_path = self.dataset_paths(experiment)
        if not os.path.exists(parquet_path):
            raise FileNotFoundError(f"No stored dataset found at {parquet_path!r}")

        data = pd.read_parquet(parquet_path)

        metadata: Dict[str, Any] = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf8") as handle:
                metadata = json.load(handle)

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class S3ParquetStorage(DataStorageBackend):
    """S3-backed storage for datasets and metadata JSON files."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        client: Any = None,
    ) -> None:
        if _get_boto3() is None or _get_client_error() is None:
            raise RuntimeError("boto3 is required for S3ParquetStorage. Install boto3.")

        config = _get_s3_config()
        self.bucket = bucket or config.get("bucket")
        self.prefix = _normalize_prefix(prefix or config.get("prefix"))
        self.region = region or config.get("region")
        self.endpoint_url = endpoint_url or _get_s3_endpoint_url()

        if not self.bucket:
            raise ValueError("S3 bucket is required. Set MFETHULS_S3_BUCKET or pass bucket.")

        config_cls = _get_config()
        self.client = client or _get_boto3().client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=os.environ.get("MFETHULS_S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("MFETHULS_S3_SECRET_KEY"),
            config=config_cls(signature_version="s3v4") if config_cls else None,
        )

    def _s3_key(self, experiment: Experiment, suffix: str) -> str:
        base = _dataset_basename(experiment)
        filename = f"{base}{suffix}"
        return _join_storage_key(self.prefix, experiment.instrument_name, experiment.experiment_id, filename)

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")
        parquet_path = f"s3://{self.bucket}/{parquet_key}"
        meta_path = f"s3://{self.bucket}/{meta_key}"
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_key = self._s3_key(experiment, ".parquet")
        try:
            self.client.head_object(Bucket=self.bucket, Key=parquet_key)
            return True
        except _get_client_error():
            return False

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")
        parquet_path, meta_path = self.dataset_paths(experiment)

        parquet_buffer = io.BytesIO()
        dataset.data.to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)
        self.client.put_object(Bucket=self.bucket, Key=parquet_key, Body=parquet_buffer.getvalue())

        metadata_to_store = dict(dataset.metadata)
        metadata_to_store.setdefault("experiment_id", experiment.experiment_id)
        metadata_to_store.setdefault("sample_id", experiment.sample_id)
        metadata_to_store.setdefault("run_id", experiment.run_id)
        metadata_to_store.setdefault("instrument_name", experiment.instrument_name)
        metadata_to_store["provenance"] = _build_provenance_metadata(
            experiment,
            dataset,
            parquet_path,
            meta_path,
            storage_backend="s3",
        )

        meta_body = json.dumps(metadata_to_store, default=_json_default).encode("utf8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=meta_key,
            Body=meta_body,
            ContentType="application/json",
        )

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_key = self._s3_key(experiment, ".parquet")
        meta_key = self._s3_key(experiment, ".metadata.json")

        try:
            parquet_obj = self.client.get_object(Bucket=self.bucket, Key=parquet_key)
        except _get_client_error() as exc:
            raise FileNotFoundError(f"No stored dataset found at s3://{self.bucket}/{parquet_key}") from exc

        parquet_bytes = parquet_obj["Body"].read()
        data = pd.read_parquet(io.BytesIO(parquet_bytes))

        metadata: Dict[str, Any] = {}
        try:
            meta_obj = self.client.get_object(Bucket=self.bucket, Key=meta_key)
            metadata = json.loads(meta_obj["Body"].read().decode("utf8"))
        except _get_client_error():
            metadata = {}

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class AzureBlobParquetStorage(DataStorageBackend):
    """Azure Blob storage backend for datasets and metadata JSON files."""

    def __init__(
        self,
        account: Optional[str] = None,
        container: Optional[str] = None,
        prefix: Optional[str] = None,
        connection_string: Optional[str] = None,
        credential: Optional[str] = None,
        service_client: Any = None,
    ) -> None:
        if _get_blob_service_client() is None:
            raise RuntimeError(
                "azure-storage-blob is required for AzureBlobParquetStorage. Install azure-storage-blob."
            )

        config = _get_azure_blob_config()
        self.connection_string = connection_string or config.get("connection_string")
        self.account = account or config.get("account")
        self.container = container or config.get("container")
        self.prefix = _normalize_prefix(prefix or config.get("prefix"))
        self.credential = credential or config.get("key") or config.get("sas_token")

        if not self.container:
            raise ValueError("Azure container is required. Set MFETHULS_AZURE_CONTAINER or pass container.")

        if service_client is not None:
            self.service_client = service_client
        elif self.connection_string:
            self.service_client = _get_blob_service_client().from_connection_string(self.connection_string)
        else:
            if not self.account:
                raise ValueError(
                    "Azure account is required. Set MFETHULS_AZURE_ACCOUNT or MFETHULS_AZURE_CONNECTION_STRING."
                )
            account_url = f"https://{self.account}.blob.core.windows.net"
            self.service_client = _get_blob_service_client()(account_url=account_url, credential=self.credential)

        self.container_client = self.service_client.get_container_client(self.container)

    def _blob_key(self, experiment: Experiment, suffix: str) -> str:
        base = _dataset_basename(experiment)
        filename = f"{base}{suffix}"
        return _join_storage_key(self.prefix, experiment.instrument_name, experiment.experiment_id, filename)

    def _blob_url(self, blob_key: str) -> str:
        account_name = self.account or self.service_client.account_name
        return f"https://{account_name}.blob.core.windows.net/{self.container}/{blob_key}"

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")
        parquet_path = self._blob_url(parquet_key)
        meta_path = self._blob_url(meta_key)
        return parquet_path, meta_path

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        parquet_key = self._blob_key(experiment, ".parquet")
        blob_client = self.container_client.get_blob_client(parquet_key)
        try:
            blob_client.get_blob_properties()
            return True
        except Exception:
            return False

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")
        parquet_path, meta_path = self.dataset_paths(experiment)

        parquet_buffer = io.BytesIO()
        dataset.data.to_parquet(parquet_buffer, index=False)
        parquet_buffer.seek(0)

        parquet_client = self.container_client.get_blob_client(parquet_key)
        parquet_client.upload_blob(parquet_buffer.getvalue(), overwrite=True)

        metadata_to_store = dict(dataset.metadata)
        metadata_to_store.setdefault("experiment_id", experiment.experiment_id)
        metadata_to_store.setdefault("sample_id", experiment.sample_id)
        metadata_to_store.setdefault("run_id", experiment.run_id)
        metadata_to_store.setdefault("instrument_name", experiment.instrument_name)
        metadata_to_store["provenance"] = _build_provenance_metadata(
            experiment,
            dataset,
            parquet_path,
            meta_path,
            storage_backend="azure_blob",
        )

        meta_body = json.dumps(metadata_to_store, default=_json_default).encode("utf8")
        meta_client = self.container_client.get_blob_client(meta_key)
        meta_client.upload_blob(meta_body, overwrite=True)

        return parquet_path, meta_path

    def load_dataset(self, experiment: Experiment) -> Dataset:
        parquet_key = self._blob_key(experiment, ".parquet")
        meta_key = self._blob_key(experiment, ".metadata.json")

        parquet_client = self.container_client.get_blob_client(parquet_key)
        try:
            parquet_bytes = parquet_client.download_blob().readall()
        except Exception as exc:
            raise FileNotFoundError(f"No stored dataset found at {self._blob_url(parquet_key)}") from exc

        data = pd.read_parquet(io.BytesIO(parquet_bytes))

        metadata: Dict[str, Any] = {}
        meta_client = self.container_client.get_blob_client(meta_key)
        try:
            metadata = json.loads(meta_client.download_blob().readall().decode("utf8"))
        except Exception:
            metadata = {}

        metadata.setdefault("experiment_id", experiment.experiment_id)
        metadata.setdefault("sample_id", experiment.sample_id)
        metadata.setdefault("run_id", experiment.run_id)
        metadata.setdefault("instrument_name", experiment.instrument_name)

        return Dataset(data=data, metadata=metadata)


class CombinedStorageBackend(DataStorageBackend):
    """Persist datasets to multiple backends while using one as canonical."""

    def __init__(self, primary: DataStorageBackend, secondary: DataStorageBackend) -> None:
        self.primary = primary
        self.secondary = secondary

    def dataset_paths(self, experiment: Experiment) -> Tuple[str, str]:
        return self.primary.dataset_paths(experiment)

    def dataset_in_storage(self, experiment: Experiment) -> bool:
        return self.primary.dataset_in_storage(experiment)

    def save_dataset(self, experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
        paths = self.primary.save_dataset(experiment, dataset)
        try:
            self.secondary.save_dataset(experiment, dataset)
        except Exception:
            pass
        return paths

    def load_dataset(self, experiment: Experiment) -> Dataset:
        return self.primary.load_dataset(experiment)


def dataset_paths(experiment: Experiment) -> Tuple[str, str]:
    return LocalParquetStorage().dataset_paths(experiment)


def dataset_in_storage(experiment: Experiment) -> bool:
    return LocalParquetStorage().dataset_in_storage(experiment)


def save_dataset_to_storage(experiment: Experiment, dataset: Dataset) -> Tuple[str, str]:
    return LocalParquetStorage().save_dataset(experiment, dataset)


def load_dataset_from_storage(experiment: Experiment) -> Dataset:
    return LocalParquetStorage().load_dataset(experiment)
