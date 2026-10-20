import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls import plot_experiments as plot_experiments_root
from mfethuls.plotting import (
    load_experiments,
    plot_dma,
    plot_dataset,
    plot_dsc,
    plot_fluorescence,
    plot_ftir,
    plot_experiments,
    plot_rheology,
    plot_sec,
    plot_uv_vis,
)
from mfethuls.plotting.comparison import ComparisonSet
from mfethuls.plotting.core import PlotError, build_dataset_spec
from mfethuls.plotting.comparison import build_experiments_spec


def _close(result):
    fig, ax = result
    plt.close(fig)
    return fig, ax


def test_plot_uv_vis_chooses_absorbance():
    dataset = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.4, 0.2]}),
        metadata={"experiment_id": "EXP001"},
    )

    fig, ax = _close(plot_uv_vis(dataset))
    assert ax.get_xlabel() == "Wavelength (nm)"
    assert ax.get_ylabel() == "Absorbance (a.u.)"
    assert len(ax.lines) == 1


def test_plot_fluorescence_uses_emission_counts():
    dataset = Dataset(
        data=pd.DataFrame({"wavelength_nm": [400, 450, 500], "emission_counts": [12.0, 80.0, 30.0]}),
        metadata={"experiment_id": "EXP001"},
    )

    fig, ax = _close(plot_fluorescence(dataset))
    assert ax.get_xlabel() == "Wavelength (nm)"
    assert ax.get_ylabel() == "Emission intensity (counts)"


@pytest.mark.parametrize("metadata", [{"instrument_type": "fluorescence"}, {}])
def test_plot_dataset_dispatches_fluorescence_by_metadata_or_columns(metadata):
    dataset = Dataset(
        data=pd.DataFrame({"wavelength_nm": [400, 450, 500], "emission_counts": [12.0, 80.0, 30.0]}),
        metadata={"experiment_id": "EXP001", **metadata},
    )

    fig, ax = _close(plot_dataset(dataset))
    assert ax.get_ylabel() == "Emission intensity (counts)"
    assert "Fluorescence" in build_dataset_spec(dataset).panel.title
    assert ax.get_title() == ""  # publication figures carry no title


def test_plot_uv_vis_rejects_fluorescence_data():
    dataset = Dataset(
        data=pd.DataFrame({"wavelength_nm": [400, 450], "emission_counts": [12.0, 80.0]}),
        metadata={"experiment_id": "EXP001"},
    )

    with pytest.raises(PlotError):
        plot_uv_vis(dataset)


def test_builtin_plots_stay_black_on_white_under_dark_style():
    """marimo's dark theme applies dark_background globally; saved figures must stay readable."""
    dataset = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.4, 0.2]}),
        metadata={"experiment_id": "EXP001"},
    )
    black, white = (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0, 1.0)

    with plt.style.context("dark_background"):
        fig, ax = plot_uv_vis(dataset)
        fig.canvas.draw()  # ticks created at draw time must also stay black
        assert fig.get_facecolor() == white
        assert ax.get_facecolor() == white
        assert matplotlib.colors.to_rgba(ax.xaxis.label.get_color()) == black
        assert matplotlib.colors.to_rgba(ax.title.get_color()) == black
        assert matplotlib.colors.to_rgba(ax.spines["bottom"].get_edgecolor()) == black
        tick_colors = {matplotlib.colors.to_rgba(t.get_color()) for t in ax.get_xticklabels() + ax.get_yticklabels()}
        assert tick_colors == {black}
    plt.close(fig)


def test_facet_figure_height_scales_with_panel_count():
    def _dataset(name, x, y):
        return Dataset(
            data=pd.DataFrame({x: [1.0, 2.0, 3.0], y: [0.1, 0.2, 0.3]}),
            metadata={"experiment_id": name, "experiment_name": name},
        )

    datasets = [
        _dataset("a", "wavelength_nm", "absorbance_a_u"),
        _dataset("b", "wavenumber_cm_inv", "transmittance_pct"),
        _dataset("c", "temperature_C", "heat_flow_mW"),
    ]

    fig_two, _ = _close(plot_experiments(datasets[:2], mode="facet"))
    fig_three, _ = _close(plot_experiments(datasets, mode="facet"))

    width_two, height_two = fig_two.get_size_inches()
    width_three, height_three = fig_three.get_size_inches()
    assert width_two == width_three
    assert height_three / height_two == pytest.approx(3 / 2)


