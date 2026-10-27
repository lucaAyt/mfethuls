"""Bruker NMR: the processed 1D spectra of an experiment folder, read with nmrglue.

A Bruker dataset folder holds one folder per experiment number, each with its
processed spectra: ``EXP014/1/pdata/1/1r``. Every processed spectrum (a ``pdata``
folder with a ``1r`` file) is read once; ``source_file`` names it by its place in
the dataset (``1/pdata/1``), so several experiment numbers (e.g. 1H and 13C) stay
apart. An experiment folder may hold several datasets (a series: ``LUB437_000/10``,
``LUB437_005/10``, ...); their spectra are then named from that folder on
(``LUB437_000/10/pdata/1``). Each row also gets the spectrum's ``dataset`` (its
dataset folder's name), ``nucleus`` (``1H``, ``13C``, ...; from ``acqus.NUC1``, else
``procs.AXNUC``), ``solvent`` (``acqus.SOLVENT``) and ``timestamp`` (when it was
acquired, ``acqus.DATE``; mfethuls adds ``time_s`` from it). All the acquisition and
processing parameters (``acqus``, ``procs``) and the spectrum's ``title`` are kept in
the dataset's metadata (``file_text``).
"""

import logging
import os
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from mfethuls.naming import natural_key
from mfethuls.parsers.ingestion import FILE_TEXT_ATTR, ParseError, build_dataset, keep_text
from mfethuls.parsers.registry import register_parser
from mfethuls.schema_normalization import apply_dataframe_schema


logger = logging.getLogger(__name__)


def _parameter_lines(dic: dict) -> List[str]:
    """``acqus.NS = 16`` lines for the acquisition and processing parameters."""
    lines = []
    for group in ("acqus", "procs"):
        for key, value in sorted((dic.get(group) or {}).items()):
            lines.append(f"{group}.{key} = {value!r}" if not isinstance(value, str) else f"{group}.{key} = {value}")
    return lines


