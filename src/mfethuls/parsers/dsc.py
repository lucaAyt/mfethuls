import os
import re
import logging
from typing import Any, Dict, Optional

import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)


@register_parser('dsc', 'prior')
class DSCPriorParser:
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
        """Parse raw DSC data.

        When experiment context (experiment_id, etc.) is provided, this returns
        a Dataset; otherwise it returns a plain DataFrame for backward
        compatibility.
        """

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:
                path_cf = str(path).casefold()

                try:
                    if path_cf.endswith(self.file_extension.casefold()):
                        parsed = self.parse_raw_data(path)
                        if not parsed.empty:
                            df = pd.concat([df, parsed], axis=0)

                    elif path_cf.endswith('.parquet'):
                        df = pd.concat([df, pd.read_parquet(path)], axis=0)

                    else:
                        logger.debug("Skipping unsupported DSC(prior) path: %s", path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed parsing DSC(prior) path %s: %s", path, exc)

        df = df.reset_index(drop=True)

        if experiment_id is None:
            # Old behaviour: just return the DataFrame.
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="dsc",
            instrument_model=instrument_model or "prior",
        )

        # New behaviour: wrap into a Dataset with provided metadata and id columns.
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
        lines = []
        cols = []
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

        if not cols or not lines:
            return pd.DataFrame()

        # Make up columns by combining 1st and 2nd lines
        cols_row_2 = [''] + lines[0]
        cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

        if len(lines) <= 1:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

    # TODO: map instrument-specific column names to a standard DSC schema
    # (e.g. temperature_C, heat_flow_mW) once lab/company-specific
    # conventions are agreed.

        return df


@register_parser('dsc', 'perkin_elmer')
class DSCPerkinElmerParser:
    def __init__(self, file_extension='.txt', parse_char_start='\tTime', parse_char_end='Shiiit', delimiter='\t'):
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
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Parse raw Perkin Elmer DSC data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:
                path_cf = str(path).casefold()

                try:
                    if path_cf.endswith(self.file_extension.casefold()) or path_cf.endswith('.csv'):
                        parsed = self.parse_raw_data(path)
                        if not parsed.empty:
                            df = pd.concat([df, parsed], axis=0)

                    elif path_cf.endswith('.parquet'):
                        df = pd.concat([df, pd.read_parquet(path)], axis=0)

                    else:
                        logger.debug("Skipping unsupported DSC(perkin_elmer) path: %s", path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed parsing DSC(perkin_elmer) path %s: %s", path, exc)

        df = df.reset_index(drop=True)

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="dsc",
            instrument_model=instrument_model or "perkin_elmer",
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

        if not str(path).casefold().endswith('.csv'):

            pattern_start = re.compile(self.parse_char_start)
            pattern_end = re.compile(self.parse_char_end)

            lines = []
            cols = []
            with open(path) as f:
                take = False
                for line in f.readlines():

                    if take:
                        l = re.split(self.delimiter, line.strip())
                        lines.append(l)

                    if pattern_start.match(line):
                        cols = re.split(self.delimiter, line.strip())
                        take = True

                    elif pattern_end.match(line):
                        take = False

            if not cols or not lines:
                return pd.DataFrame()

            # Make up columns by combining 1st and 2nd lines
            cols_row_2 = [''] + lines[0]
            cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

            if len(lines) <= 1:
                return pd.DataFrame(columns=cols)

            df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
            df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

            # TODO: map instrument-specific column names to a standard DSC
            # schema (e.g. temperature_C, heat_flow_mW) once conventions are
            # defined for this setup.

        else:

            filename = f'{os.path.basename(os.path.normpath(path)).rstrip(".csv")}'
            df = pd.read_csv(path).assign(name=filename)

        return df


@register_parser('dsc', 'mettler_toledo')
class DSCMettlerToledoParser:
    def __init__(self, file_extension='.txt', parse_char_start='\s+Index', parse_char_end='Shiiit', delimiter='\s\s+'):
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
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Parse raw Mettler Toledo DSC data.

        Returns a Dataset when experiment context is provided, otherwise a
        plain DataFrame for backward compatibility.
        """

        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:
                path_cf = str(path).casefold()

                try:
                    if path_cf.endswith(self.file_extension.casefold()):
                        parsed = self.parse_raw_data(path)
                        if not parsed.empty:
                            df = pd.concat([df, parsed], axis=0)

                    elif path_cf.endswith('.parquet'):
                        df = pd.concat([df, pd.read_parquet(path)], axis=0)

                    else:
                        logger.debug("Skipping unsupported DSC(mettler_toledo) path: %s", path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed parsing DSC(mettler_toledo) path %s: %s", path, exc)

        df = df.reset_index(drop=True)

        if experiment_id is None:
            return df

        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type="dsc",
            instrument_model=instrument_model or "mettler_toledo",
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

        pattern_start = re.compile(self.parse_char_start)
        pattern_end = re.compile(self.parse_char_end)

        lines = []
        cols = []
        with open(path) as f:
            take = False
            for line in f.readlines():

                if take:
                    l = re.split(self.delimiter, line.strip())
                    lines.append(l)

                if pattern_start.match(line):
                    cols = re.split(self.delimiter, line.strip())
                    take = True

                elif pattern_end.match(line):
                    take = False

        if not cols or not lines:
            return pd.DataFrame()

        # Make up columns by combining 1st and 2nd lines
        cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, lines[0])]

        if len(lines) <= 1:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        # TODO: map instrument-specific column names to a standard DSC schema
        # (e.g. temperature_C, heat_flow_mW) once lab/company-specific
        # naming conventions are set.

        return df