def test_plot_dsc_uses_canonical_columns():
    dataset = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50, 75], "heat_flow_mW": [0.0, 1.2, 0.8]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_dsc(dataset))
    assert ax.get_xlabel() == "Temperature (°C)"
    assert ax.get_ylabel() == "Heat flow (mW)"
    assert len(ax.lines) == 1


def test_plot_dsc_defaults_to_profile_grouping_when_available():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": [25, 50, 75, 25, 50, 75],
                "heat_flow_mW": [0.0, 1.2, 0.8, 0.1, 1.1, 0.9],
                "profile": ["Heating", "Heating", "Heating", "Cooling", "Cooling", "Cooling"],
            }
        ),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_dsc(dataset))
    assert len(ax.lines) == 2
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_title().get_text() == "Segment"


def test_plot_dsc_comparison_overlay_colours_segments_and_styles_experiments():
    ds1 = Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": [25, 50, 75, 75, 50, 25],
                "heat_flow_mW": [0.0, 1.2, 0.8, 0.1, 1.1, 0.9],
                "profile": ["Heating_1"] * 3 + ["Cooling_1"] * 3,
            }
        ),
        metadata={"experiment_id": "EXP_DSC_A"},
    )
    ds2 = Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": [25, 50, 75, 75, 50, 25],
                "heat_flow_mW": [0.1, 1.3, 0.9, 0.2, 1.2, 1.0],
                "profile": ["Heating_1"] * 3 + ["Cooling_1"] * 3,
            }
        ),
        metadata={"experiment_id": "EXP_DSC_B"},
    )

    fig, ax = _close(plot_experiments([ds1, ds2], mode="overlay", kind="dsc"))
    assert len(ax.lines) == 4
    # One legend in two sections: segments (colour), then experiments (line style).
    legend = ax.get_legend()
    assert legend.get_title().get_text() == "Segment"
    assert [t.get_text() for t in legend.get_texts()] == ["Heating_1", "Cooling_1", "", "Experiment", "EXP_DSC_A", "EXP_DSC_B"]
    assert not ax.artists  # nothing outside the layout, so nothing is clipped from saved figures

    # Same segment colour for both experiments, different line styles
    assert ax.lines[0].get_color() == ax.lines[2].get_color()
    assert ax.lines[0].get_linestyle() != ax.lines[2].get_linestyle()


def test_plot_dsc_colours_segments_by_type_and_cycle():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "temperature_C": list(range(12)),
                "heat_flow_mW": [0.1] * 12,
                "profile": ["Isothermal_1"] * 2 + ["Heating_1"] * 2 + ["Cooling_1"] * 2
                + ["Isothermal_2"] * 2 + ["Heating_2"] * 2 + ["Cooling_2"] * 2,
            }
        ),
        metadata={"experiment_id": "EXP_DSC_C"},
    )

    fig, ax = _close(plot_dsc(dataset))
    colors = {line.get_label(): line.get_color() for line in ax.lines}

    # Later cycles get a darker shade of the same colour
    for early, late in [("Heating_1", "Heating_2"), ("Cooling_1", "Cooling_2")]:
        assert sum(colors[late][:3]) < sum(colors[early][:3])
    # Heating is red-dominant, cooling blue-dominant, isothermal grey
    assert colors["Heating_1"][0] > colors["Heating_1"][2]
    assert colors["Cooling_1"][2] > colors["Cooling_1"][0]
    r, g, b, _ = colors["Isothermal_1"]
    assert max(r, g, b) - min(r, g, b) < 0.01


def test_plot_ftir_chooses_absorbance_and_reverses_axis():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavenumber_cm_inv": [500, 1000, 1500, 2000],
                "absorbance_a_u": [0.2, 0.5, 0.35, 0.1],
            }
        ),
        metadata={"experiment_id": "EXP_FTIR_001"},
    )

    fig, ax = _close(plot_ftir(dataset))
    assert ax.get_xlabel() == r"Wavenumber (cm$^{-1}$)"
    assert ax.get_ylabel() == "Absorbance (a.u.)"
    assert len(ax.lines) == 1
    left, right = ax.get_xlim()
    assert left > right


