from __future__ import annotations

import io
from types import SimpleNamespace

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
import mfethuls.storage as storage_module
from mfethuls.storage import AzureBlobParquetStorage, S3ParquetStorage, StorageManager


class _FakeClientError(Exception):
    pass


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, **kwargs):  # noqa: N803
        _ = kwargs
        if hasattr(Body, "read"):
            data = Body.read()
        else:
            data = Body
        if isinstance(data, str):
            data = data.encode("utf8")
        self.objects[(Bucket, Key)] = bytes(data)

    def head_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError(f"missing object: {Bucket}/{Key}")

    def get_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise _FakeClientError(f"missing object: {Bucket}/{Key}")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class _FakeBlobDownload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def readall(self) -> bytes:
        return self._data


class _FakeBlobClient:
    def __init__(self, storage: dict[str, bytes], key: str) -> None:
        self._storage = storage
        self._key = key

    def upload_blob(self, data, overwrite=True, **kwargs):  # noqa: ANN001, D417
        _ = overwrite, kwargs
        if hasattr(data, "read"):
            payload = data.read()
        else:
            payload = data
        if isinstance(payload, str):
            payload = payload.encode("utf8")
        self._storage[self._key] = bytes(payload)

    def get_blob_properties(self):
        if self._key not in self._storage:
            raise _FakeClientError(f"missing blob: {self._key}")
        return {"name": self._key}

    def download_blob(self):
        if self._key not in self._storage:
            raise _FakeClientError(f"missing blob: {self._key}")
        return _FakeBlobDownload(self._storage[self._key])


class _FakeContainerClient:
    def __init__(self, storage: dict[str, bytes], container: str) -> None:
        self._storage = storage
        self._container = container

    def get_blob_client(self, key: str) -> _FakeBlobClient:
        _ = self._container
        return _FakeBlobClient(self._storage, key)


class _FakeBlobServiceClient:
    def __init__(self, account_url: str | None = None, credential: str | None = None) -> None:
        _ = credential
        self.account_name = "fakeaccount"
        if account_url:
            host = account_url.split("//", 1)[-1]
            self.account_name = host.split(".", 1)[0]
        self._storage: dict[str, bytes] = {}

    @classmethod
    def from_connection_string(cls, connection_string: str):
        _ = connection_string
        return cls(account_url="https://fakeaccount.blob.core.windows.net")

    def get_container_client(self, container: str) -> _FakeContainerClient:
        return _FakeContainerClient(self._storage, container)


class _RecordingMetadataBackend:
    def __init__(self) -> None:
        self.metadata: list[dict[str, object]] = []

    def persist_metadata(self, metadata):
        self.metadata.append(metadata)
        return 101


def _build_experiment() -> Experiment:
    return Experiment(
        name="cloud_roundtrip_exp",
        experiment_id="EXP900",
        instrument_name="uv_vis",
        sample_id="S900",
        run_id="R900",
    )


def _build_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "wavelength_nm": [200.0, 210.0, 220.0],
            "absorbance": [0.1, 0.2, 0.3],
            "source_file": ["scan_a.csv", "scan_a.csv", "scan_b.csv"],
        }
    )
    return Dataset(
        data=frame,
        metadata={
            "key": "value",
            "instrument_type": "uv_vis",
            "instrument_model": "generic",
            "schema_version": "1.0",
            "schema_normalization": {
                "schema_applied": True,
                "warnings": [],
                "missing_required_columns": [],
            },
        },
    )


def test_s3_parquet_storage_roundtrip(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(
        storage_module,
        "boto3",
        SimpleNamespace(client=lambda service_name, region_name=None: fake_client),
    )
    monkeypatch.setattr(storage_module, "ClientError", _FakeClientError)
    monkeypatch.setenv("MFETHULS_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("MFETHULS_S3_PREFIX", "datasets")
    monkeypatch.setenv("MFETHULS_S3_REGION", "us-east-1")

    backend = S3ParquetStorage()
    experiment = _build_experiment()
    dataset = _build_dataset()

    parquet_path, meta_path = backend.save_dataset(experiment, dataset)

    assert parquet_path == "s3://test-bucket/datasets/uv_vis/EXP900/EXP900_S900_R900.parquet"
    assert meta_path == "s3://test-bucket/datasets/uv_vis/EXP900/EXP900_S900_R900.metadata.json"
    assert backend.dataset_in_storage(experiment) is True

    loaded = backend.load_dataset(experiment)
    assert loaded.data.equals(dataset.data)
    assert loaded.metadata["key"] == "value"
    assert loaded.metadata["provenance"]["storage"]["backend"] == "s3"
    assert loaded.metadata["provenance"]["storage"]["parquet_path"] == parquet_path


def test_azure_blob_parquet_storage_roundtrip(monkeypatch):
    monkeypatch.setattr(storage_module, "BlobServiceClient", _FakeBlobServiceClient)
    monkeypatch.setenv("MFETHULS_AZURE_CONTAINER", "test-container")
    monkeypatch.setenv("MFETHULS_AZURE_PREFIX", "datasets")
    monkeypatch.setenv("MFETHULS_AZURE_ACCOUNT", "fakeaccount")

    service_client = _FakeBlobServiceClient(account_url="https://fakeaccount.blob.core.windows.net")
    backend = AzureBlobParquetStorage(service_client=service_client)
    experiment = _build_experiment()
    dataset = _build_dataset()

    parquet_path, meta_path = backend.save_dataset(experiment, dataset)

    assert parquet_path == "https://fakeaccount.blob.core.windows.net/test-container/datasets/uv_vis/EXP900/EXP900_S900_R900.parquet"
    assert meta_path == "https://fakeaccount.blob.core.windows.net/test-container/datasets/uv_vis/EXP900/EXP900_S900_R900.metadata.json"
    assert backend.dataset_in_storage(experiment) is True

    loaded = backend.load_dataset(experiment)
    assert loaded.data.equals(dataset.data)
    assert loaded.metadata["key"] == "value"
    assert loaded.metadata["provenance"]["storage"]["backend"] == "azure_blob"
    assert loaded.metadata["provenance"]["storage"]["parquet_path"] == parquet_path


def test_storage_manager_uses_new_metadata_workflow(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(
        storage_module,
        "boto3",
        SimpleNamespace(client=lambda service_name, region_name=None: fake_client),
    )
    monkeypatch.setattr(storage_module, "ClientError", _FakeClientError)
    monkeypatch.setenv("MFETHULS_S3_BUCKET", "manager-bucket")
    monkeypatch.setenv("MFETHULS_S3_PREFIX", "managed")

    backend = S3ParquetStorage()
    metadata_backend = _RecordingMetadataBackend()
    manager = StorageManager(data_backend=backend, metadata_backend=metadata_backend)

    experiment = _build_experiment()
    dataset = _build_dataset()

    parquet_path, meta_path, dataset_id = manager.save_and_persist(experiment, dataset)

    assert parquet_path.endswith(".parquet")
    assert meta_path.endswith(".metadata.json")
    assert dataset_id == 101
    assert len(metadata_backend.metadata) == 1
    persisted = metadata_backend.metadata[0]
    assert persisted["storage_path"] == parquet_path
    assert persisted["provenance"]["storage"]["backend"] == "s3"
    assert persisted["provenance"]["storage"]["parquet_path"] == parquet_path
