from __future__ import annotations

import io
import tempfile
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


class _FakePostgresResult:
    def __init__(self, row_id: int = 77) -> None:
        self._row = (row_id,)

    def fetchone(self):
        return self._row


class _FakePostgresConnection:
    def __init__(self, statements: list[tuple[str, object | None]]) -> None:
        self._statements = statements

    def execute(self, statement, params=None):  # noqa: ANN001
        self._statements.append((str(statement), params))
        if "RETURNING id" in str(statement):
            return _FakePostgresResult()
        return _FakePostgresResult()

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False


class _FakePostgresEngine:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object | None]] = []

    def connect(self):
        return _FakePostgresConnection(self.statements)


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
        SimpleNamespace(client=lambda service_name, **kwargs: fake_client),
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
        SimpleNamespace(client=lambda service_name, **kwargs: fake_client),
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


def test_storage_manager_records_both_local_and_cloud_locations(monkeypatch):
    fake_client = _FakeS3Client()
    monkeypatch.setattr(
        storage_module,
        "boto3",
        SimpleNamespace(client=lambda service_name, **kwargs: fake_client),
    )
    monkeypatch.setattr(storage_module, "ClientError", _FakeClientError)
    monkeypatch.setenv("MFETHULS_S3_BUCKET", "combo-bucket")
    monkeypatch.setenv("MFETHULS_S3_PREFIX", "combo")
    monkeypatch.setenv("MFETHULS_S3_REGION", "us-east-1")

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", tmpdir)

        cloud_backend = S3ParquetStorage()
        local_backend = storage_module.LocalParquetStorage()
        combined_backend = storage_module.CombinedStorageBackend(primary=cloud_backend, secondary=local_backend)
        metadata_backend = _RecordingMetadataBackend()
        manager = StorageManager(data_backend=combined_backend, metadata_backend=metadata_backend)

        experiment = _build_experiment()
        dataset = _build_dataset()

        parquet_path, meta_path, dataset_id = manager.save_and_persist(experiment, dataset)

        assert parquet_path.startswith("s3://combo-bucket/")
        assert meta_path.startswith("s3://combo-bucket/")
        assert dataset_id == 101
        persisted = metadata_backend.metadata[0]
        assert persisted["storage_path"] == parquet_path
        assert persisted["cloud_storage_path"] == parquet_path
        assert persisted["local_storage_path"] is not None
        assert persisted["local_storage_path"].startswith(tmpdir)


def test_postgres_metadata_backend_upserts_dataset_rows(monkeypatch):
    fake_engine = _FakePostgresEngine()
    monkeypatch.setattr(storage_module, "create_engine", lambda db_url: fake_engine)

    backend = storage_module.PostgresMetadataBackend("postgresql://example")
    metadata = storage_module.DatasetMetadata(
        experiment_id="EXP900",
        sample_id="S900",
        run_id="R900",
        experiment_name="cloud_roundtrip_exp",
        instrument_name="uv_vis",
        instrument_type="uv_vis",
        instrument_model="generic",
        dataset_name="EXP900_S900_R900",
        storage_path="s3://bucket/datasets/uv_vis/EXP900/EXP900_S900_R900.parquet",
        local_storage_path="/tmp/local/uv_vis/EXP900/EXP900_S900_R900.parquet",
        cloud_storage_path="s3://bucket/datasets/uv_vis/EXP900/EXP900_S900_R900.parquet",
        storage_format="parquet",
        rows=3,
        cols=2,
        schema_version="1.0",
        measurement_profile="profile-a",
        schema_normalization={"schema_applied": True},
        mfethuls_version="0.0.13",
        provenance={"storage": {"backend": "s3"}},
    )

    row_id = backend.persist_metadata(metadata)

    assert row_id == 77
    insert_sql = next(sql for sql, _ in fake_engine.statements if sql.startswith("INSERT INTO datasets"))
    assert "ON CONFLICT (experiment_id, dataset_name) DO UPDATE SET" in insert_sql
    assert "updated_at = now()" in insert_sql
    assert "local_storage_path" in insert_sql
    assert "cloud_storage_path" in insert_sql
    inserted_params = next(params for sql, params in fake_engine.statements if sql.startswith("INSERT INTO datasets"))
    assert inserted_params["storage_path"].startswith("s3://bucket/")
    assert inserted_params["local_storage_path"].startswith("/tmp/local/")
