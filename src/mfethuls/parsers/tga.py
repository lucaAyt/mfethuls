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


@register_parser('tga', 'tgaX')
class TGAXParser:
    def __init__(self, file_extension='.txt', delimiter='\s+'):
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
        """Parse TGA data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=self.parse_raw_data,
            logger=logger,
            parser_label="TGA",
            should_parse_raw=lambda path: str(path).casefold().endswith(self.file_extension.casefold()) or str(path).casefold().endswith('.csv'),
        )

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="tga",
            instrument_model=instrument_model or "tgaX",
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

    # TODO: Fix parser header, units are mismatched (Follow up with schema change).
    def parse_raw_data(self, path):
        
        if not str(path).casefold().endswith('.csv'):

            lines = []
            cols = []
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                take = 0
                for line in f.readlines():

                    if take == 1:
                        curate_line = re.split('\s+', line.strip(), maxsplit=5)
                        lines.append(curate_line)

                    if 'Index' in line:
                        cols = re.split('\s+', line.strip(), maxsplit=5)
                        take = 1

                    elif 'Results' in line:
                        take = 0

            if not cols or not lines:
                return pd.DataFrame()

            # Make up columns by combining 1st and 2nd lines
            cols_row_2 = lines[0]
            cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

            if len(lines) <= 1:
                return pd.DataFrame(columns=cols)

            df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
            df["name"] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]
            
            # Calculate mass percentage as not in original data
            _calculate_mass_percentage(df, weight_column="Weight [mg]")
        
        else:
            
            filename = f'{os.path.basename(os.path.normpath(path)).rstrip(".csv")}'
            df = pd.read_csv(path).assign(name=filename)
            _calculate_mass_percentage(df)
            logger.warning(f"Parsed CSV file:\n{df}")

        return df

# TODO: Fix mass percentage calculation, currently assumes weight column is present and valid. 
# Do after mapping schema is finalized.
def _calculate_mass_percentage(df, weight_column="mass_mg"):
    """Calculate mass percentage from weight data."""
    if weight_column in df.columns:
        min_weight = df[weight_column].min()
        max_weight = df[weight_column].max()
        if max_weight != min_weight:
            df["mass_pct"] = (df[weight_column] - min_weight) / (max_weight - min_weight) * 100