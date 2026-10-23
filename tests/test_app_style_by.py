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


def test_free_form_offset_and_panels_split_by_experiment():
    for mode in ("lines", "markers"):
        offset = _spec(mode, color="_experiment", layout="stacked")
        assert offset.layout == "single" and not offset.panel.y_ticks
        # Every experiment's y runs 0..8: B is shifted by 1.1 x 8, C by twice that.
        starts = sorted({round(float(min(t.y)), 6) for t in offset.panel.traces})
        assert starts == pytest.approx([0.0, 8.8, 17.6])

        panels = _spec(mode, color="_experiment", layout="facet")
        assert panels.layout == "facet" and panels.shared_x
        assert [p.title for p in panels.panels] == ["A", "B", "C"]


def test_a_waterfall_shifts_each_spectrum_up_by_its_time():
    from mfethuls.app.page import WATERFALL_RISE

    # Three spectra, at 0, 10 and 40 s, each running 0..4 over five wavelengths.
    spectra = pd.DataFrame({"_experiment": "run", "wavelength_nm": [400.0, 450, 500, 550, 600] * 3,
                            "time_s": np.repeat([0.0, 10.0, 40.0], 5), "signal": [0.0, 1, 4, 1, 0] * 3})
    spec = _xy_spec(spectra, x="wavelength_nm", y="signal", color="time_s", mode="lines", palette=PALETTE,
                    title="t", ylabel="Signal", log_x=False, log_y=False, invert_x=False, layout="waterfall")
    panel = spec.panel
    assert spec.layout == "single" and not panel.y_ticks and panel.legend  # few times: a legend, not a scale
    assert panel.ylabel == "Signal (offset)"
    rise = WATERFALL_RISE * 1.1 * 4  # the last spectrum: three Offset steps of the tallest line
    # Shifted in proportion to the time: 10 s is a quarter of the way up.
    assert [float(t.y.min()) for t in panel.traces] == pytest.approx([0.0, rise / 4, rise])
    assert float(spectra["signal"].max()) == 4.0  # the data itself is not changed

    # Lines without a colour scale (coloured by experiment): drawn as they are.
    together = _spec("lines", color="_experiment", layout="waterfall")
    assert together.panel.y_ticks and [float(t.y.min()) for t in together.panel.traces] == [0.0, 0.0, 0.0]


def test_one_experiment_has_nothing_to_lay_out():
    data = _data()
    one = data[data["_experiment"] == "A"]
    spec = _xy_spec(one, x="x", y="y", color="_experiment", mode="lines", palette=PALETTE, title="t",
                    ylabel="y", log_x=False, log_y=False, invert_x=False, layout="facet")
    assert spec.layout == "single" and spec.panel.y_ticks


def test_colour_that_leaves_one_point_per_line_is_detected():
    from mfethuls.app.page import _points_own_lines

    series = _series()
    assert _points_own_lines(series, "time_s", None)  # one wavelength of a spectra series
    assert not _points_own_lines(series, "_experiment", None)


def test_style_legend_reacts_only_when_curves_belong_to_it():
    # Colour and style legends: the curves are grouped by colour, so the style legend is a key.
    fig = render(_spec("lines", color="_experiment", style="sample_id"), backend="plotly")
    assert fig.layout.legend.itemclick is None and fig.layout.legend2.itemclick is False
    # Only styles listed: the curves are grouped by style, and clicking one hides its curves.
    fig = render(_spec("lines", color=None, style="sample_id"), backend="plotly")
    assert fig.layout.legend.itemclick is None
    groups = {t.legendgroup for t in fig.data if t.x is not None and len(t.x)}
    assert groups == {"style:S001", "style:S002"}


def test_free_form_normalises_each_experiment_and_y_column():
    from mfethuls.app.page import _normalised_frame

    data = pd.DataFrame({"_experiment": ["A", "A", "B", "B", "C", "C"], "x": [0, 1, 0, 1, 0, 1],
                         "y": [0, 4, 0, 2, 3, 3]})
    out, unchanged = _normalised_frame(data, "x", "y", "max")
    assert out["y"].tolist()[:4] == [0.0, 1.0, 0.0, 1.0]
    assert unchanged == [] and data["y"].tolist()[1] == 4  # the data itself is untouched
    _, unchanged = _normalised_frame(data, "x", "y", "minmax")
    assert unchanged == ["C"]  # flat: drawn as it is


def test_free_form_area_is_summed_over_the_lines_drawn():
    """Heating and cooling of one run share temperatures: integrated as one curve sorted by x they
    would zigzag; each line is integrated on its own."""
    from mfethuls.app.page import _normalised_frame

    data = pd.DataFrame({"_experiment": ["A"] * 4, "profile": ["Heating_1", "Heating_1", "Cooling_1", "Cooling_1"],
                         "x": [0.0, 1.0, 1.0, 0.0], "y": [2.0, 2.0, -2.0, -2.0]})
    out, _ = _normalised_frame(data, "x", "y", "area", lines=["profile"])
    assert out["y"].tolist() == pytest.approx([0.5, 0.5, -0.5, -0.5])  # areas 2 + 2 = 4


def test_free_form_normalises_over_the_x_window():
    from mfethuls.app.page import _normalised_frame

    data = pd.DataFrame({"_experiment": ["A"] * 3, "x": [0.0, 1.0, 2.0], "y": [8.0, 2.0, 4.0]})
    out, _ = _normalised_frame(data, "x", "y", "max", x_range=(1.0, 2.0))
    assert out["y"].tolist() == [2.0, 0.5, 1.0]
