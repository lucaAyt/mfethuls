import os
import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)


@register_parser('nmr', 'bruker_nmr')
class BrukerNMRParser:
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

        Derives the experiment folder from the provided file paths (each file
        is a member of the Bruker dataset directory). parse_raw_data is called
        once per unique folder so nmrglue reads the spectrum exactly once.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """
        experiment_folders: set[str] = set()
        for paths in dict_paths.values():
            for p in paths:
                experiment_folders.add(os.path.dirname(p) if not os.path.isdir(p) else p)

        frames = []
        for folder in sorted(experiment_folders):
            parsed = self.parse_raw_data(folder)
            if not parsed.empty:
                frames.append(parsed)

        df = (
            pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        ).dropna(how='all', axis=1)

        # Note: this parser currently produces a somewhat non-standard
        # structure. We now normalize into canonical 1D spectral columns.

        df = df.reset_index(drop=True)

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="nmr",
            instrument_model=instrument_model or "bruker_nmr",
        )

        if isinstance(df, pd.DataFrame):
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
        """Parse a Bruker processed spectrum into canonical columns.

        Supports passing either the experiment root folder or a direct pdata
        path and returns an empty DataFrame when parsing is not possible.
        """

        try:
            import nmrglue as ng
        except ImportError:
            return pd.DataFrame()

        # Candidate locations for Bruker processed data.
        candidates = [
            os.path.dirname(path),
            path,
            os.path.join(path, "1", "pdata", "1"),
            os.path.join(path, "pdata", "1"),
        ]

        dic = None
        data = None
        for candidate in candidates:
            try:
                dic, data = ng.bruker.read_pdata(candidate)
                break
            except Exception:
                continue

        if dic is None or data is None:
            return pd.DataFrame()

        # Flatten to 1D and use real component for canonical signal output.
        data_1d = np.asarray(data).squeeze()
        if data_1d.ndim != 1:
            return pd.DataFrame()

        udic = ng.bruker.guess_udic(dic, data_1d)
        uc = ng.fileiobase.uc_from_udic(udic, 0)

        ppm = np.asarray(uc.ppm_scale(), dtype=float)
        intensity = np.real(data_1d).astype(float, copy=False)

        if ppm.shape[0] != intensity.shape[0]:
            return pd.DataFrame()

        return pd.DataFrame(
            {
                "chemical_shift_ppm": ppm,
                "intensity_a_u": intensity,
                "source_file": os.path.basename(os.path.normpath(path)),
            }
        )