@register_parser('nmr', 'bruker_nmr')
class BrukerNMRParser:
    # Raised whenever the reading changes, so data read by an older version is read again.
    version = 5

    def parse(self, dict_paths, *, instrument_model: Optional[str] = None, **context):
        """Parse Bruker NMR data: every processed spectrum among the given files, once each.

        The spectra are the folders holding a ``1r`` file (``<expno>/pdata/<procno>``).
        Without one (e.g. only the dataset folder is given), each file's folder is tried.
        """
        paths = [p for group in dict_paths.values() for p in group]
        folders = sorted({os.path.dirname(p) for p in paths if os.path.basename(p) == "1r"}, key=natural_key)
        spectra_found = bool(folders)
        if not folders:
            folders = sorted({p if os.path.isdir(p) else os.path.dirname(p) for p in paths}, key=natural_key)

        # Spectra of several datasets are named from the folder holding the datasets on.
        datasets = {_dataset_folder(folder) for folder in folders} - {None}
        base = os.path.commonpath(sorted(datasets)) if len(datasets) > 1 else None

        frames = []
        file_text: dict = {}
        problems: List[str] = []
        for folder in folders:
            parsed = self.parse_raw_data(folder, problems=problems)
            if not parsed.empty:
                label = _spectrum_label(folder, base)
                parsed["source_file"] = label
                text = parsed.attrs.pop(FILE_TEXT_ATTR, None)
                if text:
                    file_text[label] = text
                frames.append(parsed)
        # A processed spectrum (a folder with 1r) that cannot be read is an error, never skipped;
        # without any, every folder was only a guess and the reasons are given when none reads.
        if problems and (spectra_found or not frames):
            raise ParseError("Bruker NMR data could not be read: " + "; ".join(problems))
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        df, schema_report = apply_dataframe_schema(df, instrument_type="nmr",
                                                   instrument_model=instrument_model or "bruker_nmr")
        return build_dataset(df, schema_report, instrument_model=instrument_model, file_text=file_text, **context)

    def parse_raw_data(self, path, problems: Optional[List[str]] = None):
        """Parse a Bruker processed spectrum into canonical columns.

        Supports passing either the experiment root folder or a direct pdata
        path and returns an empty DataFrame when parsing is not possible; why is
        added to ``problems``.
        """
        import nmrglue as ng

        def failed(reason: str) -> pd.DataFrame:
            if problems is not None:
                problems.append(f"{_spectrum_label(path)}: {reason}")
            return pd.DataFrame()

        # Candidate locations for Bruker processed data.
        candidates = [
            os.path.dirname(path),
            path,
            os.path.join(path, "1", "pdata", "1"),
            os.path.join(path, "pdata", "1"),
        ]

        dic: Any = None
        data = None
        error: Optional[Exception] = None
        for candidate in candidates:
            try:
                dic, data = ng.bruker.read_pdata(candidate)
                break
            except Exception as exc:  # noqa: BLE001 - the next candidate may be the spectrum
                error = exc

        if dic is None or data is None:
            return failed(f"no processed spectrum ({error})" if error else "no processed spectrum")

        # Flatten to 1D and use real component for canonical signal output.
        data_1d = np.asarray(data).squeeze()
        if data_1d.ndim != 1:
            return failed(f"the spectrum has {data_1d.ndim} dimensions; only 1D spectra are read")

        udic = ng.bruker.guess_udic(dic, data_1d)
        uc = ng.fileiobase.uc_from_udic(udic, 0)

        ppm = np.asarray(uc.ppm_scale(), dtype=float)
        intensity = np.real(data_1d).astype(float, copy=False)

        if ppm.shape[0] != intensity.shape[0]:
            return failed(f"{ppm.shape[0]} chemical shifts for {intensity.shape[0]} intensities")

        dataset = _dataset_folder(path)
        df = pd.DataFrame(
            {
                "chemical_shift_ppm": ppm,
                "intensity_a_u": intensity,
                "source_file": os.path.basename(os.path.normpath(path)),
                "dataset": os.path.basename(dataset) if dataset else None,
                "nucleus": _parameter(dic, ("acqus", "NUC1"), ("procs", "AXNUC")),
                "solvent": _parameter(dic, ("acqus", "SOLVENT")),
                "timestamp": _acquired(dic),
            }
        )
        return keep_text(df, parameters=_parameter_lines(dic), title=_title_lines(path))


def _parameter(dic: dict, *keys) -> Optional[str]:
    """The first of ``(group, name)`` set in the parameters, as text (``<1H>`` -> ``1H``); None if none is."""
    for group, name in keys:
        value = str((dic.get(group) or {}).get(name) or "").strip().strip("<>").strip()
        if value and value.casefold() != "off":
            return value
    return None


def _acquired(dic: dict) -> Optional[pd.Timestamp]:
    """When the spectrum was acquired (``acqus.DATE``, seconds since 1970, UTC); None if unknown."""
    seconds = pd.to_numeric((dic.get("acqus") or {}).get("DATE"), errors="coerce")
    return pd.Timestamp(seconds, unit="s", tz="UTC") if pd.notna(seconds) and seconds > 0 else None


def _dataset_folder(folder: str) -> Optional[str]:
    """``.../EXP014`` for the spectrum ``.../EXP014/1/pdata/1``; None for other folders."""
    parts = os.path.normpath(folder).split(os.sep)
    if len(parts) >= 4 and parts[-2] == "pdata":
        return os.sep.join(parts[:-3])
    return None


def _spectrum_label(folder: str, base: Optional[str] = None) -> str:
    """``1/pdata/1`` for ``.../EXP014/1/pdata/1``, or from ``base`` on (``EXP014/1/pdata/1``);
    the folder's name otherwise."""
    if base and _dataset_folder(folder):
        return os.path.relpath(folder, base).replace(os.sep, "/")
    parts = os.path.normpath(folder).split(os.sep)
    if len(parts) >= 3 and parts[-2] == "pdata":
        return "/".join(parts[-3:])
    return parts[-1]


def _title_lines(folder: str) -> List[str]:
    """The spectrum's title (``pdata/<procno>/title``, written by TopSpin), if there is one."""
    path = os.path.join(folder, "title")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as handle:
        return [line.rstrip() for line in handle if line.strip()]
