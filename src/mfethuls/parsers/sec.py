import os
import re
import logging
from typing import Any, Dict, Optional

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.ingestion import collect_dataframe_from_paths
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)


@register_parser('sec', 'agilent')
class AgilentSec:
    def __init__(self, file_extension='.csv', delimiter=','):
        self.file_extension = file_extension
        self.delimiter = delimiter

    def parse(
        self,
        dict_paths,
        *,
        experiment_id: Optional[str] = None,
        sample_id: Optional[str] = None,
        run_id: Optional[str] = None,
        instrument_type: Optional[str] = None,
        instrument_model: Optional[str] = None,
        instrument_name: Optional[str] = None,
        experiment_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Parse Agilent SEC data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="SEC",
        )

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="sec",
            instrument_model=instrument_model or "agilent",
        )

        if "experiment_id" not in df.columns:
            df["experiment_id"] = experiment_id
        if sample_id is not None and "sample_id" not in df.columns:
            df["sample_id"] = sample_id
        if run_id is not None and "run_id" not in df.columns:
            df["run_id"] = run_id

        meta: Dict[str, Any] = {
            "schema_version": schema_report.get("schema_version", "1.0"),
            "experiment_id": experiment_id,
            "sample_id": sample_id,
            "run_id": run_id,
            "instrument_type": instrument_type,
            "instrument_model": instrument_model,
            "instrument_name": instrument_name,
            "experiment_name": experiment_name,
            "schema_normalization": schema_report,
        }
        if metadata:
            meta.update(metadata)

        return Dataset(data=df, metadata=meta)

    def parse_raw_data(self, path):
        df = pd.read_csv(path, sep=self.delimiter, names=['time (min)', 'value'], header=None) \
               .apply(pd.to_numeric, errors='coerce')
        name = f'{os.path.basename(os.path.normpath(path)).casefold().rstrip(self.file_extension)}'.replace('.dx_', '_')
        detector_name = self._infer_detector_name(path)
        df.loc[:, 'name'] = [name] * df.shape[0]
        df.loc[:, 'detector_name'] = [detector_name] * df.shape[0]
        df.loc[:, 'source_file'] = [os.path.basename(path)] * df.shape[0]

        return df

    # TODO: Fix to pick up current detectors
    @staticmethod
    def _infer_detector_name(path: str) -> str:
        """Infer a canonical detector name from a SEC filename."""

        stem = os.path.basename(path).casefold()
        normalized = re.sub(r"[^a-z0-9]+", "_", stem)

        # Allow trailing alphanumeric suffixes (e.g. RID1A, VWD1A) when matching
        detector_patterns = {
            "ri": [r"(?:^|_)ri(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)refractive(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)refractiveindex(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)dri(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)rid(?:[0-9a-z]+)?(?:_|$)"],
            "uv": [r"(?:^|_)uv(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)uvvis(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)dad(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)vwd(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)pda(?:[0-9a-z]+)?(?:_|$)"],
            "ls": [r"(?:^|_)ls(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)lightscattering(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)mals(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)rals(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)lals(?:[0-9a-z]+)?(?:_|$)"],
            "viscometer": [r"(?:^|_)visc(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)viscometer(?:[0-9a-z]+)?(?:_|$)", r"(?:^|_)dp(?:[0-9a-z]+)?(?:_|$)"],
        }

        for detector, patterns in detector_patterns.items():
            if any(re.search(pattern, normalized) for pattern in patterns):
                return detector

        return "unknown"
