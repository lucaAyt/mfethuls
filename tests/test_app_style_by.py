"""The app's line/scatter plot: colour by one column, style by another, in both renderers."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from mfethuls.app.page import _xy_spec  # noqa: E402
from mfethuls.plotting.backend import render  # noqa: E402
from mfethuls.plotting.spec import LINESTYLES, MARKERS  # noqa: E402

PALETTE = [(0.1, 0.2, 0.8), (0.8, 0.2, 0.1), (0.1, 0.6, 0.2)]


def _data():
    rows = []
    for experiment, sample in [("A", "S001"), ("B", "S001"), ("C", "S002")]:
        for x in range(5):
            rows.append({"_experiment": experiment, "sample_id": sample, "x": x, "y": x * 2.0})
    return pd.DataFrame(rows)


def _spec(mode, **kwargs):
    return _xy_spec(_data(), x="x", y="y", mode=mode, palette=PALETTE, title="t", ylabel="y",
                    log_x=False, log_y=False, invert_x=False, **kwargs)


def test_lines_coloured_by_experiment_and_styled_by_sample():
    panel = _spec("lines", color="_experiment", style="sample_id").panel

    assert {trace.linestyle for trace in panel.traces} == {LINESTYLES[0], LINESTYLES[1]}
    assert len({trace.color for trace in panel.traces}) == 3
    assert len(panel.traces) == 3  # one line per experiment
    # Two hand-built legends replace the per-trace legend: colour, then style.
    assert not panel.legend and [legend.title for legend in panel.legends] == ["Experiment", "sample_id"]
    assert [entry.linestyle for entry in panel.legends[1].entries] == [LINESTYLES[0], LINESTYLES[1]]
    assert all(entry.marker is None for entry in panel.legends[1].entries)


def test_scatter_styles_use_marker_shapes():
    panel = _spec("markers", color="_experiment", style="sample_id").panel

    assert {trace.marker for trace in panel.traces} == {MARKERS[0], MARKERS[1]}
    assert all(trace.linestyle == "-" for trace in panel.traces)
    assert [entry.marker for entry in panel.legends[1].entries] == [MARKERS[0], MARKERS[1]]


def test_without_style_the_legend_is_per_trace():
    panel = _spec("lines", color="_experiment").panel

    assert panel.legend and panel.legends == []
    assert {trace.linestyle for trace in panel.traces} == {"-"}


def test_style_only_draws_one_colour():
    panel = _spec("lines", color=None, style="sample_id").panel

    assert len({trace.color for trace in panel.traces}) == 1
    assert [legend.title for legend in panel.legends] == ["sample_id"]


@pytest.mark.parametrize("mode", ["lines", "markers"])
def test_both_renderers_draw_styles(mode):
    spec = _spec(mode, color="_experiment", style="sample_id")

    fig, ax = render(spec, backend="matplotlib")
    if mode == "lines":
        assert {line.get_linestyle() for line in ax.get_lines()} >= {"-", "--"}
    else:
        assert {line.get_marker() for line in ax.get_lines()} >= {"o", "s"}
    plt.close(fig)

    plotly_fig = render(spec, backend="plotly")
    data_traces = [t for t in plotly_fig.data if t.x is not None and len(t.x) and t.x[0] is not None]
    if mode == "lines":
        assert {t.line.dash for t in data_traces} == {"solid", "longdash"}
    else:
        assert {t.marker.symbol for t in data_traces} == {"circle", "square"}
    legend_entries = [t for t in plotly_fig.data if t.x is not None and len(t.x) and t.x[0] is None]
    assert len(legend_entries) == 3 + 2  # experiments + samples
    assert np.isfinite(data_traces[0].y).all()


def test_colour_and_style_legend_fits_in_the_saved_figure():
    """Both legend sections must be inside the figure, or SVG exports cut them off."""
    rows = [{"_experiment": f"LB_polymer_sample_{i:03d}", "sample_id": f"S00{i % 3}", "x": x, "y": x * i}
            for i in range(6) for x in range(10)]
    spec = _xy_spec(pd.DataFrame(rows), x="x", y="y", color="_experiment", style="sample_id", mode="markers",
                    palette=PALETTE, title="t", ylabel="y", log_x=False, log_y=False, invert_x=False)

    fig, ax = render(spec, backend="matplotlib")
    renderer = fig.canvas.get_renderer()
    legend_right = ax.get_legend().get_window_extent(renderer).x1 / fig.dpi
    assert legend_right <= fig.get_figwidth() + 1e-6
    assert fig.get_tightbbox(renderer).x1 >= legend_right - 1e-6
    plt.close(fig)


def test_csv_export_keeps_every_column_with_the_experiment_first():
    from mfethuls.app.page import _csv_bytes

    data = pd.DataFrame({"x": [1.0, 2.0], "name": ["a", "b"], "_experiment": ["E1", "E1"]})
    assert _csv_bytes(data).decode("utf-8").splitlines() == ["experiment,x,name", "E1,1.0,a", "E1,2.0,b"]


def _series():
    """One wavelength of a spectra series, read in file-name order (0, 10, 11, ..., 1, 2)."""
    times = sorted(range(12), key=str)
    return pd.DataFrame({"_experiment": "poly3", "time_s": [float(t) for t in times],
                         "emission_counts": [100.0 - t for t in times]})


def test_lines_along_time_follow_the_time_not_the_file_order():
    spec = _xy_spec(_series(), x="time_s", y="emission_counts", color="_experiment", mode="lines", palette=PALETTE,
                    title="t", ylabel="y", log_x=False, log_y=False, invert_x=False)
    [trace] = spec.panel.traces
    assert list(trace.x) == sorted(trace.x) and trace.mode == "lines"


def test_lines_of_one_point_are_drawn_as_points():
    # Coloured by time_s, each time is its own line of one point, which Plotly would not draw.
    spec = _xy_spec(_series(), x="time_s", y="emission_counts", color="time_s", mode="lines", palette=PALETTE,
                    title="t", ylabel="y", log_x=False, log_y=False, invert_x=False)
    assert len(spec.panel.traces) == 12 and {trace.mode for trace in spec.panel.traces} == {"markers"}
