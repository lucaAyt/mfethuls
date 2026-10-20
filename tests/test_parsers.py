import os
import shutil

import pytest
import pandas as pd

from mfethuls.examples import DATA_DIR as EXAMPLE_DATA
from mfethuls.dataset import Dataset
from mfethuls.parsers.registry import get_parser


ALL_PARSER_KEYS = [
    ("dsc", "mettler_toledo_v0"),
    ("dsc", "perkin_elmer"),
    ("dsc", "mettler_toledo_v1"),
    ("tga", "tgaX"),
    ("ftir", "bruker"),
    ("nmr", "bruker_nmr"),
    ("ms", "bruker"),
    ("saxs", "anton_paar"),
    ("sec", "agilent"),
    ("rheometer", "anton_paar"),
    ("dma", "ta_q800"),
    ("uv_vis", "flame"),
    ("fluorescence", "flame"),
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
        "key": ("dsc", "mettler_toledo_v0"),
        "raw": {"Tr [°C]": [25.0, 26.0], "Value [mW]": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("dsc", "perkin_elmer"),
        "raw": {"Program Temperature": [25.0, 26.0], "Unsubtracted Heat Flow": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("dsc", "mettler_toledo_v1"),
        "raw": {"Tr [°C]": [25.0, 26.0], "Value [mW]": [0.10, 0.11]},
        "expect": {"temperature_C", "heat_flow_mW"},
    },
    {
        "key": ("tga", "tgaX"),
        "raw": {"Tr [°C]": [25.0, 30.0], "Weight [mg]": [10.0, 9.95]},  # the text export (dummy.txt)
        "expect": {"temperature_C", "mass_mg", "mass_pct"},
    },
    {
        "key": ("ftir", "bruker"),
        "raw": {"Wavenumber [cm-1]": [4000.0, 3999.0], "Transmittance [%]": [95.0, 94.5]},
        "expect": {"wavenumber_cm_inv", "transmittance_pct"},
    },
    {
        "key": ("nmr", "bruker_nmr"),
        "raw": {"chemical_shift_ppm": [1.0, 0.9], "intensity_a_u": [100.0, 110.0]},  # what parse_raw_data gives
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
        "raw": {"column_1": [5.0, 5.1], "column_2": [0.20, 0.25]},  # SEC exports have no header
        "expect": {"retention_time_min", "detector_response_a_u"},
    },
    {
        "key": ("rheometer", "anton_paar"),
        "raw": {"w [rad/s]": [1.0, 2.0], "G' [Pa]": [1000.0, 1100.0], "G'' [Pa]": [200.0, 220.0]},
        "expect": {"angular_frequency_rad_s", "storage_modulus_pa", "loss_modulus_pa"},
    },
    {
        "key": ("dma", "ta_q800"),
        "raw": {"Frequency [Hz]": [1.0, 10.0], "Storage Modulus [MPa]": [1.0, 1.1], "Loss Modulus [MPa]": [0.2, 0.22]},
        "expect": {"frequency_hz", "storage_modulus_mpa", "loss_modulus_mpa"},
    },
    {
        "key": ("uv_vis", "flame"),
        "raw": {"column_1": [400.0, 450.0], "column_2": [0.8, 0.75]},  # Flame spectra have no header
        "expect": {"wavelength_nm", "transmittance_pct"},
    },
    {
        "key": ("fluorescence", "flame"),
        "raw": {"column_1": [400.0, 450.0], "column_2": [11.9, -4.1]},
        "expect": {"wavelength_nm", "emission_counts"},
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
    monkeypatch.setattr(parser, "parse_raw_data", lambda _path, _df=raw_df, **_: _df.copy())

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


@pytest.mark.parametrize(
    "key,example,renamed",
    [
        (("dsc", "mettler_toledo_v1"), "DSC/poly1.txt", "test.txt"),
        (("tga", "tgaX"), "TGA/poly1.txt", "test.txt"),
        (("ftir", "bruker"), "FTIR/poly1.csv", "spec.csv"),
    ],
)
def test_parser_name_keeps_full_file_stem(tmp_path, key, example, renamed):
    """The name column is the file stem, not the name with extension characters stripped.

    ``"test.txt".rstrip(".txt")`` gives ``"tes"`` and ``"spec.csv".rstrip(".csv")``
    gives ``"spe"``, which these file names would expose.
    """
    path = tmp_path / renamed
    shutil.copy(EXAMPLE_DATA / example, path)

    df = get_parser(*key).parse_raw_data(str(path))

    assert set(df["name"]) == {path.stem}



def test_nmr_reads_each_processed_spectrum_once(tmp_path, monkeypatch):
    """Every <expno>/pdata/<procno> holding a 1r is read once, named by its place in the dataset."""
    files = []
    for relative in ["EXP/1/acqus", "EXP/1/fid", "EXP/1/pdata/1/1r", "EXP/1/pdata/1/procs",
                     "EXP/2/acqus", "EXP/2/pdata/1/1r", "EXP/2/pdata/1/title"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("13C spectrum\n" if relative.endswith("title") else "x", encoding="utf-8")
        files.append(str(path))
    parser = get_parser("nmr", "bruker_nmr")
    read = []

    def parse_raw_data(folder, **_):
        read.append(os.path.relpath(folder, tmp_path).replace(os.sep, "/"))
        return pd.DataFrame({"chemical_shift_ppm": [2.0, 1.0], "intensity_a_u": [5.0, 6.0]})

    monkeypatch.setattr(parser, "parse_raw_data", parse_raw_data)
    data = parser.parse({"EXP": files}, experiment_id="e", instrument_type="nmr").data
    assert read == ["EXP/1/pdata/1", "EXP/2/pdata/1"]
    assert data["source_file"].tolist() == ["1/pdata/1"] * 2 + ["2/pdata/1"] * 2


def test_nmr_keeps_the_spectrum_title(tmp_path):
    from mfethuls.parsers.nmr import _spectrum_label, _title_lines

    (tmp_path / "title").write_text("PROTON DMSO\n\nLUB 9\n", encoding="utf-8")
    assert _title_lines(str(tmp_path)) == ["PROTON DMSO", "LUB 9"]
    assert _spectrum_label(os.path.join("data", "EXP014", "1", "pdata", "1")) == "1/pdata/1"


def test_nmr_nucleus_and_solvent_come_from_the_parameters():
    from mfethuls.parsers.nmr import _parameter

    dic = {"acqus": {"NUC1": "<13C>", "SOLVENT": "CDCl3"}, "procs": {"AXNUC": "1H"}}
    assert _parameter(dic, ("acqus", "NUC1"), ("procs", "AXNUC")) == "13C"
    assert _parameter({"acqus": {"NUC1": "off"}, "procs": {"AXNUC": "19F"}},
                      ("acqus", "NUC1"), ("procs", "AXNUC")) == "19F"
    assert _parameter(dic, ("acqus", "SOLVENT")) == "CDCl3"
    assert _parameter({}, ("acqus", "SOLVENT")) is None


def test_nmr_says_why_a_processed_spectrum_cannot_be_read(tmp_path):
    from mfethuls.parsers.ingestion import ParseError
    from mfethuls.parsers.nmr import BrukerNMRParser

    spectrum = tmp_path / "EXP099" / "1" / "pdata" / "1"
    spectrum.mkdir(parents=True)
    (spectrum / "1r").write_bytes(b"not a spectrum")
    with pytest.raises(ParseError, match=r"1/pdata/1: no processed spectrum \("):
        BrukerNMRParser().parse({"EXP099": [str(spectrum / "1r")]}, instrument_type="nmr")
