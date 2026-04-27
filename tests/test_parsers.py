import pytest
import pandas as pd

from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import get_parser
from mfethuls.parsers.sec import AgilentSec


ALL_PARSER_KEYS = [
    ("dsc", "prior"),
    ("dsc", "perkin_elmer"),
    ("dsc", "mettler_toledo"),
    ("tga", "tgaX"),
    ("ftir", "bruker"),
    ("nmr", "bruker_nmr"),
    ("ms", "bruker"),
    ("saxs", "anton_paar"),
    ("sec", "agilent"),
    ("rheometer", "anton_paar"),
    ("dma", "ta_q800"),
    ("uv_vis", "flame"),
    ("reflection", "flame"),
    ("uv_vis", "Shimadzu"),
]


@pytest.mark.parametrize("instrument_type,instrument_model", ALL_PARSER_KEYS)
def test_registered_parsers_return_dataset_with_context(instrument_type, instrument_model):
    parser = get_parser(instrument_type, instrument_model)

    dataset = parser.parse(
        {},
        experiment_id="EXP001",
        sample_id="S001",
        run_id="R001",
        instrument_type=instrument_type,
        instrument_model=instrument_model,
        instrument_name=f"{instrument_type}_{instrument_model}",
        experiment_name="parser_smoke_test",
        metadata={"test": "parser_registry_smoke"},
    )

    assert isinstance(dataset, Dataset)
    assert dataset.experiment_id == "EXP001"
    assert dataset.sample_id == "S001"
    assert dataset.metadata.get("instrument_type") == instrument_type
    assert dataset.metadata.get("instrument_model") == instrument_model


@pytest.mark.parametrize("instrument_type,instrument_model", ALL_PARSER_KEYS)
def test_registered_parsers_are_resolvable(instrument_type, instrument_model):
    parser = get_parser(instrument_type, instrument_model)
    assert parser is not None
    assert hasattr(parser, "parse")
    assert callable(parser.parse)


