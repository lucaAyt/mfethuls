from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .config.loader import ingest_experiment_dataset
from .experiments import get_experiment, load_experiment_registry
from .storage.job_store import claim_next_job, get_job, update_job
from .storage import DuckDBQueryBackend, get_postgres_db_url

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if job is None:
        logger.warning("job_id=%s not found", job_id)
        return None

    registry_path = job.get("registry_storage_path")
    if not registry_path:
        logger.warning("job_id=%s missing registry_storage_path", job_id)
        return update_job(job_id, status="failed", message="missing registry_storage_path")

    try:
        logger.info("job_id=%s starting ingest", job_id)
        update_job(job_id, status="running", progress=5, message="reading registry")
        df = load_experiment_registry(registry_path)

        # Get list of registered experiment names
        experiment_names = df["name"].dropna().tolist()
        experiment_names = [str(name) for name in experiment_names]
        if not experiment_names:
            raise ValueError("load_experiments requires at least one experiment name.")

        storage_mode = (job.get("storage_mode") or "local").strip().lower()
        cloud_provider = job.get("cloud_provider")
        logger.info(
            "job_id=%s loaded registry rows=%d storage_mode=%s cloud_provider=%s",
            job_id,
            len(df.index),
            storage_mode,
            cloud_provider,
        )
        query_backend = DuckDBQueryBackend()
        try:
            return _process_job_ingest(
                job_id=job_id,
                experiment_names=experiment_names,
                registry_path=registry_path,
                storage_mode=storage_mode,
                cloud_provider=cloud_provider,
                query_backend=query_backend,
                db_url=get_postgres_db_url(),
            )
        finally:
            query_backend.close()
    except Exception as exc:  # pragma: no cover - worker level catch
        logger.exception("job_id=%s ingest failed", job_id)
        return update_job(job_id, status="failed", message=f"ingest failed: {exc}")


def _process_job_ingest(
    *,
    job_id: str,
    experiment_names: List[str],
    registry_path: str,
    storage_mode: str,
    cloud_provider: Optional[str],
    query_backend: DuckDBQueryBackend,
    db_url: Optional[str],
) -> Dict[str, Any]:
    dataset_results: List[Dict[str, Any]] = []

    total = max(len(experiment_names), 1)
    for idx, experiment_name in enumerate(experiment_names, start=1):
        try:
            if not experiment_name:
                raise ValueError("missing experiment name")
            exp = get_experiment(experiment_name)
            logger.info(
                "job_id=%s row=%d/%d processing experiment_id=%s instrument=%s",
                job_id,
                idx,
                total,
                exp.experiment_id,
                exp.instrument_name,
            )

            result = ingest_experiment_dataset(
                exp.name,
                use_storage=True,
                refresh=False,
                storage_mode=storage_mode,
                cloud_provider=cloud_provider,
                db_url=db_url,
                query_backend=query_backend,
            )
            status = (result or {}).get("status", "skipped")
            dataset_id = (result or {}).get("dataset_id")
            storage_path = (result or {}).get("storage_path")
            entry: Dict[str, Any] = {
                "experiment_id": exp.experiment_id,
                "status": status,
            }
            if dataset_id:
                entry["dataset_id"] = dataset_id
            if storage_path:
                entry["storage_path"] = storage_path
            dataset_results.append(entry)

            if status == "registered":
                logger.info(
                    "job_id=%s experiment_id=%s registered dataset_id=%s",
                    job_id,
                    exp.experiment_id,
                    dataset_id,
                )
            elif status == "persisted":
                logger.info(
                    "job_id=%s experiment_id=%s persisted dataset_id=%s",
                    job_id,
                    exp.experiment_id,
                    dataset_id,
                )
            elif status == "skipped":
                logger.info("job_id=%s experiment_id=%s skipped", job_id, exp.experiment_id)
            else:
                logger.warning(
                    "job_id=%s experiment_id=%s ingestion status=%s",
                    job_id,
                    exp.experiment_id,
                    status,
                )
        except Exception:
            logger.exception(
                "job_id=%s row=%d/%d failed experiment_id=%s",
                job_id,
                idx,
                total,
                experiment_name,
            )
            dataset_results.append(
                {
                    "experiment_id": experiment_name,
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
    logger.info("job_id=%s ingest completed registry_table=%s", job_id, registry_table)
    return get_job(job_id)


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
