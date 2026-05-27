import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from mfethuls import factory
from mfethuls.config.loader import load_experiment_dataset
from mfethuls.experiments import load_experiment_registry


def _load_test_env_paths() -> tuple[str, str, str]:
    """Load real-data test paths from .env and return normalized strings."""

    # Load .env from repository root if present.
    load_dotenv()

    data_root = os.getenv("MFETHULS_TEST_DATA_ROOT")
    registry_path = os.getenv("MFETHULS_TEST_REGISTRY")
    local_storage = os.getenv("MFETHULS_TEST_LOCAL_STORAGE")

    if not data_root or not registry_path or not local_storage:
        pytest.skip(
            "Real-data test paths are not configured. Set MFETHULS_TEST_DATA_ROOT, "
            "MFETHULS_TEST_REGISTRY and MFETHULS_TEST_LOCAL_STORAGE in .env."
        )

    return data_root.strip(), registry_path.strip(), local_storage.strip()


@pytest.fixture()
def real_data_config(monkeypatch):
    """Configure mfethuls runtime to use real-data test paths from .env."""

    data_root, registry_path, local_storage = _load_test_env_paths()

    if not Path(data_root).exists():
        pytest.skip(f"MFETHULS_TEST_DATA_ROOT does not exist: {data_root}")
    if not Path(registry_path).exists():
        pytest.skip(f"MFETHULS_TEST_REGISTRY does not exist: {registry_path}")

    # Point runtime environment to dedicated testing paths.
    monkeypatch.setenv("PATH_TO_DATA", data_root)
    monkeypatch.setenv("PATH_TO_REGISTRY", registry_path)
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", local_storage)
    monkeypatch.setenv("MFETHULS_DISABLE_STORAGE", "0")

    # factory.DATA_ROOT_PATH is initialized at import-time, so keep it aligned.
    factory.DATA_ROOT_PATH = data_root

    return data_root, registry_path, local_storage


def test_real_registry_loads(real_data_config):
    """The real registry should be readable and contain required columns."""

    _, registry_path, _ = real_data_config
    df_registry = load_experiment_registry(registry_path)

    assert not df_registry.empty
    assert "name" in df_registry.columns
    assert "experiment_id" in df_registry.columns
    assert "instrument_name" in df_registry.columns


def test_real_data_parse_and_cache_pipeline(real_data_config):
    """Smoke test the end-to-end parse + local cache pipeline on real data.

    This intentionally checks that at least one experiment can be parsed and
    cached using real data. Individual experiments may still fail due to
    missing files or partial datasets.
    """

    _, registry_path, local_storage = real_data_config
    df_registry = load_experiment_registry(registry_path)

    if "status" in df_registry.columns:
        selected_names = df_registry[df_registry["status"] == "to_analyse"]["name"].tolist()
    else:
        selected_names = df_registry["name"].tolist()

    if not selected_names:
        pytest.skip("No experiments selected from real registry.")

    successes = []
    failures = []

    for name in selected_names:
        try:
            # Fresh parse from raw data and persist to local storage.
            ds = load_experiment_dataset(name, use_storage=True, refresh=True)
            assert ds.experiment_id is not None
            assert not ds.data.empty

            # Cache load path should also work after write.
            ds_cached = load_experiment_dataset(name, use_storage=True, refresh=False)
            assert ds_cached.experiment_id == ds.experiment_id
            assert not ds_cached.data.empty
            successes.append(name)
        except Exception as exc:  # noqa: BLE001
            failures.append((name, repr(exc)))

    # In real-world fixtures, some experiments may be incomplete; require at
    # least one successful full parse/cache cycle to validate the pipeline.
    assert successes, (
        "No real-data experiment could complete parse+cache pipeline. "
        f"Failures: {failures}"
    )

    assert Path(local_storage).exists()
