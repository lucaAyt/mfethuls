import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.ticker import AutoMinorLocator

from mfethuls.dataset import Dataset
from mfethuls.plotting import build_dataset_spec, build_experiments_spec, plot_dma, plot_fluorescence, plot_uv_vis
from mfethuls.schema_normalization import add_elapsed_time

go = pytest.importorskip("plotly.graph_objects")


def _spectra_series(name, spectra=20, start="2025-05-11 16:11:00"):
    """Fluorescence spectra recorded one second apart, as the Flame parser stores them."""
    wavelengths = np.linspace(400, 700, 30)
    times = pd.date_range(start, periods=spectra, freq="1s", tz="UTC")
    data = pd.DataFrame(
        {
            "wavelength_nm": np.tile(wavelengths, spectra),
            "emission_counts": np.random.default_rng(0).random(spectra * len(wavelengths)),
            "timestamp": np.repeat(times, len(wavelengths)),
        }
    )
    return Dataset(data=add_elapsed_time(data), metadata={"experiment_id": name, "instrument_type": "fluorescence"})


def test_time_series_spectra_get_a_colorbar_instead_of_a_legend(caplog):
    caplog.set_level("WARNING", logger="mfethuls.plotting.core")

    panel = build_dataset_spec(_spectra_series("A")).panel

    assert panel.legend is False
    assert panel.colorbar is not None
    assert panel.colorbar.title == "Time (s)"
    assert (panel.colorbar.vmin, panel.colorbar.vmax) == (0.0, 19.0)
    assert [trace.color_value for trace in panel.traces[:3]] == [0.0, 1.0, 2.0]
    # time_s and timestamp split the data the same way; time_s is chosen without a tie warning.
    assert "tie detected" not in caplog.text


def test_few_numeric_groups_keep_a_legend():
    panel = build_dataset_spec(_spectra_series("A", spectra=4)).panel

    assert panel.colorbar is None
    assert panel.legend is True
    assert panel.legend_title == "Time"


def test_overlay_merges_colorbars_and_marks_experiments_by_linestyle():
    spec = build_experiments_spec(
        [_spectra_series("A"), _spectra_series("B", spectra=30)],
        mode="overlay",
    )

    panel = spec.panel
    assert (panel.colorbar.vmin, panel.colorbar.vmax) == (0.0, 29.0)
    assert panel.legend is False
    assert [entry.label for entry in panel.legends[0].entries] == ["A", "B"]
    assert {trace.linestyle for trace in panel.traces} == {"-", "--"}


def test_matplotlib_draws_colorbar():
    fig, ax = plot_fluorescence(_spectra_series("A"))
    try:
        colorbar_axes = [axis for axis in fig.axes if axis is not ax]
        assert len(colorbar_axes) == 1
        assert colorbar_axes[0].get_ylabel() == "Time (s)"
        assert ax.get_legend() is None
    finally:
        plt.close(fig)


def test_plotly_draws_colorbar():
    fig = plot_fluorescence(_spectra_series("A"), backend="plotly")

    bars = [trace for trace in fig.data if getattr(trace.marker, "showscale", False)]
    assert len(bars) == 1
    assert bars[0].marker.colorbar.title.text == "Time (s)"
    assert not any(trace.showlegend for trace in fig.data if isinstance(trace, go.Scattergl))


def test_linear_x_axis_has_one_minor_tick_between_majors():
    dataset = Dataset(data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.4, 0.2]}))

    fig, ax = plot_uv_vis(dataset)
    try:
        locator = ax.xaxis.get_minor_locator()
        assert isinstance(locator, AutoMinorLocator)
        assert locator.ndivs == 2
    finally:
        plt.close(fig)


def test_plotly_log_axes_label_decades_only():
    dataset = Dataset(
        data=pd.DataFrame(
            {"frequency_hz": [0.1, 1.0, 10.0], "storage_modulus_mpa": [10, 100, 1000], "loss_modulus_mpa": [5, 50, 500]}
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )

    fig = plot_dma(dataset, backend="plotly")
    for axis in (fig.layout.xaxis, fig.layout.yaxis):
        assert axis.dtick == 1
        assert axis.exponentformat == "power"


def _axes_width_in(fig, ax):
    fig.draw_without_rendering()
    return ax.get_position().width * fig.get_figwidth()


@pytest.mark.parametrize("outside", ["colorbar", "legends"])
def test_outside_legend_or_colorbar_does_not_shrink_axes(outside):
    from mfethuls.plotting.render_mpl import render

    if outside == "colorbar":
        spec = build_dataset_spec(_spectra_series("A"))
        plain = build_dataset_spec(_spectra_series("A"))
        plain.panel.colorbar = None
    else:
        series = [_spectra_series("A"), _spectra_series("B")]
        spec = build_experiments_spec(series, mode="overlay")
        plain = build_experiments_spec(series, mode="overlay")
        plain.panel.legends = []

    fig, ax = render(spec)
    plain_fig, plain_ax = render(plain)
    try:
        assert fig.get_figwidth() > plain_fig.get_figwidth()
        assert _axes_width_in(fig, ax) == pytest.approx(_axes_width_in(plain_fig, plain_ax), abs=0.05)
    finally:
        plt.close(fig)
        plt.close(plain_fig)