def test_plot_rheology_plots_against_what_the_run_swept():
    # A frequency sweep: temperature drifts a little and time runs, but only the frequency was swept.
    dataset = Dataset(data=pd.DataFrame({
        "time_s": [1.0, 2.0, 3.0],
        "temperature_C": [20.95, 20.96, 20.97],
        "strain_pct": [0.99, 1.0, 1.01],
        "angular_frequency_rad_s": [0.1, 1.0, 10.0],
        "storage_modulus_pa": [10, 100, 1000],
        "loss_modulus_pa": [5, 50, 500],
    }))

    fig, ax = _close(plot_rheology(dataset))
    assert ax.get_xlabel() == r"Angular frequency (rad s$^{-1}$)"
    assert len(ax.lines) == 2
    fig, ax = _close(plot_rheology(dataset, x="time_s"))  # another axis on request
    assert ax.get_xlabel() == "Time (s)"


def test_plot_rheology_draws_a_flow_curve_as_stress_and_viscosity():
    dataset = Dataset(data=pd.DataFrame({
        "shear_rate_s_inv": [0.1, 1.0, 10.0],
        "shear_stress_pa": [1.0, 5.0, 20.0],
        "viscosity_pa_s": [10.0, 5.0, 2.0],
    }))
    fig, ax = _close(plot_rheology(dataset))
    assert ax.get_xlabel() == r"Shear rate (s$^{-1}$)"
    from mfethuls.plotting.labels import legend_name

    assert [line.get_label() for line in ax.lines] == [legend_name("shear_stress_pa"), legend_name("viscosity_pa_s")]


def test_plot_dma_plots_against_what_the_run_swept():
    # A strain sweep at 1 Hz while the temperature crept from 26 to 28 °C (as in a real TA Q800 file).
    dataset = Dataset(data=pd.DataFrame({
        "time_s": [3.0, 600.0, 1200.0],
        "temperature_C": [25.98, 27.0, 28.2],
        "frequency_hz": [1.0, 1.0, 1.0],
        "strain_pct": [0.1, 0.5, 1.01],
        "storage_modulus_mpa": [10, 100, 1000],
        "loss_modulus_mpa": [5, 50, 500],
    }))

    fig, ax = _close(plot_dma(dataset))
    assert ax.get_xlabel() == "Strain (%)"
    assert len(ax.lines) == 2


def test_a_run_that_swept_nothing_is_plotted_against_time():
    from mfethuls.plotting.sweeps import sweep_axis

    held = pd.DataFrame({"time_s": [1.0, 60.0], "temperature_C": [25.74, 25.75], "strain_pct": [0.998, 1.01],
                         "angular_frequency_rad_s": [10.0, 10.0]})
    assert sweep_axis(held, ["temperature_C", "angular_frequency_rad_s", "strain_pct", "time_s"]) == "time_s"
    assert sweep_axis(held.drop(columns="time_s"), ["temperature_C", "strain_pct"]) is None
    ramp = held.assign(temperature_C=[-50.0, 150.0])
    assert sweep_axis(ramp, ["temperature_C", "angular_frequency_rad_s", "time_s"]) == "temperature_C"


def test_plot_sec_groups_by_detector():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "retention_time_min": [1, 2, 1, 2],
                "detector_response_a_u": [10, 20, 30, 40],
                "detector_name": ["uv", "uv", "ri", "ri"],
            }
        ),
        metadata={"experiment_id": "EXP003"},
    )

    fig, ax = _close(plot_sec(dataset))
    assert len(ax.lines) == 2
    assert sorted(line.get_label() for line in ax.lines) == ["ri", "uv"]


def test_plot_dataset_dispatches_from_columns():
    dataset = Dataset(
        data=pd.DataFrame({"mz": [10, 20, 30], "intensity_a_u": [1, 3, 2]}),
        metadata={"experiment_id": "EXP004"},
    )

    fig, ax = _close(plot_dataset(dataset))
    assert ax.get_xlabel() == "$m/z$"
    assert ax.get_ylabel() == "Intensity (a.u.)"


def test_plot_dataset_dispatches_ftir_from_columns():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavenumber_cm_inv": [800, 1200, 1600],
                "transmittance_pct": [90, 75, 82],
            }
        ),
        metadata={"experiment_id": "EXP_FTIR_002"},
    )

    fig, ax = _close(plot_dataset(dataset))
    assert ax.get_xlabel() == r"Wavenumber (cm$^{-1}$)"
    assert ax.get_ylabel() == "Transmittance (%)"


