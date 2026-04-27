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


# TODO: Add inference from measurment_profile in registry (mapping)
def _infer_dma_profile_from_columns(df: pd.DataFrame) -> Optional[str]:
    """Infer a DMA measurement profile from available raw column names."""

    column_text = " ".join(str(column).lower() for column in df.columns)
    if not column_text.strip():
        return None

    if any(token in column_text for token in ("freq", "frequency", "hz")):
        return "oscillatory_frequency_sweep"
    if any(token in column_text for token in ("strain", "amplitude")):
        return "oscillatory_strain_sweep"
    if any(token in column_text for token in ("temp", "temperature")):
        return "oscillatory_temperature_sweep"
    if any(token in column_text for token in ("time", "t [s]")):
        return "oscillatory_time_sweep"

    return None


@register_parser('dma', 'ta_q800')
class DmaTaQ800:
    def __init__(self, file_extension='.txt', parse_char_start='StartOfData', parse_char_end='Shiiit', delimiter='\t'):
        self.file_extension = file_extension
        self.parse_char_start = parse_char_start
        self.parse_char_end = parse_char_end
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
        measurement_profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Parse DMA TA Q800 data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="DMA",
        )

        if experiment_id is None:
            return df

        metadata_profile = (metadata or {}).get("measurement_profile")
        measurement_profile = measurement_profile or metadata_profile or _infer_dma_profile_from_columns(df)

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="dma",
            instrument_model=instrument_model or "ta_q800",
            measurement_profile=measurement_profile,
        )

        if "experiment_id" not in df.columns:
            df["experiment_id"] = experiment_id
        if sample_id is not None and "sample_id" not in df.columns:
            df["sample_id"] = sample_id
        if run_id is not None and "run_id" not in df.columns:
            df["run_id"] = run_id

        meta: Dict[str, Any] = dict(metadata or {})
        meta.update(
            {
                "schema_version": schema_report.get("schema_version", "1.0"),
                "experiment_id": experiment_id,
                "sample_id": sample_id,
                "run_id": run_id,
                "instrument_type": instrument_type,
                "instrument_model": instrument_model,
                "instrument_name": instrument_name,
                "experiment_name": experiment_name,
                "measurement_profile": measurement_profile,
                "schema_normalization": schema_report,
            }
        )

        return Dataset(data=df, metadata=meta)

    def parse_raw_data(self, path):

        pattern_start = re.compile(self.parse_char_start)
        pattern_end = re.compile(self.parse_char_end)

        # Specific for DMAQ800 - pull out signal\column names
        pattern_column_name = re.compile('Sig\d')

        lines = []
        column_names = []
        with open(path) as f:
            take = False
            for line in f.readlines():

                # Match signal name - this could break if line empty (edgecase)
                if pattern_column_name.match(line):
                    column_names.append(re.split(self.delimiter, line.strip(), maxsplit=2)[1].casefold())

                if take:
                    l = re.split(self.delimiter, line.strip())
                    lines.append(l)

                if pattern_start.match(line):
                    take = True

                elif pattern_end.match(line):
                    take = False

        if not column_names or not lines:
            return pd.DataFrame()

        # Make up columns by combining 1st and 2nd lines
        df = pd.DataFrame(lines, columns=column_names).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        return df
