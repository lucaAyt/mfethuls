import numpy as np
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting import PlotError, build_dataset_spec, build_experiments_spec
from mfethuls.plotting.backend import render
from mfethuls.plotting.comparison import shares_x_axis
from mfethuls.plotting.dsc import DSC_EXPERIMENT_LINESTYLES


def _uv_vis(name, y):
    return Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": y}),
        metadata={"experiment_id": name},
    )


def _dsc(name):
    return Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": [25, 50, 75, 75, 50, 25],
                "heat_flow_mW": [0.0, 1.2, 0.8, 0.1, 1.1, 0.9],
                "profile": ["Heating_1"] * 3 + ["Cooling_1"] * 3,
            }
        ),
        metadata={"experiment_id": name},
    )


def test_single_signal_spec_uses_canonical_columns():
    spec = build_dataset_spec(_uv_vis("EXP001", [0.1, 0.4, 0.2]))

    panel = spec.panel
    assert spec.layout == "single"
    assert (panel.xlabel, panel.ylabel) == ("Wavelength (nm)", "Absorbance (a.u.)")
    assert len(panel.traces) == 1
    assert isinstance(panel.traces[0].x, np.ndarray)
    assert panel.legend is False


@pytest.mark.parametrize(
    ("columns", "reversed_x", "xscale", "yscale"),
    [
        ({"wavenumber_cm_inv": [500, 1000], "absorbance_a_u": [0.2, 0.5]}, True, "linear", "linear"),
        ({"chemical_shift_ppm": [1.0, 2.0], "intensity_a_u": [3.0, 4.0]}, True, "linear", "linear"),
        ({"q_inv_nm": [0.1, 1.0], "intensity_a_u": [10.0, 1.0]}, False, "log", "log"),
    ],
)
def test_axis_direction_and_scale_flags(columns, reversed_x, xscale, yscale):
    panel = build_dataset_spec(Dataset(data=pd.DataFrame(columns), metadata={})).panel

    assert panel.x_reversed is reversed_x
    assert (panel.xscale, panel.yscale) == (xscale, yscale)


def test_dma_temperature_sweep_keeps_linear_x():
    dataset = Dataset(
        data=pd.DataFrame(
            {"temperature_C": [20, 40], "storage_modulus_mpa": [100, 50], "loss_modulus_mpa": [10, 20]}
        ),
    )

    panel = build_dataset_spec(dataset).panel
    assert (panel.xscale, panel.yscale) == ("linear", "log")
    assert [trace.label for trace in panel.traces] == ["Storage modulus", "Loss modulus"]


def test_overlay_prefixes_labels_with_experiment():
    spec = build_experiments_spec([_uv_vis("A", [0.1, 0.2, 0.3]), _uv_vis("B", [0.2, 0.3, 0.4])])

    assert [trace.label for trace in spec.panel.traces] == ["A", "B"]
    assert spec.panel.title == "Comparison Overlay"


def test_stacked_offsets_y_values_and_keeps_reversed_axis():
    def _ftir(name):
        return Dataset(
            data=pd.DataFrame({"wavenumber_cm_inv": [500, 1000, 1500], "absorbance_a_u": [0.1, 0.2, 0.3]}),
            metadata={"experiment_id": name},
        )

    spec = build_experiments_spec([_ftir("A"), _ftir("B"), _ftir("C")], mode="stacked", stacked_offset=1.0)

    traces = spec.panel.traces
    assert spec.panel.x_reversed is True
    np.testing.assert_allclose(traces[2].y - traces[0].y, [2.0, 2.0, 2.0])


def test_dsc_overlay_encodes_segment_by_colour_and_experiment_by_linestyle():
    spec = build_experiments_spec([_dsc("A"), _dsc("B")], mode="overlay")

    panel = spec.panel
    segments, experiments = panel.legends
    assert [entry.label for entry in segments.entries] == ["Heating_1", "Cooling_1"]
    assert [entry.label for entry in experiments.entries] == ["A", "B"]

    by_label = {trace.label: trace for trace in panel.traces}
    assert by_label["A | Heating_1"].color == by_label["B | Heating_1"].color
    assert by_label["A | Heating_1"].linestyle == DSC_EXPERIMENT_LINESTYLES[0]
    assert by_label["B | Heating_1"].linestyle == DSC_EXPERIMENT_LINESTYLES[1]
    # Experiment legend entries toggle that experiment's traces in Plotly.
    assert by_label["B | Cooling_1"].legend_group == experiments.entries[1].group