def test_plot_dataset_dispatches_dma_from_metadata_and_profile():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "strain_pct": [0.1, 0.5, 1.0],
                "storage_modulus_mpa": [100, 120, 140],
                "loss_modulus_mpa": [40, 45, 55],
            }
        ),
        metadata={
            "instrument_type": "dma",
            "measurement_profile": "oscillatory_strain_sweep",
        },
    )

    fig, ax = _close(plot_dataset(dataset))
    assert ax.get_xlabel() == "Strain (%)"


def test_plot_dataset_dispatches_dma_from_profile_without_instrument_type():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "strain_pct": [0.05, 0.2, 0.8],
                "storage_modulus_mpa": [90, 110, 130],
                "loss_modulus_mpa": [30, 35, 42],
            }
        ),
        metadata={"measurement_profile": "oscillatory_strain_sweep"},
    )

    fig, ax = _close(plot_dataset(dataset))
    assert ax.get_xlabel() == "Strain (%)"


def test_plotting_fails_on_missing_columns():
    dataset = Dataset(data=pd.DataFrame({"temperature_C": [1, 2, 3]}), metadata={})

    with pytest.raises(PlotError):
        plot_dsc(dataset)


def test_plot_uv_vis_infers_grouping_from_duplicate_x_segments():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavelength_nm": [200, 250, 300, 200, 250, 300],
                "absorbance_a_u": [0.1, 0.2, 0.3, 0.15, 0.25, 0.35],
                "timestamp": ["t1", "t1", "t1", "t2", "t2", "t2"],
            }
        ),
        metadata={"experiment_id": "EXP_GRP_001"},
    )

    fig, ax = _close(plot_uv_vis(dataset))
    assert len(ax.lines) == 2
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_title().get_text() == "timestamp"


def test_plot_uv_vis_respects_explicit_group_by():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavelength_nm": [200, 250, 300, 200, 250, 300],
                "absorbance_a_u": [0.1, 0.2, 0.3, 0.15, 0.25, 0.35],
                "source_file": ["a", "a", "a", "b", "b", "b"],
            }
        ),
        metadata={"experiment_id": "EXP_GRP_002"},
    )

    fig, ax = _close(plot_dataset(dataset, kind="uv_vis", group_by="source_file"))
    assert len(ax.lines) == 2
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_title().get_text() == "File"


def test_plot_uv_vis_uses_gradient_palette_for_dense_groups():
    x_values = [200, 250, 300]
    rows = []
    for group_index in range(11):
        group_label = f"g{group_index:02d}"
        for offset, x_value in enumerate(x_values):
            rows.append(
                {
                    "wavelength_nm": x_value,
                    "absorbance_a_u": 0.1 + (group_index * 0.01) + (offset * 0.005),
                    "source_file": group_label,
                }
            )

    dataset = Dataset(data=pd.DataFrame(rows), metadata={"experiment_id": "EXP_GRP_003"})

    fig, ax = _close(plot_dataset(dataset, kind="uv_vis", group_by="source_file"))
    assert len(ax.lines) == 11
    assert len({line.get_color() for line in ax.lines}) == 11


def test_plot_dataset_group_by_respects_max_groups(caplog):
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavelength_nm": [200, 250, 300, 200, 250, 300],
                "absorbance_a_u": [0.1, 0.2, 0.3, 0.15, 0.25, 0.35],
                "source_file": ["a", "b", "c", "d", "e", "f"],
            }
        ),
        metadata={"instrument_type": "uv_vis"},
    )

    caplog.set_level("WARNING", logger="mfethuls.plotting.core")
    fig, ax = _close(plot_dataset(dataset, group_by="source_file", max_groups=3))
    assert len(ax.lines) == 0
    assert "Skipping grouped plot" in caplog.text


def test_plot_sec_group_by_respects_max_groups(caplog):
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "retention_time_min": [1, 2, 1, 2, 1, 2],
                "detector_response_a_u": [10, 20, 30, 40, 50, 60],
                "source_file": ["a", "b", "c", "d", "e", "f"],
            }
        ),
        metadata={"instrument_type": "sec"},
    )

    caplog.set_level("WARNING", logger="mfethuls.plotting.sec")
    fig, ax = _close(plot_sec(dataset, group_by="source_file", max_groups=3))
    assert len(ax.lines) == 0
    assert "Skipping grouped SEC plot" in caplog.text


