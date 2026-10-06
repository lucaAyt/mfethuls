import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting import build_dataset_spec
from mfethuls.plotting.backend import render

go = pytest.importorskip("plotly.graph_objects")


def _ftir():
    return Dataset(
        data=pd.DataFrame({"wavenumber_cm_inv": [500, 1000, 1500, 2000], "absorbance_a_u": [0.2, 0.5, 0.35, 0.1]})
    )


def _dma():
    return Dataset(
        data=pd.DataFrame(
            {"frequency_hz": [0.1, 1.0, 10.0], "storage_modulus_mpa": [10, 100, 1000], "loss_modulus_mpa": [5, 50, 500]}
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )


def test_limits_on_reversed_axis_keep_high_to_low():
    spec = build_dataset_spec(_ftir())
    spec.panel.xlim = (800.0, 1800.0)
    spec.panel.ylim = (0.0, 0.6)

    fig, ax = render(spec, backend="matplotlib")
    plt.close(fig)
    assert ax.get_xlim() == (1800.0, 800.0)
    assert ax.get_ylim() == (0.0, 0.6)

    plotly_fig = render(spec, backend="plotly")
    assert list(plotly_fig.layout.xaxis.range) == [1800.0, 800.0]
    assert list(plotly_fig.layout.yaxis.range) == [0.0, 0.6]
    assert plotly_fig.layout.xaxis.autorange is None


def test_limits_on_log_axes_use_log10_in_plotly():
    spec = build_dataset_spec(_dma())
    spec.panel.xlim = (1.0, 100.0)
    spec.panel.ylim = (10.0, 1000.0)

    fig, ax = render(spec, backend="matplotlib")
    plt.close(fig)
    assert ax.get_xlim() == pytest.approx((1.0, 100.0))

    plotly_fig = render(spec, backend="plotly")
    assert list(plotly_fig.layout.xaxis.range) == pytest.approx([0.0, 2.0])
    assert list(plotly_fig.layout.yaxis.range) == pytest.approx([1.0, 3.0])


def test_no_limits_leaves_axes_automatic():
    plotly_fig = render(build_dataset_spec(_ftir()), backend="plotly")

    assert plotly_fig.layout.xaxis.range is None
    assert plotly_fig.layout.xaxis.autorange == "reversed"
