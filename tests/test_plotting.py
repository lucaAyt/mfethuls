import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls import plot_experiments as plot_experiments_root
from mfethuls.plotting import (
    load_comparison_set,
    plot_dma,
    plot_comparison,
    plot_dataset,
    plot_dsc,
    plot_ftir,
    plot_experiments,
    plot_rheology,
    plot_sec,
    plot_uv_vis,
)
from mfethuls.plotting.comparison import ComparisonSet
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
    assert legend.get_title().get_text() == "profile"


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
    assert legend.get_title().get_text() == "source_file"


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


def test_load_comparison_set_preserves_order_and_options(monkeypatch):
    calls = []

    def _fake_loader(name, use_storage=True, refresh=False):
        calls.append((name, use_storage, refresh))
        return Dataset(
            data=pd.DataFrame({"wavelength_nm": [200.0], "absorbance_a_u": [0.1]}),
            metadata={"experiment_name": f"name_{name}", "experiment_id": name},
        )

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    result = load_comparison_set(["EXP003", "EXP001"], use_storage=False, refresh=True)

    assert isinstance(result, ComparisonSet)
    assert [ds.experiment_id for ds in result.datasets] == ["EXP003", "EXP001"]
    assert result.labels == ["name_EXP003", "name_EXP001"]
    assert calls == [
        ("EXP003", False, True),
        ("EXP001", False, True),
    ]


def test_load_comparison_set_label_fallbacks(monkeypatch):
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

    def _fake_loader(name, use_storage=True, refresh=False):
        _ = name, use_storage, refresh
        return queue.pop(0)

    monkeypatch.setattr("mfethuls.comparison.load_experiment_dataset", _fake_loader)

    result = load_comparison_set(["exp_a", "exp_b"])
    assert result.labels == ["EXP777", "dataset_2"]


def test_plot_comparison_auto_overlay_when_shared_x():
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
    assert ax.get_title() == "Comparison Overlay"


def test_plot_comparison_auto_facet_when_x_not_compatible():
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


def test_plot_comparison_explicit_overlay_rejects_incompatible_x():
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


def test_plot_comparison_explicit_stacked_rejects_incompatible_x():
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


def test_plot_comparison_stacked_requires_positive_offset():
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


def test_plot_comparison_remains_compatible_alias():
    ds1 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.1, 0.2, 0.3]}),
        metadata={"experiment_id": "EXP001"},
    )
    ds2 = Dataset(
        data=pd.DataFrame({"wavelength_nm": [200, 250, 300], "absorbance_a_u": [0.15, 0.25, 0.35]}),
        metadata={"experiment_id": "EXP002"},
    )

    fig, ax = _close(plot_comparison([ds1, ds2], mode="auto", kind="uv_vis"))
    assert len(ax.lines) == 2


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
