"""The dataset catalog record: one row per ingested dataset in DuckDB ``dataset_registry``.

The catalog is derived data, rebuilt on each ingest from the owners of each fact:
the registry (descriptive fields), the manifest (``experiment_id``) and the parsed
dataset (instrument type/model, canonical measurement profile, row count). The app,
the API ``/datasets`` endpoint and ``storage.notebook`` read only the catalog; the
optional Postgres ``datasets`` table is written from the same record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

from .config import _view_basename

# Catalog columns besides table_name, storage_path and registered_at, with DuckDB types.
CATALOG_FIELDS: dict[str, str] = {
    "experiment_id": "TEXT",
    "experiment_name": "TEXT",
    "raw_data_filename": "TEXT",
    "instrument_name": "TEXT",
    "instrument_type": "TEXT",
    "instrument_model": "TEXT",
    "sample_id": "TEXT",
    "run_id": "TEXT",
    "measurement_profile": "TEXT",
    "rows": "BIGINT",
}


@dataclass(frozen=True)
class CatalogRecord:
    table_name: str
    storage_path: str
    experiment_id: Optional[str] = None
    experiment_name: Optional[str] = None
    raw_data_filename: Optional[str] = None
    instrument_name: Optional[str] = None
    instrument_type: Optional[str] = None
    instrument_model: Optional[str] = None
    sample_id: Optional[str] = None
    run_id: Optional[str] = None
    measurement_profile: Optional[str] = None
    rows: Optional[int] = None

    @classmethod
    def build(
        cls,
        experiment,
        storage_path: str,
        *,
        dataset_metadata: Optional[Mapping[str, Any]] = None,
        rows: Optional[int] = None,
    ) -> "CatalogRecord":
        """Record for ``experiment`` stored at ``storage_path``.

        ``dataset_metadata`` is the parsed dataset's metadata (or its sidecar), which
        holds the instrument type and model and the canonical measurement profile.
        """

        metadata = dataset_metadata or {}
        return cls(
            table_name=_view_basename(experiment),
            storage_path=storage_path,
            experiment_id=experiment.experiment_id,
            experiment_name=experiment.name,
            raw_data_filename=experiment.raw_data_filename,
            instrument_name=experiment.instrument_name,
            instrument_type=metadata.get("instrument_type"),
            instrument_model=metadata.get("instrument_model"),
            sample_id=experiment.sample_id,
            run_id=experiment.run_id,
            measurement_profile=metadata.get("measurement_profile"),
            rows=rows,
        )

    def fields(self) -> dict[str, Any]:
        """The catalog columns (everything except table_name and storage_path)."""

        values = asdict(self)
        return {name: values[name] for name in CATALOG_FIELDS}
