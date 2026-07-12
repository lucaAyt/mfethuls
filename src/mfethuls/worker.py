from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .config.loader import ingest_experiment_dataset
from .experiments import clear_experiment_registry, get_experiment, load_experiment_registry
from .storage.job_store import claim_next_job, get_job, update_job
from .storage import DuckDBQueryBackend, get_postgres_db_url

logger = logging.getLogger(__name__)

_JOB_TIMEOUT_SECONDS = int(os.environ.get("MFETHULS_JOB_TIMEOUT_SECONDS", "1800"))


def process_job(job_id: str) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if job is None:
        logger.warning("job_id=%s not found", job_id)
        return None

    job_registry_path = job.get("job_registry_storage_path")
    if not job_registry_path:
        logger.warning("job_id=%s missing job_registry_storage_path", job_id)
        return update_job(job_id, status="failed", message="missing job_registry_storage_path")

    try:
        logger.info("job_id=%s starting ingest", job_id)
        update_job(job_id, status="running", progress=5, message="reading registry")
        clear_experiment_registry()
        df = load_experiment_registry()

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
        return _process_job_ingest(
            job_id=job_id,
            experiment_names=experiment_names,
            job_registry_path=job_registry_path,
            storage_mode=storage_mode,
            cloud_provider=cloud_provider,
            db_url=get_postgres_db_url(),
            refresh=bool(job.get("refresh", False)),
        )
    except Exception as exc:  # pragma: no cover - worker level catch
        logger.exception("job_id=%s ingest failed", job_id)
        return update_job(job_id, status="failed", message=f"ingest failed: {exc}")


def _process_job_ingest(
    *,
    job_id: str,
    experiment_names: List[str],
    job_registry_path: str,
    storage_mode: str,
    cloud_provider: Optional[str],
    db_url: Optional[str],
    refresh: bool = False,
) -> Dict[str, Any]:
    dataset_results: List[Dict[str, Any]] = []
    # Collect Parquet paths during parsing; DuckDB registration happens in one
    # brief write window at the end so we don't hold an exclusive lock while
    # parsing (which can take minutes for large registries).
    parquet_paths: List[Dict[str, Any]] = []

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

            # No query_backend here — Parquet files are written, Postgres metadata
            # is persisted, but DuckDB view registration is deferred to the batch
            # step below so the write lock is held for milliseconds, not minutes.
            result = ingest_experiment_dataset(
                exp.name,
                use_storage=True,
                refresh=refresh,
                storage_mode=storage_mode,
                cloud_provider=cloud_provider,
                db_url=db_url,
                query_backend=None,
            )
            status = (result or {}).get("status", "skipped")
            storage_path = (result or {}).get("storage_path")
            entry: Dict[str, Any] = {
                "experiment_id": exp.experiment_id,
                "status": status,
            }
            if storage_path:
                entry["storage_path"] = storage_path
                from mfethuls.storage.config import _view_basename
                parquet_paths.append({
                    "storage_path": storage_path,
                    "experiment_id": exp.experiment_id,
                    "view_name": _view_basename(exp),
                    "experiment_name": exp.name,
                    "raw_data_filename": getattr(exp, "raw_data_filename", None),
                })

            dataset_results.append(entry)

            if status in ("registered", "persisted"):
                logger.info("job_id=%s experiment_id=%s status=%s", job_id, exp.experiment_id, status)
            elif status == "skipped":
                logger.info("job_id=%s experiment_id=%s skipped", job_id, exp.experiment_id)
            else:
                logger.warning("job_id=%s experiment_id=%s ingestion status=%s", job_id, exp.experiment_id, status)
        except Exception:
            logger.exception(
                "job_id=%s row=%d/%d failed experiment_id=%s",
                job_id,
                idx,
                total,
                experiment_name,
            )
            dataset_results.append({"experiment_id": experiment_name, "status": "failed"})

        progress = int((idx / total) * 90)
        update_job(job_id, progress=progress)

    # Brief write window: open DuckDB once, batch-register all Parquet files,
    # then close immediately. API and Streamlit readers are blocked only during this.
    try:
        with DuckDBQueryBackend() as qb:
            for item in parquet_paths:
                try:
                    view_name = qb.register_parquet(
                        item["storage_path"],
                        table_name=item["view_name"],
                        experiment_name=item["experiment_name"],
                        raw_data_filename=item["raw_data_filename"],
                    )
                    for entry in dataset_results:
                        if entry.get("storage_path") == item["storage_path"]:
                            entry["dataset_id"] = view_name
                    logger.info(
                        "job_id=%s experiment_id=%s registered view=%s",
                        job_id, item["experiment_id"], view_name,
                    )
                except Exception:
                    logger.warning("job_id=%s failed to register %s in DuckDB", job_id, item["storage_path"])
    except Exception:
        logger.exception("job_id=%s DuckDB batch registration failed", job_id)

    update_job(
        job_id,
        progress=100,
        status="completed",
        message="ingest completed",
        datasets=dataset_results,
    )
    logger.info("job_id=%s ingest completed", job_id)
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
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(process_job, job_id)
                try:
                    future.result(timeout=_JOB_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    logger.error(
                        "job_id=%s timed out after %ds", job_id, _JOB_TIMEOUT_SECONDS
                    )
                    update_job(
                        job_id,
                        status="failed",
                        message=f"job timed out after {_JOB_TIMEOUT_SECONDS}s",
                    )
            processed += 1

        if max_jobs is not None and processed >= max_jobs:
            return
