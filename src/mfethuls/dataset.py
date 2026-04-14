from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class Dataset:
    """Core data container: tabular data + metadata.

    - `data` holds the measurements as a pandas DataFrame.
    - `metadata` holds context (ids, instrument info, provenance, etc.).
    """

    data: pd.DataFrame
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def schema_version(self) -> str:
        return str(self.metadata.get("schema_version", "1.0"))

    @property
    def experiment_ids(self) -> List[str]:
        ids = self.metadata.get("experiment_ids")
        if isinstance(ids, list):
            return [str(x) for x in ids]
        experiment_id = self.metadata.get("experiment_id")
        return [str(experiment_id)] if experiment_id is not None else []

    @property
    def sample_ids(self) -> List[str]:
        ids = self.metadata.get("sample_ids")
        if isinstance(ids, list):
            return [str(x) for x in ids if x is not None]
        sample_id = self.metadata.get("sample_id")
        return [str(sample_id)] if sample_id is not None else []

    @property
    def experiment_id(self) -> Optional[str]:
        # convenience accessor when there is a single experiment id
        if "experiment_id" in self.metadata:
            return str(self.metadata["experiment_id"])
        ids = self.experiment_ids
        return ids[0] if ids else None

    @property
    def sample_id(self) -> Optional[str]:
        if "sample_id" in self.metadata:
            return str(self.metadata["sample_id"])
        ids = self.sample_ids
        return ids[0] if ids else None