def test_facet_has_one_panel_per_dataset_named_after_it():
    other = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50], "heat_flow_mW": [0.2, 0.4]}),
        metadata={"experiment_id": "B"},
    )

    spec = build_experiments_spec([_uv_vis("A", [0.1, 0.2, 0.3]), other], title="Mixed")

    assert spec.layout == "facet"
    assert spec.title == "Mixed"
    assert [panel.xlabel for panel in spec.panels] == ["Wavelength (nm)", "Temperature (°C)"]
    assert [panel.title for panel in spec.panels] == ["A", "B"]  # which panel is which experiment
    assert not spec.shared_x  # wavelength and temperature: no common x-axis


def _dsc_run(name, heat):
    return Dataset(data=pd.DataFrame({"temperature_C": [25.0, 50.0, 75.0], "heat_flow_mW": heat}),
                   metadata={"experiment_name": name, "instrument_type": "dsc"})


def test_panels_with_a_common_x_quantity_share_the_x_axis():
    spec = build_experiments_spec([_dsc_run("A", [0.1, 0.2, 0.3]), _dsc_run("B", [1.0, 2.0, 3.0])], mode="facet")
    assert spec.layout == "facet" and spec.shared_x
    assert shares_x_axis([_dsc_run("A", [0.1, 0.2, 0.3]), _dsc_run("B", [1.0, 2.0, 3.0])])

    fig = render(spec, backend="plotly")
    assert fig.layout.xaxis.matches == "x2" or fig.layout.xaxis2.matches == "x"  # zooming one zooms all
    assert [a.text for a in fig.layout.annotations] == ["A", "B"]
    names = [t.name for t in fig.data if t.showlegend]
    assert len(names) == len(set(names))  # each legend entry once, not once per panel


def test_offset_stacks_experiments_by_the_tallest_range_and_hides_the_y_values():
    spec = build_experiments_spec([_dsc_run("A", [0.0, 1.0, 2.0]), _dsc_run("B", [0.0, 0.5, 1.0])], mode="stacked")
    by_experiment = {}
    for trace in spec.panel.traces:
        by_experiment.setdefault(trace.label.split(" | ")[0], []).extend(trace.y)
    assert min(by_experiment["B"]) == pytest.approx(1.1 * 2.0)  # 1.1 x the tallest range (A: 2)
    assert not spec.panel.y_ticks and spec.panel.ylabel.endswith("(offset)")

    wider = build_experiments_spec([_dsc_run("A", [0.0, 1.0, 2.0]), _dsc_run("B", [0.0, 0.5, 1.0])], mode="stacked",
                                   spacing=2.0)
    assert min(t.y.min() for t in wider.panel.traces if t.label.startswith("B")) == pytest.approx(4.4)
    fixed = build_experiments_spec([_dsc_run("A", [0.0, 1.0, 2.0]), _dsc_run("B", [0.0, 0.5, 1.0])], mode="stacked",
                                   stacked_offset=10.0)
    assert min(t.y.min() for t in fixed.panel.traces if t.label.startswith("B")) == pytest.approx(10.0)
    with pytest.raises(PlotError):
        build_experiments_spec([_dsc_run("A", [0.0, 1.0, 2.0]), _dsc_run("B", [0.0, 0.5, 1.0])], mode="stacked",
                               stacked_offset=0)


def test_offset_on_a_log_axis_is_a_factor():
    from mfethuls.plotting.comparison import stack_step
    from mfethuls.plotting.spec import Panel, Trace

    panels = [Panel(traces=[Trace(np.array([1.0, 2.0]), np.array([1.0, 100.0]))], yscale="log")]
    assert stack_step(panels, "auto", log=True) == pytest.approx(2.2)  # 2 decades x 1.1


def test_matplotlib_panels_share_x_and_name_each_panel():
    import matplotlib

    spec = build_experiments_spec([_dsc_run("A", [0.1, 0.2, 0.3]), _dsc_run("B", [1.0, 2.0, 3.0])], mode="facet")
    fig, axes = render(spec, backend="matplotlib")
    assert axes[0, 0].get_shared_x_axes().joined(axes[0, 0], axes[1, 0])
    assert [axis.get_title(loc="left") for axis in axes.ravel()] == ["A", "B"]
    assert axes[0, 0].get_xlabel() == "" and axes[1, 0].get_xlabel() == "Temperature (°C)"
    matplotlib.pyplot.close(fig)


