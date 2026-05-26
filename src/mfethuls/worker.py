from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from .config_loader import _build_data_backend, load_experiment_dataset
from .experiments import _normalize_optional_str, register_experiment
from .job_store import claim_next_job, get_job, update_job
from .registry_validator import RegistryValidator
from .storage import DuckDBQueryBackend, get_postgres_db_url


def _load_registry(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Registry file not found: {path}")
    return pd.read_parquet(path)


def process_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if job is None:
        return None

    registry_path = job.get("registry_storage_path")
    if not registry_path:
        return update_job(job_id, status="failed", message="missing registry_storage_path")

    try:
        update_job(job_id, status="running", progress=5, message="reading registry")
        df = _load_registry(registry_path)

        storage_mode = (job.get("storage_mode") or "local").strip().lower()
        cloud_provider = job.get("cloud_provider")
        data_backend = _build_data_backend(storage_mode, cloud_provider)
        query_backend = DuckDBQueryBackend()
        db_url = get_postgres_db_url()
        dataset_results: List[Dict[str, Any]] = []

        from .experiments import Experiment

        total = max(len(df.index), 1)
        for idx, rec in enumerate(df.to_dict(orient="records"), start=1):
            name = rec.get("name")
            experiment_id = rec.get("experiment_id")
            instrument_name = _normalize_optional_str(rec.get("instrument_name"))
            sample_id = _normalize_optional_str(rec.get("sample_id"))
            run_id = _normalize_optional_str(rec.get("run_id")) or "R001"
            metadata = {
                k: v
                for k, v in rec.items()
                if k
                not in {
                    "name",
                    "experiment_id",
                    "instrument_name",
                    "sample_id",
                    "run_id",
                    "description",
                    "measurement_profile",
                }
            }

            try:
                validated_experiment_id = RegistryValidator.validate_experiment_id(experiment_id)
                exp = Experiment(
                    name=name,
                    experiment_id=validated_experiment_id,
                    instrument_name=instrument_name,
                    sample_id=sample_id,
                    run_id=run_id,
                    metadata=metadata,
                )
                register_experiment(exp)

                if data_backend.dataset_in_storage(exp):
                    parquet_path, _ = data_backend.dataset_paths(exp)
                    dataset_id = query_backend.register_parquet(parquet_path)
                    dataset_results.append(
                        {
                            "experiment_id": exp.experiment_id,
                            "dataset_id": dataset_id,
                            "storage_path": parquet_path,
                            "status": "registered",
                        }
                    )
                else:
                    dataset = load_experiment_dataset(
                        exp.name,
                        use_storage=True,
                        refresh=False,
                        storage_mode=storage_mode,
                        cloud_provider=cloud_provider,
                        db_url=db_url,
                        query_backend=query_backend,
                    )
                    if dataset is None:
                        dataset_results.append(
                            {
                                "experiment_id": exp.experiment_id,
                                "status": "skipped",
                            }
                        )
                    else:
                        parquet_path, _ = data_backend.dataset_paths(exp)
                        dataset_id = query_backend.register_parquet(parquet_path)
                        dataset_results.append(
                            {
                                "experiment_id": exp.experiment_id,
                                "dataset_id": dataset_id,
                                "storage_path": parquet_path,
                                "status": "persisted",
                            }
                        )
            except Exception:
                dataset_results.append(
                    {
                        "experiment_id": experiment_id,
                        "status": "failed",
                    }
                )

            progress = int((idx / total) * 90)
            update_job(job_id, progress=progress)

        registry_table = query_backend.register_parquet(
            registry_path,
            table_name=f"registry_{job_id}",
            overwrite=True,
        )

        update_job(
            job_id,
            progress=100,
            status="completed",
            message="ingest completed",
            datasets=dataset_results,
            registry_table=registry_table,
        )
        return get_job(job_id)
    except Exception as exc:  # pragma: no cover - worker level catch
        return update_job(job_id, status="failed", message=f"ingest failed: {exc}")


def run_worker(poll_interval: float = 2.0, max_jobs: Optional[int] = None) -> None:
    processed = 0
    while True:
        job = claim_next_job()
        if job is None:
            time.sleep(poll_interval)
            continue

        job_id = job.get("job_id")
        if job_id:
            process_job(job_id)
            processed += 1

        if max_jobs is not None and processed >= max_jobs:
            return
