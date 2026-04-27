import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting import (
    plot_dma,
    plot_dataset,
    plot_dsc,
    plot_ftir,
    plot_rheology,
    plot_sec,
    plot_uv_vis,
)
from mfethuls.plotting.core import PlotError


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
    assert ax.get_xlabel() == "wavelength_nm"
    assert ax.get_ylabel() == "absorbance_a_u"
    assert len(ax.lines) == 1


def test_plot_dsc_uses_canonical_columns():
    dataset = Dataset(
        data=pd.DataFrame({"temperature_C": [25, 50, 75], "heat_flow_mW": [0.0, 1.2, 0.8]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_dsc(dataset))
    assert ax.get_xlabel() == "temperature_C"
    assert ax.get_ylabel() == "heat_flow_mW"
    assert len(ax.lines) == 1


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
    assert ax.get_xlabel() == "wavenumber_cm_inv"
    assert ax.get_ylabel() == "absorbance_a_u"
    assert len(ax.lines) == 1
    left, right = ax.get_xlim()
    assert left > right


def test_plot_rheology_uses_profile_requirements():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "angular_frequency_rad_s": [0.1, 1.0, 10.0],
                "storage_modulus_pa": [10, 100, 1000],
                "loss_modulus_pa": [5, 50, 500],
            }
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )

    fig, ax = _close(plot_rheology(dataset))
    assert ax.get_xlabel() == "angular_frequency_rad_s"
    assert len(ax.lines) == 2


def test_plot_dma_uses_profile_requirements():
    dataset = Dataset(
        data=pd.DataFrame(
            {
                "frequency_hz": [0.1, 1.0, 10.0],
                "storage_modulus_mpa": [10, 100, 1000],
                "loss_modulus_mpa": [5, 50, 500],
            }
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )

    fig, ax = _close(plot_dma(dataset))
    assert ax.get_xlabel() == "frequency_hz"
    assert len(ax.lines) == 2


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
    assert ax.get_xlabel() == "mz"
    assert ax.get_ylabel() == "intensity_a_u"


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
    assert ax.get_xlabel() == "wavenumber_cm_inv"
    assert ax.get_ylabel() == "transmittance_pct"


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
    assert ax.get_xlabel() == "strain_pct"


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
    assert ax.get_xlabel() == "strain_pct"


def test_plotting_fails_on_missing_columns():
    dataset = Dataset(data=pd.DataFrame({"temperature_C": [1, 2, 3]}), metadata={})

    with pytest.raises(PlotError):
        plot_dsc(dataset)