def test_matplotlib_figure_has_no_title_minor_y_ticks_and_columns_for_a_long_legend():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.ticker import AutoMinorLocator

    from mfethuls.plotting.render_mpl import render as render_mpl
    from mfethuls.plotting.spec import Panel, PlotSpec, Trace

    x = np.linspace(0, 1, 5)
    panel = Panel(traces=[Trace(x, x * i, label=f"test {i}") for i in range(40)], title="Title",
                  xlabel="x", ylabel="y", legend=True, legend_title="name")
    fig, ax = render_mpl(PlotSpec([panel]))
    fig.draw_without_rendering()
    assert ax.get_title() == ""
    assert isinstance(ax.yaxis.get_minor_locator(), AutoMinorLocator)
    legend = ax.get_legend()
    assert legend._ncols > 1
    # The axes keep a usable size: the legend widens the figure instead of squashing them.
    assert ax.get_position().height * fig.get_figheight() > 3
    assert legend.get_window_extent().x0 >= ax.get_window_extent().x1  # outside, right of the axes
    plt.close(fig)


def _nmr(name, nuclei):
    rows = [{"chemical_shift_ppm": ppm, "intensity_a_u": 1.0, "nucleus": nucleus,
             "source_file": f"{i + 1}/pdata/1"}
            for i, nucleus in enumerate(nuclei) for ppm in (10.0, 5.0, 0.0)]
    return Dataset(data=pd.DataFrame(rows), metadata={"instrument_type": "nmr", "experiment_name": name})


def test_nmr_gets_one_panel_per_nucleus_named_on_its_axis():
    from mfethuls.plotting.nmr import build_nmr_spec

    single = build_nmr_spec(_nmr("A", ["1H"]))
    assert single.layout == "single" and single.panel.xlabel == "$^{1}$H chemical shift (ppm)"
    both = build_nmr_spec(_nmr("A", ["1H", "13C"]))
    assert both.layout == "facet"
    assert [p.xlabel for p in both.panels] == ["$^{1}$H chemical shift (ppm)", "$^{13}$C chemical shift (ppm)"]
    assert all(p.x_reversed for p in both.panels)


def test_nmr_comparison_overlays_each_nucleus_in_its_own_panel():
    spec = build_experiments_spec([_nmr("A", ["1H", "13C"]), _nmr("B", ["1H"])])
    assert spec.layout == "facet"
    assert [[t.label for t in p.traces] for p in spec.panels] == [["A", "B"], ["A"]]
    assert spec.panels[1].xlabel == "$^{13}$C chemical shift (ppm)"
    same = build_experiments_spec([_nmr("A", ["13C"]), _nmr("B", ["13C"])])
    assert same.layout == "single" and same.panel.xlabel == "$^{13}$C chemical shift (ppm)"
    facet = build_experiments_spec([_nmr("A", ["1H", "13C"]), _nmr("B", ["1H"])], mode="facet")
    assert len(facet.panels) == 3  # A's two nuclei, then B


def test_overlay_gives_each_experiment_its_own_colour():
    spec = build_experiments_spec([_nmr("A", ["1H"]), _nmr("B", ["1H"])])
    assert len({t.color for t in spec.panel.traces}) == 2
    alone = build_experiments_spec([_nmr("A", ["1H"])])
    assert alone.panel.traces[0].color == "#8c564b"  # a single experiment keeps the family colour


def test_nmr_panels_go_lightest_nucleus_first_and_experiments_keep_their_colour():
    from mfethuls.plotting.nmr import build_nmr_spec

    # Expno 1 holds the 13C spectrum here (as in a real dataset): 1H still comes first.
    assert [p.xlabel for p in build_nmr_spec(_nmr("A", ["13C", "1H"])).panels] == [
        "$^{1}$H chemical shift (ppm)", "$^{13}$C chemical shift (ppm)"]
    spec = build_experiments_spec([_nmr("A", ["1H"]), _nmr("B", ["13C", "1H"])])
    colours = [{t.label: t.color for t in p.traces} for p in spec.panels]
    assert colours[0]["B"] == colours[1]["B"] != colours[0]["A"]
