import os
import re
from typing import Any, Dict, Optional

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


@register_parser('ms', 'bruker')
class BrukerMS:
    def __init__(self, file_extension='.bsc', delimiter=','):
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
        """Parse Bruker MS data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.casefold().endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0)

                elif path.casefold().endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        df = df.reset_index(drop=True)

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="ms",
            instrument_model=instrument_model or "bruker",
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
        # Read main data from raw data file
        df = pd.read_csv(path, sep=self.delimiter, names=['m/z', 'intensity'], header=None) \
               .drop_duplicates(subset=['m/z']) \
               .apply(pd.to_numeric, errors='coerce') \
               .sort_values(by='m/z', ascending=True) \
               .reset_index(drop=True) \
               .dropna(axis=0, how='any')
               
        name = f'{os.path.basename(os.path.normpath(path)).casefold().rstrip(self.file_extension)}'
        df.loc[:, 'name'] = [name] * df.shape[0]

        peak_mz = self._read_peak_mz_from_raw_file(path)
        df['peaks'] = df['m/z'].isin(peak_mz)
    
        return df

    def _read_peak_mz_from_raw_file(self, path):
        # Identify peaks from raw data file
        lines = []
        with open(path) as f:
            take = 0
            for line in f.readlines():

                if take == 1:
                    curate_line = re.split(',', line.strip(), maxsplit=2)
                    lines.append(curate_line)

                if 'Peak' in line:
                    take = 1

                elif 'End' in line:
                    take = 0

        df_peaks = pd.DataFrame(lines, columns=['m/z', 'intensity']) \
                     .apply(pd.to_numeric, errors='coerce' ) \
                     .dropna(axis=0, how='any')

        return df_peaks['m/z']
