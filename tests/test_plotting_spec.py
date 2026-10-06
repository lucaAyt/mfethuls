import numpy as np
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting import build_dataset_spec, build_experiments_spec
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
                "profile": ["Heating_0"] * 3 + ["Cooling_0"] * 3,
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
        metadata={"measurement_profile": "oscillatory_temperature_sweep"},
    )

    panel = build_dataset_spec(dataset).panel
    assert (panel.xscale, panel.yscale) == ("linear", "log")
    assert [trace.label for trace in panel.traces] == [r"Storage modulus $E'$", r"Loss modulus $E''$"]


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
    assert [entry.label for entry in segments.entries] == ["Heating_0", "Cooling_0"]
    assert [entry.label for entry in experiments.entries] == ["A", "B"]

    by_label = {trace.label: trace for trace in panel.traces}
    assert by_label["A | Heating_0"].color == by_label["B | Heating_0"].color
    assert by_label["A | Heating_0"].linestyle == DSC_EXPERIMENT_LINESTYLES[0]
    assert by_label["B | Heating_0"].linestyle == DSC_EXPERIMENT_LINESTYLES[1]
    # Experiment legend entries toggle that experiment's traces in Plotly.
    assert by_label["B | Cooling_0"].legend_group == experiments.entries[1].group


def test_facet_has_one_untitled_panel_per_dataset():
    other = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50], "heat_flow_mW": [0.2, 0.4]}),
        metadata={"experiment_id": "B"},
    )

    spec = build_experiments_spec([_uv_vis("A", [0.1, 0.2, 0.3]), other], title="Mixed")

    assert spec.layout == "facet"
    assert spec.title == "Mixed"
    assert [panel.xlabel for panel in spec.panels] == ["Wavelength (nm)", "Temperature (°C)"]
    assert all(panel.title is None for panel in spec.panels)
