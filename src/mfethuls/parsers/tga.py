import os
import re
from typing import Any, Dict, Optional

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import register_parser


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

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        df = df.reset_index(drop=True)

        if experiment_id is None:
            return df

        if "experiment_id" not in df.columns:
            df["experiment_id"] = experiment_id
        if sample_id is not None and "sample_id" not in df.columns:
            df["sample_id"] = sample_id
        if run_id is not None and "run_id" not in df.columns:
            df["run_id"] = run_id

        meta: Dict[str, Any] = {
            "schema_version": "1.0",
            "experiment_id": experiment_id,
            "sample_id": sample_id,
            "run_id": run_id,
            "instrument_type": instrument_type,
            "instrument_model": instrument_model,
            "instrument_name": instrument_name,
            "experiment_name": experiment_name,
        }
        if metadata:
            meta.update(metadata)

        return Dataset(data=df, metadata=meta)

    def parse_raw_data(self, path):
        lines = []
        with open(path) as f:
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

        # Make up columns by combining 1st and 2nd lines
        cols_row_2 = [''] + lines[0]
        cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

        df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df['name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        return df
