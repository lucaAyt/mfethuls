"""Experiments made of several files keep track of each row's file."""

import logging

import numpy as np
import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.ingestion import collect_dataframe_from_paths
from mfethuls.plotting import build_dataset_spec
from mfethuls.schema_normalization import add_elapsed_time

LOGGER = logging.getLogger(__name__)


def _spectrum(path: str) -> pd.DataFrame:
    return pd.DataFrame({"wavelength_nm": [400.0, 500.0], "absorbance_a_u": [0.1, 0.2]})


def test_several_files_get_a_source_file_column():
    df = collect_dataframe_from_paths(
        {"titration_A": ["/data/titration_A/step01.txt", "/data/titration_A/step02.txt"]},
        file_extension=".txt", parse_raw=_spectrum, logger=LOGGER, parser_label="test",
    )

    assert df["source_file"].tolist() == ["step01", "step01", "step02", "step02"]


def test_single_file_is_unchanged():
    df = collect_dataframe_from_paths(
        {"compoundA": ["/data/compoundA.txt"]},
        file_extension=".txt", parse_raw=_spectrum, logger=LOGGER, parser_label="test",
    )

    assert "source_file" not in df.columns


def test_titration_without_timestamps_plots_one_line_per_file():
    data = pd.concat(
        [_spectrum("").assign(source_file=f"step{i:02d}") for i in range(1, 4)], ignore_index=True
    )

    panel = build_dataset_spec(Dataset(data=data, metadata={"instrument_type": "uv_vis"})).panel

    assert [trace.label for trace in panel.traces] == ["step01", "step02", "step03"]
    assert panel.legend_title == "File"


def test_timed_series_still_gets_the_time_colour_bar(caplog):
    files, wavelengths = 20, np.linspace(400, 700, 10)
    times = pd.date_range("2025-05-11 16:11:00", periods=files, freq="1s", tz="UTC")
    data = pd.DataFrame(
        {
            "wavelength_nm": np.tile(wavelengths, files),
            "emission_counts": np.arange(files * len(wavelengths), dtype=float),
            "timestamp": np.repeat(times, len(wavelengths)),
            "source_file": np.repeat([f"poly3__{i}" for i in range(files)], len(wavelengths)),
        }
    )
    caplog.set_level("WARNING", logger="mfethuls.plotting.core")

    panel = build_dataset_spec(
        Dataset(data=add_elapsed_time(data), metadata={"instrument_type": "fluorescence"})
    ).panel

    assert panel.colorbar is not None and panel.colorbar.title == "Time (s)"
    assert "tie detected" not in caplog.text
