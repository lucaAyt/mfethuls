"""Large datasets on screen: long series show a spread of their lines, very long lines are thinned,
a heatmap shows a whole series, and repetitive text columns are kept as categories."""

import numpy as np
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting.heatmap import heatmap_grid, matplotlib_heatmaps, plotly_heatmaps
from mfethuls.plotting.spec import Panel, PlotSpec, Trace
from mfethuls.plotting.thin import minmax_indices, spread_values, thin_spec


def _series(spectra: int, points: int = 50) -> pd.DataFrame:
    """A synthetic in-situ run: ``spectra`` spectra of ``points`` wavelengths, one time each."""
    wavelength = np.linspace(400, 800, points)
    return pd.DataFrame({
        "wavelength_nm": np.tile(wavelength, spectra),
        "transmittance_pct": np.concatenate([np.sin(wavelength / 50) + t / spectra for t in range(spectra)]),
        "time_s": np.repeat(np.arange(spectra, dtype=float) * 2, points),
        "source_file": np.repeat([f"s{t}.txt" for t in range(spectra)], points),
    })


def test_a_spread_keeps_the_first_and_last_value_and_is_even():
    assert spread_values(np.arange(10.0), 20).tolist() == list(range(10))  # all, when few
    spread = spread_values(np.repeat(np.arange(1000.0), 3), 100)
    assert len(spread) == 100 and spread[0] == 0 and spread[-1] == 999
    assert np.ptp(np.diff(spread)) <= 1  # evenly spaced, to rounding


def test_thinning_keeps_peaks_dips_and_the_ends():
    y = np.zeros(1_000_000)
    y[123_457], y[876_543], y[-1] = 50.0, -20.0, 3.0
    keep = minmax_indices(y, 2_000)
    assert len(keep) <= 2_002 and list(keep) == sorted(keep)
    assert {0, 123_457, 876_543, 999_999} <= set(keep)
    assert len(minmax_indices(np.arange(10.0), 2_000)) == 10  # short lines are kept whole


def test_a_figure_is_thinned_only_above_the_limit():
    x = np.arange(600_000, dtype=float)
    spec = PlotSpec([Panel(traces=[Trace(x, np.sin(x / 1000)), Trace(x[:1000], x[:1000])])])
    small, shown, total = thin_spec(spec, max_points=1_000_000)
    assert small is spec and shown == total == 601_000
    thinned, shown, total = thin_spec(spec, max_points=300_000)
    assert total == 601_000 and shown <= 301_000
    assert len(thinned.panel.traces[1].x) == 1_000  # its share is more than its length: kept whole
    assert len(spec.panel.traces[0].x) == 600_000  # the original (used for the SVG) is untouched


def test_the_screen_shows_fewer_points_on_a_reversed_x_axis_drawn_in_svg():
    pytest.importorskip("streamlit")
    from mfethuls.app.page import _screen_figure
    from mfethuls.plotting.thin import SVG_MAX_POINTS

    x = np.arange(200_000, dtype=float)
    for reversed_, limit in ((False, 200_000), (True, SVG_MAX_POINTS)):
        fig = _screen_figure(PlotSpec([Panel(traces=[Trace(x, np.sin(x / 1000))], x_reversed=reversed_)]))
        assert len(fig.data[0].x) <= limit + 1


def test_the_built_in_plot_of_a_long_series_shows_a_spread_of_its_spectra():
    from mfethuls.plotting import build_dataset_spec

    dataset = Dataset(data=_series(500), metadata={"instrument_type": "uv_vis", "experiment_name": "run"})
    spec = build_dataset_spec(dataset)  # before: more than 50 groups drew nothing
    traces = spec.panel.traces
    assert len(traces) == 100 and spec.panel.colorbar is not None
    assert traces[0].color_value == 0.0 and traces[-1].color_value == 998.0  # first and last spectrum
    assert spec.notes == ["Showing 100 of the 500 Time (s) values, spread evenly from first to last."]


def test_a_series_with_a_header_date_is_coloured_by_time():
    from mfethuls.plotting import build_dataset_spec

    frame = _series(200)
    # Flame files carry the header's date as well: it ties with time_s, and must not win (it is no number).
    frame.insert(2, "header_time", pd.to_datetime("2025-05-11", utc=True) + pd.to_timedelta(frame["time_s"], "s"))
    spec = build_dataset_spec(Dataset(data=frame, metadata={"instrument_type": "uv_vis"}))
    assert spec.panel.colorbar is not None and spec.panel.colorbar.title == "Time (s)"
    assert len(spec.panel.traces) == 100


def test_a_heatmap_shows_every_spectrum_as_a_row():
    grid = heatmap_grid(_series(30), x="wavelength_nm", value="transmittance_pct", rows="time_s")
    assert grid.z.shape == (30, 50) and not grid.notes and not np.isnan(grid.z).any()
    assert grid.z[3, 7] == pytest.approx(np.sin(np.linspace(400, 800, 50)[7] / 50) + 3 / 30)
    assert (grid.xlabel, grid.rowlabel) == ("Wavelength (nm)", "Time (s)")


def test_a_heatmap_with_more_rows_than_an_image_averages_them():
    grid = heatmap_grid(_series(1_000, points=20), x="wavelength_nm", value="transmittance_pct", rows="time_s",
                        max_rows=100)
    assert grid.z.shape == (100, 20)
    assert grid.notes == ["1,000 Time (s) values in 100 rows: each row is the mean of the values in its range."]
    figure = plotly_heatmaps([grid, grid], cmap="coolwarm_r")  # a Matplotlib scale Plotly does not know
    assert len(figure.data) == 2 and figure.data[0].showscale and not figure.data[1].showscale
    import matplotlib.pyplot as plt

    plt.close(matplotlib_heatmaps([grid]))


def test_repetitive_text_columns_become_categories_and_group_without_empty_groups():
    pytest.importorskip("streamlit")
    from mfethuls.app.page import compact_text

    frame = _series(200)
    frame["_experiment"] = "run"
    frame["note"] = [f"unique {i}" for i in range(len(frame))]  # every value different: stays text
    before = frame.memory_usage(deep=True).sum()
    compact = compact_text(frame.copy())
    assert str(compact["source_file"].dtype) == "category" and str(compact["note"].dtype) != "category"
    # Smaller: much smaller from pandas 2's text objects (506 -> 83 MB for an in-situ series),
    # less from pandas 3's compact strings.
    assert compact.memory_usage(deep=True).sum() < before
    assert compact["source_file"].memory_usage(deep=True) < frame["source_file"].memory_usage(deep=True) / 2
    kept = compact[compact["source_file"].isin(["s1.txt", "s2.txt"])]
    assert kept.groupby("source_file", observed=True).ngroups == 2
