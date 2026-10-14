import json
from pathlib import Path

import pandas as pd
import pytest

import mfethuls.config
from mfethuls.dataset import Dataset
from mfethuls.plotting import build_dataset_spec
from mfethuls.plotting.labels import (
    COLUMN_LABELS,
    axis_label,
    legend_name,
    mathtext_to_html,
    shared_axis_label,
)


SCHEMA_DIR = Path(mfethuls.config.__file__).parent / "schemas"


def _schema_columns() -> set[str]:
    columns: set[str] = set()
    for path in SCHEMA_DIR.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf8"))
        columns |= set(schema.get("required_columns", [])) | set(schema.get("dtypes", {}))
    return columns


def test_every_schema_column_has_a_label():
    missing = sorted(_schema_columns() - set(COLUMN_LABELS))
    assert not missing, f"Add these canonical columns to plotting/labels.py: {missing}"


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("temperature_C", "Temperature (°C)"),
        ("wavenumber_cm_inv", r"Wavenumber (cm$^{-1}$)"),
        ("viscosity_pa_s", r"Viscosity $\eta$ (Pa$\cdot$s)"),
        ("mz", r"$m/z$"),
        ("some_custom_column", "some_custom_column"),
    ],
)
def test_axis_label(column, expected):
    assert axis_label(column) == expected


def test_legend_name_has_no_unit():
    assert legend_name("storage_modulus_pa") == r"Storage modulus $G'$"
    assert legend_name("timestamp") == "timestamp"


def test_shared_axis_label_groups_same_kind_and_unit():
    assert shared_axis_label(["storage_modulus_mpa", "loss_modulus_mpa"]) == "Modulus (MPa)"
    assert shared_axis_label(["shear_stress_pa", "viscosity_pa_s"]) == (
        r"Shear stress $\tau$ (Pa), Viscosity $\eta$ (Pa$\cdot$s)"
    )
    assert shared_axis_label(["heat_flow_mW"]) == "Heat flow (mW)"


def test_every_label_renders_with_matplotlib_mathtext():
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.mathtext import MathTextParser

    parser = MathTextParser("path")
    for column in COLUMN_LABELS:
        label = axis_label(column)
        for idx, part in enumerate(label.split("$")):
            if idx % 2:
                parser.parse(f"${part}$")  # raises ValueError on invalid mathtext


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"Wavenumber (cm$^{-1}$)", "Wavenumber (cm<sup>-1</sup>)"),
        (r"Storage modulus $E'$", "Storage modulus E′"),
        (r"Loss modulus $E''$", "Loss modulus E″"),
        (r"Loss factor $\tan\delta$", "Loss factor tan δ"),
        (r"Shear rate $\dot{\gamma}$ (s$^{-1}$)", "Shear rate γ̇ (s<sup>-1</sup>)"),
        (r"Viscosity $\eta$ (Pa$\cdot$s)", "Viscosity η (Pa·s)"),
        (r"$\frac{\mathrm{d}m}{\mathrm{d}t}$ at T$_g$", "dm/dt at T<sub>g</sub>"),
        ("plain text", "plain text"),
        ("costs $5", "costs $5"),
    ],
)
def test_mathtext_to_html(text, expected):
    assert mathtext_to_html(text) == expected


def test_dma_spec_uses_shared_modulus_axis():
    dataset = Dataset(
        data=pd.DataFrame(
            {"frequency_hz": [0.1, 1.0], "storage_modulus_mpa": [10, 100], "loss_modulus_mpa": [5, 50]}
        ),
        metadata={"measurement_profile": "oscillatory_frequency_sweep"},
    )

    panel = build_dataset_spec(dataset).panel
    assert (panel.xlabel, panel.ylabel) == ("Frequency (Hz)", "Modulus (MPa)")