PARSER_BEHAVIOR_CASES = [
    {
        "key": ("dsc", "prior"),
        "raw": {"Tr [°C]": [25.0, 26.0], "Value [mW]": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("dsc", "perkin_elmer"),
        "raw": {"Program Temperature": [25.0, 26.0], "Unsubtracted Heat Flow": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("dsc", "mettler_toledo"),
        "raw": {"Tr [°C]": [25.0, 26.0], "Value [mW]": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("tga", "tgaX"),
        "raw": {"Temperature [°C]": [25.0, 30.0], "Mass [%]": [100.0, 99.5]},
        "expect": {"temperature_C", "mass_pct"},
    },
    {
        "key": ("ftir", "bruker"),
        "raw": {"Wavenumber [cm-1]": [4000.0, 3999.0], "Transmittance [%]": [95.0, 94.5]},
        "expect": {"wavenumber_cm_inv", "transmittance_pct"},
    },
    {
        "key": ("nmr", "bruker_nmr"),
        "raw": {"ppm": [1.0, 0.9], "intensity": [100.0, 110.0]},
        "expect": {"chemical_shift_ppm", "intensity_a_u"},
    },
    {
        "key": ("ms", "bruker"),
        "raw": {"m/z": [100.0, 101.0], "intensity": [5000.0, 5200.0]},
        "expect": {"mz", "intensity_a_u"},
    },
    {
        "key": ("saxs", "anton_paar"),
        "raw": {"q": [0.10, 0.20], "I": [1000.0, 900.0]},
        "expect": {"q_inv_nm", "intensity_a_u"},
    },
    {
        "key": ("sec", "agilent"),
        "raw": {"time (min)": [5.0, 5.1], "value": [0.20, 0.25], "detector_name": ["ri", "ri"]},
        "expect": {"retention_time_min", "detector_response_a_u", "detector_name"},
    },
    {
        "key": ("rheometer", "anton_paar"),
        "raw": {"w [rad/s]": [1.0, 2.0], "G' [Pa]": [1000.0, 1100.0], "G'' [Pa]": [200.0, 220.0]},
        "expect": {"angular_frequency_rad_s", "storage_modulus_pa", "loss_modulus_pa"},
        "parse_kwargs": {"measurement_profile": "oscillatory_frequency_sweep"},
    },
    {
        "key": ("dma", "ta_q800"),
        "raw": {"Frequency [Hz]": [1.0, 10.0], "Storage Modulus [MPa]": [1.0, 1.1], "Loss Modulus [MPa]": [0.2, 0.22]},
        "expect": {"frequency_hz", "storage_modulus_mpa", "loss_modulus_mpa"},
        "parse_kwargs": {"measurement_profile": "oscillatory_frequency_sweep"},
    },
    {
        "key": ("uv_vis", "flame"),
        "raw": {"wavelength (nm)": [400.0, 450.0], "transmission": [0.8, 0.75]},
        "expect": {"wavelength_nm", "transmittance_pct"},
    },
    {
        "key": ("reflection", "flame"),
        "raw": {"wavelength (nm)": [400.0, 450.0], "transmission": [0.8, 0.75]},
        "expect": {"wavelength_nm", "transmittance_pct"},
    },
    {
        "key": ("uv_vis", "Shimadzu"),
        "raw": {"Wavelength (nm)": [400.0, 450.0], "Absorbance": [0.1, 0.12]},
        "expect": {"wavelength_nm", "absorbance_a_u"},
    },
]


@pytest.mark.parametrize("case", PARSER_BEHAVIOR_CASES)
def test_each_parser_normalizes_expected_columns(case, monkeypatch):
    instrument_type, instrument_model = case["key"]
    parser = get_parser(instrument_type, instrument_model)

    raw_df = pd.DataFrame(case["raw"])
    monkeypatch.setattr(parser, "parse_raw_data", lambda _path, _df=raw_df: _df.copy())

    parse_kwargs = case.get("parse_kwargs", {})
    dataset = parser.parse(
        {"dummy": [f"dummy{getattr(parser, 'file_extension', '.txt')}"]},
        experiment_id="EXP001",
        sample_id="S001",
        run_id="R001",
        instrument_type=instrument_type,
        instrument_model=instrument_model,
        instrument_name=f"{instrument_type}_{instrument_model}",
        experiment_name="parser_behavior_test",
        metadata={"test": "parser_behavior"},
        **parse_kwargs,
    )

    assert isinstance(dataset, Dataset)
    assert case["expect"].issubset(set(dataset.data.columns))
    assert dataset.experiment_id == "EXP001"
    assert dataset.sample_id == "S001"


def test_sec_infer_detector_name_from_filename_tokens():
    parser = AgilentSec()

    assert parser._infer_detector_name("sample_ri_trace.csv") == "ri"
    assert parser._infer_detector_name("sample_uv254_signal.csv") == "uv"
    assert parser._infer_detector_name("sample_mals_channel.csv") == "ls"
    assert parser._infer_detector_name("sample_visc_dp.csv") == "viscometer"
    assert parser._infer_detector_name("sample_unknown_detector.csv") == "unknown"


def test_dma_parser_explicit_measurement_profile_trumps_metadata(monkeypatch):
    parser = get_parser("dma", "ta_q800")
    raw_df = pd.DataFrame(
        {
            "Frequency [Hz]": [1.0, 10.0],
            "Storage Modulus [MPa]": [1.2, 1.3],
            "Loss Modulus [MPa]": [0.2, 0.25],
        }
    )
    monkeypatch.setattr(parser, "parse_raw_data", lambda _path, _df=raw_df: _df.copy())

    dataset = parser.parse(
        {"dummy": ["dummy.txt"]},
        experiment_id="EXP123",
        sample_id="S001",
        run_id="R001",
        instrument_type="dma",
        instrument_model="ta_q800",
        instrument_name="dma",
        experiment_name="dma_profile_priority",
        measurement_profile="oscillatory_frequency_sweep",
        metadata={"measurement_profile": "oscillatory_temperature_sweep"},
    )

    assert dataset.metadata.get("measurement_profile") == "oscillatory_frequency_sweep"