def test_plot_uv_vis_logs_when_inferred_grouping_ties(caplog):
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "wavelength_nm": [200, 250, 300, 200, 250, 300],
                "absorbance_a_u": [0.1, 0.2, 0.3, 0.15, 0.25, 0.35],
                "group_alpha": ["a", "a", "a", "b", "b", "b"],
                "group_beta": ["x", "x", "x", "y", "y", "y"],
            }
        ),
        metadata={"instrument_type": "uv_vis"},
    )

    caplog.set_level("WARNING", logger="mfethuls.plotting.core")
    fig, ax = _close(plot_dataset(dataset))
    assert len(ax.lines) == 2
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_title().get_text() == "group_alpha"
    assert "Grouping inference tie detected" in caplog.text


def _dsc_registry(*names):
    from mfethuls import Registry

    return Registry.from_frame(pd.DataFrame([{"name": name, "instrument_name": "dsc_mettler_toledo_v0"} for name in names]))


def test_load_experiments_preserves_order_and_options(monkeypatch):
    calls = []

    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = kwargs
        calls.append((name, use_storage, refresh))
        return Dataset(
            data=pd.DataFrame({"wavelength_nm": [200.0], "absorbance_a_u": [0.1]}),
            metadata={"experiment_name": f"name_{name}", "experiment_id": name},
        )

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    result = load_experiments(["EXP003", "EXP001"], registry=_dsc_registry("EXP003", "EXP001"),
                                          use_storage=False, refresh=True)

    assert isinstance(result, ComparisonSet)
    assert [ds.experiment_id for ds in result.datasets] == ["EXP003", "EXP001"]
    assert result.labels == ["name_EXP003", "name_EXP001"]
    assert calls == [
        ("EXP003", False, True),
        ("EXP001", False, True),
    ]


def test_load_experiments_label_fallbacks(monkeypatch):
    queue = [
        Dataset(
            data=pd.DataFrame({"temperature_C": [25.0], "heat_flow_mW": [0.2]}),
            metadata={"experiment_id": "EXP777"},
        ),
        Dataset(
            data=pd.DataFrame({"temperature_C": [30.0], "heat_flow_mW": [0.3]}),
            metadata={},
        ),
    ]

    def _fake_loader(name, use_storage=True, refresh=False, **kwargs):
        _ = name, use_storage, refresh, kwargs
        return queue.pop(0)

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    result = load_experiments(["exp_a", "exp_b"], registry=_dsc_registry("exp_a", "exp_b"))
    assert result.labels == ["EXP777", "dataset_2"]


def test_plot_experiments_auto_overlay_when_shared_x():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.15, 0.25, 0.35]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_experiments([ds1, ds2], mode="auto", kind="uv_vis"))
    assert len(ax.lines) == 2
    assert ax.get_title() == ""  # the title is the Plotly figure's only
    assert build_experiments_spec([ds1, ds2], kind="uv_vis").panel.title == "Comparison Overlay"


def test_plot_experiments_auto_facet_when_x_not_compatible():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50, 75], "heat_flow_mW": [0.2, 0.4, 0.1]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, axes = plot_experiments([ds1, ds2], mode="auto")
    plt.close(fig)
    assert axes.shape[0] == 2
    assert axes[0, 0].get_xlabel() == "Wavelength (nm)"
    assert axes[1, 0].get_xlabel() == "Temperature (°C)"
    assert axes[0, 0].get_title() == ""
    assert axes[1, 0].get_title() == ""


def test_plot_experiments_explicit_overlay_rejects_incompatible_x():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50, 75], "heat_flow_mW": [0.2, 0.4, 0.1]}),
        metadata={"experiment_id": "EXP002"},
    )

    with pytest.raises(PlotError):
        plot_experiments([ds1, ds2], mode="overlay")


def test_plot_experiments_explicit_stacked_rejects_incompatible_x():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50, 75], "heat_flow_mW": [0.2, 0.4, 0.1]}),
        metadata={"experiment_id": "EXP002"},
    )

    with pytest.raises(PlotError):
        plot_experiments([ds1, ds2], mode="stacked", stacked_offset=0.5)


def test_plot_experiments_stacked_requires_positive_offset():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.2, 0.3, 0.4]}),
        metadata={"experiment_id": "EXP002"},
    )

    with pytest.raises(PlotError):
        plot_experiments([ds1, ds2], mode="stacked", stacked_offset=0.0)


def test_plot_experiments_is_available_from_package_root():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.15, 0.25, 0.35]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_experiments_root([ds1, ds2], mode="auto", kind="uv_vis"))
    assert len(ax.lines) == 2
