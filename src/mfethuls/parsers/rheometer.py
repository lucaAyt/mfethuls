import logging
import os
from typing import Any, Dict, Optional

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.ingestion import collect_dataframe_from_paths
from mfethuls.parsers.registry import register_parser
from mfethuls.registry_validator import infer_canonical_profile_from_registry_profile
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)





@register_parser('rheometer', 'anton_paar')
class RheometerAntPaarParser:
    def __init__(self, file_extension='.csv', delimiter='\t'):
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
        measurement_profile: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Parse rheometer data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="rheometer",
        ).dropna(how='all', axis=1)

        if experiment_id is None:
            return df

        # Map the explicit measurement_profile provided by the registry to a
        # canonical profile key defined in the rheometer schema. We only
        # accept the mapped canonical value; unknown registry values are not
        # silently converted.
        if measurement_profile:
            mapped = infer_canonical_profile_from_registry_profile(
                "rheometer", measurement_profile, instrument_model
            )
            measurement_profile = mapped or None
        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="rheometer",
            instrument_model=instrument_model or "anton_paar",
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
        # Quite a shitty parse
        df = pd.read_csv(path, engine='python', encoding='utf-8', on_bad_lines='skip', skip_blank_lines=True,
                         header=[4, 6], sep='\t') \
            .dropna(how='all') \
            .reset_index(drop=True) \
            .sort_index(axis=1) \
            .drop(columns=['Interval data:', 'Point No.'], errors='ignore')

        if df.empty:
            return pd.DataFrame()

        # Rename columns
        df.columns = df.columns.get_level_values(0) + [f' {col}' if 'Unnamed' not in col else '' for col in
                                                       df.columns.get_level_values(1)]
        df.loc[:, 'name'] = os.path.basename(os.path.normpath(path)).split('$')[0]

        return df
