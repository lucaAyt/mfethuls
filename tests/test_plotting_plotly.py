import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

go = pytest.importorskip("plotly.graph_objects")

from mfethuls import set_plot_backend
from mfethuls.dataset import Dataset
from mfethuls.plotting import (
    get_default_backend,
    plot_dataset,
    plot_dma,
    plot_experiments,
    plot_ftir,
    plot_nmr,
    plot_uv_vis,
    set_default_backend,
)
from mfethuls.plotting.core import PlotError


@pytest.fixture(autouse=True)
def _restore_default_backend():
    previous = get_default_backend()
    yield
    set_default_backend(previous)


def _uv_vis(name="EXP001", n=3):
    x = np.linspace(200, 800, n)
    return Dataset(
        data=pd.DataFrame({"wavelength_nm": x, "absorbance_a_u": np.sin(x / 50.0)}),
        metadata={"experiment_id": name},
    )


def _dsc(name):
    return Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": [25, 50, 75, 75, 50, 25],
                "heat_flow_mW": [0.0, 1.2, 0.8, 0.1, 1.1, 0.9],
                "profile": ["Heating_0"] * 3 + ["Cooling_0"] * 3,
            }
        ),
        metadata={"experiment_id": name},
    )


def test_plotly_backend_returns_webgl_figure():
    fig = plot_uv_vis(_uv_vis(), backend="plotly")

    assert isinstance(fig, go.Figure)
    assert [type(trace) for trace in fig.data] == [go.Scattergl]
    assert fig.layout.xaxis.title.text == "Wavelength (nm)"
    assert fig.layout.yaxis.title.text == "Absorbance (a.u.)"
    assert fig.layout.title.text == "UV/Vis - EXP001"


@pytest.mark.parametrize(
    ("plot", "columns"),
    [
        (plot_ftir, {"wavenumber_cm_inv": [500, 1000], "absorbance_a_u": [0.2, 0.5]}),
        (plot_nmr, {"chemical_shift_ppm": [1.0, 2.0], "intensity_a_u": [3.0, 4.0]}),
    ],
)
def test_plotly_reverses_x_for_spectra(plot, columns):
    fig = plot(Dataset(data=pd.DataFrame(columns), metadata={}), backend="plotly")

    assert fig.layout.xaxis.autorange == "reversed"


def test_plotly_dma_uses_log_axes():
    dataset = Dataset(
        data=pd.DataFrame(
            {"frequency_hz": [0.1, 1.0, 10.0], "storage_modulus_mpa": [10, 100, 1000], "loss_modulus_mpa": [5, 50, 500]}
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )

    fig = plot_dma(dataset, backend="plotly")
    assert (fig.layout.xaxis.type, fig.layout.yaxis.type) == ("log", "log")
    assert [trace.name for trace in fig.data] == ["Storage modulus E′", "Loss modulus E″"]


def test_plotly_dsc_overlay_has_segment_and_experiment_legends():
    fig = plot_experiments([_dsc("A"), _dsc("B")], mode="overlay", backend="plotly")

    lines = [trace for trace in fig.data if isinstance(trace, go.Scattergl)]
    assert len(lines) == 4
    assert not any(trace.showlegend for trace in lines)

    entries = [trace for trace in fig.data if not isinstance(trace, go.Scattergl)]
    by_legend = {}
    for entry in entries:
        by_legend.setdefault(entry.legend or "legend", []).append(entry.name)
    assert by_legend == {"legend": ["Heating_0", "Cooling_0"], "legend2": ["A", "B"]}
    assert fig.layout.legend.title.text == "Segment"
    assert fig.layout.legend2.title.text == "Experiment"

    # Clicking an experiment entry toggles that experiment's lines.
    experiment_b = next(entry for entry in entries if entry.name == "B")
    assert {trace.legendgroup for trace in lines if trace.name.startswith("B |")} == {experiment_b.legendgroup}
    assert lines[0].line.dash == "solid" and lines[2].line.dash == "longdash"


def test_plotly_facet_has_one_subplot_per_dataset():
    other = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50], "heat_flow_mW": [0.2, 0.4]}),
        metadata={"experiment_id": "B"},
    )

    fig = plot_experiments([_uv_vis("A"), other], backend="plotly")

    assert fig.layout.xaxis.title.text == "Wavelength (nm)"
    assert fig.layout.xaxis2.title.text == "Temperature (°C)"
    assert {trace.xaxis for trace in fig.data} == {"x", "x2"}


def test_plotly_backend_rejects_ax():
    fig, ax = plt.subplots()
    try:
        with pytest.raises(PlotError):
            plot_uv_vis(_uv_vis(), ax=ax, backend="plotly")
    finally:
        plt.close(fig)


def test_unknown_backend_is_rejected():
    with pytest.raises(PlotError):
        plot_uv_vis(_uv_vis(), backend="altair")


def test_default_backend_can_be_switched():
    set_plot_backend("plotly")
    assert isinstance(plot_dataset(_uv_vis()), go.Figure)

    set_default_backend("matplotlib")
    fig, _ = plot_dataset(_uv_vis())
    plt.close(fig)


def test_plotly_keeps_every_point_for_large_datasets():
    fig = plot_experiments([_uv_vis("A", n=250_000), _uv_vis("B", n=250_000)], backend="plotly")

    assert [len(trace.x) for trace in fig.data] == [250_000, 250_000]
