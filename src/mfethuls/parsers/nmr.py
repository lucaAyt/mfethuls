import os
from typing import Any, Dict, Optional

import nmrglue as ng
import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import register_parser


@register_parser('nmr', 'bruker_nmr')
class RheometerAntPaarParser:
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
        """Parse Bruker NMR data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0).dropna(how='all', axis=1)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        # Note: this parser currently produces a somewhat non-standard
        # structure (uc + data). For now we preserve that but still allow
        # attaching experiment metadata when requested.

        if experiment_id is None:
            return df

        if isinstance(df, pd.DataFrame):
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
        # Quite a shitty parse
        dic, data = ng.bruker.read_pdata(os.path.join(path, '1', 'pdata', '1'))
        udic = ng.bruker.guess_udic(dic, data)
        uc = ng.fileiobase.uc_from_udic(udic, 0)
        return [uc, data]
