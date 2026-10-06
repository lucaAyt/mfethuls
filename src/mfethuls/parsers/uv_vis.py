import os
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from dateutil.parser import parse
from dateutil.tz import gettz, UTC

from mfethuls.dataset import Dataset
from mfethuls.parsers.ingestion import collect_dataframe_from_paths
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)


@register_parser('uv_vis', 'flame')
@register_parser('fluorescence', 'flame')
class FlameOceanOpticsParser:
    def __init__(self, file_extension='.txt'):
        self.file_extension = file_extension

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
        """Parse in-situ UV-Vis or fluorescence data from Ocean Optics Flame.

        The raw signal column is named ``intensity``; the schema of the
        instrument type gives it its meaning (``transmittance_pct`` for
        uv_vis, ``emission_counts`` for fluorescence).

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="Flame",
        )

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type=instrument_type or "uv_vis",
            instrument_model=instrument_model or "flame",
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
        # Get milliseconds from timestamp in filename if data was saved with timestamp suffix
        filenname_suffix = Path(path).stem.split('_')[-1]
        milliseconds = timedelta(milliseconds=float(filenname_suffix.split('-')[-1])) if '-' in filenname_suffix \
            else timedelta(0)

        timestamp = None
        with open(path) as file:
            for line in file:
                if line.startswith('Date'):
                    timestamp = line.split(': ')[-1].strip()
                if 'Number of Pixels' in line:
                    break
            df = pd.read_csv(file, sep='\t', header=1)

        if df.shape[1] < 2:
            return pd.DataFrame()

        df = df.iloc[:, :2]
        df.columns = ['wavelength (nm)', 'intensity']
        df.loc[:, 'timestamp'] = handle_tz(timestamp) + milliseconds if timestamp else pd.NaT

        # Add name of experiment
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.dirname(path))}'] * df.shape[0]

        return df


@register_parser('uv_vis', 'Shimadzu')
class ShimadzuUVVisParser:
    def __init__(self, file_extension='.txt'):
        self.file_extension = file_extension

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
        """Parse Shimadzu UV-Vis data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="Shimadzu UV",
        )

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="uv_vis",
            instrument_model=instrument_model or "Shimadzu",
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
        df = pd.read_csv(path, header=1, sep='\t').apply(pd.to_numeric, errors='coerce')

        # Additional 'meta' data: You can use underscore for titration meta data. Delete post if not needed in output
        titrant_info = Path(path).stem.split('_')[-1].lstrip('0')
        df.loc[:, 'titrant'] = titrant_info if not titrant_info == '' else '0'  # I DNA
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.dirname(path))}'] * df.shape[0]

        return df


def handle_tz(ts: str):
    tzinfos = {"CET": gettz("Europe/Zurich"), "CEST": gettz("Europe/Zurich")}
    timestamp_eu = parse(ts, tzinfos=tzinfos)
    return pd.to_datetime(timestamp_eu.astimezone(UTC).isoformat())
