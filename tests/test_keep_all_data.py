"""mfethuls keeps everything in a raw file: every data row (gaps too), every column, the text around the table.

One small file per parser, in the instrument's layout, and the example files.
"""

import glob
import re

import pandas as pd

import pytest

from mfethuls.examples import DATA_DIR as EXAMPLE_DATA
from mfethuls.parsers.registry import get_parser, reader_fingerprint


def _parse(key, *paths):
    parser = get_parser(*key)
    return parser.parse({"x": [str(p) for p in paths]}, experiment_id="e", instrument_type=key[0],
                        instrument_model=key[1])


def _write(path, lines, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding=encoding)
    return path


def _numeric_lines(path, encoding):
    """Lines of the file that start with a number (the data rows)."""
    count = 0
    with open(path, encoding=encoding) as handle:
        for line in handle:
            first = re.split(r"[\s,;]+", line.strip())[0] if line.strip() else ""
            try:
                float(first)
            except ValueError:
                continue
            count += 1
    return count


@pytest.mark.parametrize("key,pattern,encoding", [
    (("tga", "tgaX"), "TGA/*.txt", "cp1252"),
    (("dsc", "mettler_toledo_v1"), "DSC/*.txt", "cp1252"),
    (("ftir", "bruker"), "FTIR/*.csv", "utf-8"),
])
def test_example_files_arrive_complete(key, pattern, encoding):
    for path in sorted(glob.glob(str(EXAMPLE_DATA / pattern))):
        dataset = _parse(key, path)
        assert len(dataset.data) == _numeric_lines(path, encoding), path


def test_every_flame_spectrum_point_is_kept():
    paths = sorted(glob.glob(str(EXAMPLE_DATA / "Fluorescence" / "poly3" / "*.txt")))[:3]
    dataset = _parse(("fluorescence", "flame"), *paths)
    assert len(dataset.data) == 3 * 1044  # "Number of Pixels in Spectrum: 1044"
    assert dataset.data["wavelength_nm"].min() == 347.57  # the first point of each spectrum
    preamble = next(iter(dataset.metadata["file_text"].values()))["preamble"]
    assert "Integration Time (sec): 1.000000E-1" in preamble


def test_dsc_rows_with_gaps_and_the_footer_are_kept(tmp_path):
    path = _write(tmp_path / "run.txt", [
        "Method: 10 K/min",
        "         Index             t     Heat Flow            Ts            Tr",
        "           [#]           [s]          [mW]          [°C]          [°C]",
        "             0   0.00000e+00   1.0e-01   2.50e+01   2.50e+01",
        "             1   1.00000e+00                 2.51e+01   2.51e+01",
        "             2   2.00000e+00   1.2e-01   2.52e+01   2.52e+01",
        "LUB1, 12.12.2025 14:02:50",
    ], encoding="cp1252")
    dataset = _parse(("dsc", "mettler_toledo_v1"), path)
    assert len(dataset.data) == 3
    assert "temperature_sample_C" in dataset.data.columns  # Ts [°C], degree sign and all
    assert dataset.metadata["file_text"]["run.txt"] == {"preamble": ["Method: 10 K/min"],
                                                        "footer": ["LUB1, 12.12.2025 14:02:50"]}


def test_dsc_mettler_toledo_v1_units_stand_under_their_names_and_heat_flow_stays_per_gram(tmp_path):
    """Older Mettler Toledo STARe export (dsc_mettler_toledo_v0): no unit under Index, heat flow in W/g, sample text after the table."""
    path = _write(tmp_path / "lubxyz.txt", [
        "Title                                     09.02.2023 17:57",
        "Curve Values:",
        "          Index              t             Ts             Tr          Value",
        "                           [s]           [°C]           [°C]        [Wg^-1]",
        "              0              0        -80.002        -80.000      -0.043083",
        "              1              1        -80.002        -80.000     -0.0444151",
        "Results:",
        "  BKBMBTT, 5.3170 mg",
    ], encoding="cp1252")
    dataset = _parse(("dsc", "mettler_toledo_v0"), path)
    data = dataset.data
    assert data["time_s"].tolist() == [0.0, 1.0] and data["temperature_C"].tolist() == [-80.0, -80.0]
    assert data["temperature_sample_C"].tolist() == [-80.002, -80.002]
    assert data["heat_flow_W_g"].tolist() == [-0.043083, -0.0444151]
    # The sample mass in the text after the table gives heat flow in mW too.
    assert data["sample_mass_mg"].tolist() == [5.317, 5.317]
    assert data["heat_flow_mW"].tolist() == pytest.approx([-0.043083 * 5.317, -0.0444151 * 5.317])
    assert dataset.metadata["file_text"]["lubxyz.txt"]["values"] == {"sample_mass_mg": 5.317}
    assert "Index" in data.columns
    assert dataset.metadata["schema_normalization"]["missing_required_columns"] == []
    assert dataset.metadata["file_text"]["lubxyz.txt"]["footer"] == ["Results:", "  BKBMBTT, 5.3170 mg"]


def test_dma_keeps_the_header_text_and_every_row(tmp_path):
    path = _write(tmp_path / "dma.txt", [
        "Instrument\tDMA Q800", "Sig1\tTime (min)", "Sig2\tTemperature (°C)", "Sig3\tStorage Modulus (MPa)",
        "StartOfData", "0.0\t25.0\t1000", "0.5\t26.0\t", "1.0\t27.0\t990", "End of run",
    ])
    dataset = _parse(("dma", "ta_q800"), path)
    assert len(dataset.data) == 3
    text = dataset.metadata["file_text"]["dma.txt"]
    assert text["preamble"][0] == "Instrument\tDMA Q800" and text["footer"] == ["End of run"]


def test_saxs_keeps_rows_with_gaps(tmp_path):
    path = _write(tmp_path / "S1" / "curve.csv", ["q,I,dI", "0.1,1000,10", "0.2,900,", "0.3,800,8"])
    data = _parse(("saxs", "anton_paar"), path).data
    assert data["q_inv_nm"].tolist() == [0.1, 0.2, 0.3]
    assert data["intensity_error_a_u"].isna().tolist() == [False, True, False]


def test_sec_keeps_text_and_extra_columns(tmp_path):
    path = _write(tmp_path / "LUB9_RID1A.csv", ["Sample LUB9", "5.0,0.20,1", "5.1,0.25,1"])
    dataset = _parse(("sec", "agilent"), path)
    assert dataset.data["retention_time_min"].tolist() == [5.0, 5.1]
    assert "column_3" in dataset.data.columns
    assert set(dataset.data["detector_name"]) == {"ri"}
    assert dataset.metadata["file_text"]["LUB9_RID1A.csv"] == {"preamble": ["Sample LUB9"]}


def test_ms_leaves_out_repeated_rows_and_keeps_the_peak_table(tmp_path):
    path = _write(tmp_path / "m1.bsc", ["Spectrum", "100.0,5", "100.0,5", "100.0,6", "101.0,7", "102.0,1",
                                        "Peak", "101.0,7", "End", "Operator LB"])
    dataset = _parse(("ms", "bruker"), path)
    data = dataset.data
    # Only the row repeating an earlier row in every field goes; the same m/z with another intensity stays.
    assert data["mz"].tolist() == [100.0, 100.0, 101.0, 102.0]
    assert data["intensity_a_u"].tolist() == [5.0, 6.0, 7.0, 1.0]
    text = dataset.metadata["file_text"]["m1.bsc"]
    assert text["notes"] == ["1 row(s) repeating an earlier row in every field left out"]
    assert text["preamble"] == ["Spectrum"]
    assert text["footer"] == ["Peak", "101.0,7", "End", "Operator LB"]
    assert dataset.metadata["tables"] == {"peak_list": {"m1.bsc": [{"mz": 101.0, "intensity_a_u": 7.0}]}}


def test_rheometer_keeps_every_column_and_every_row(tmp_path):
    """RheoCompass layout: a tab-only line between names and units; a row with extra fields keeps them."""
    path = _write(tmp_path / "osc$1.csv", [
        "Project:\tP1", "", "Test:\tfreq", "", "Result:\tR1", "",
        "Interval and data points:\t1\t3",
        "Interval data:\tPoint No.\tAngular Frequency\tStorage Modulus\tLoss Modulus",
        "\t\t\t\t",
        "\t\t[rad/s]\t[Pa]\t[Pa]",
        "\t1\t1.0\t100\t10",
        "\t2\t2.0\t110\t11\t99\t98",
        "\t3\t3.0\t120\t12",
    ])
    dataset = _parse(("rheometer", "anton_paar"), path)
    data = dataset.data
    assert data["angular_frequency_rad_s"].tolist() == [1.0, 2.0, 3.0]
    assert data["storage_modulus_pa"].tolist() == [100.0, 110.0, 120.0]
    assert data["column_6"].tolist()[1] == 99.0 and data["interval"].tolist() == [1, 1, 1]
    assert {"Interval data:", "Point No."} <= set(data.columns)
    text = dataset.metadata["file_text"]["osc$1.csv"]
    assert text["preamble"] == ["Project:\tP1", "Test:\tfreq", "Result:\tR1"]
    assert text["blocks"] == ["Interval and data points:\t1\t3"]


def test_shimadzu_keeps_its_title_line(tmp_path):
    path = _write(tmp_path / "T1" / "T1_001.txt", ['"LUB7"', '"Wavelength nm."\t"Abs."', "200.0\t0.1", "201.0\t0.2"])
    dataset = _parse(("uv_vis", "Shimadzu"), path)
    assert dataset.data["wavelength_nm"].tolist() == [200.0, 201.0]
    assert dataset.metadata["file_text"]["T1_001.txt"] == {"preamble": ['"LUB7"']}


def test_every_code_parser_has_a_version():
    """A version lets Clean up offer to read data again after a parser is improved."""
    from mfethuls.parsers.registry import _PARSER_REGISTRY
    from mfethuls.parsers.tabular import TabularParser

    for key, parser in _PARSER_REGISTRY.items():
        if isinstance(parser, TabularParser):
            continue
        assert getattr(type(parser), "version", 1) >= 2, key
        assert reader_fingerprint(parser).endswith(f"-v{type(parser).version}")


def test_perkin_elmer_segment_lines_label_the_rows_below_them(tmp_path):
    path = _write(tmp_path / "pe.txt", [
        "Sample: PLA", "",
        "1) DSC 8500 Isothermal",
        "\tTime\tUnsubtracted\tProgram",
        "\t\tHeat Flow\tTemperature",
        "\t0.0\t-0.81\t30.0",
        "\t0.5\t-0.82\t30.0",
        "2) DSC 8500 Temperature Scan",
        "\t1.0\t-0.88\t30.1",
        "\t1.5\t-0.89\t30.2",
    ])
    dataset = _parse(("dsc", "perkin_elmer"), path)
    assert dataset.data["segment"].tolist() == ["1) DSC 8500 Isothermal"] * 2 + ["2) DSC 8500 Temperature Scan"] * 2
    assert dataset.metadata["file_text"]["pe.txt"]["preamble"] == ["Sample: PLA", "1) DSC 8500 Isothermal"]


def test_text_in_a_number_column_is_recorded_with_the_file(tmp_path):
    from mfethuls.instruments.definition import parse_definition
    from mfethuls.parsers.tabular import TabularParser

    path = tmp_path / "run1.txt"
    path.write_text("T\tm\n1\t5.0\n2\t--\n3\t4.8\n4\t4.7\n5\tn/a\n", encoding="utf8")
    definition = parse_definition({
        "name": "probe", "type": "tga", "model": "probe",
        "file": {"extensions": [".txt"], "delimiter": "tab"},
        "columns": [{"source": "T", "quantity": "temperature", "unit": "°C"},
                    {"source": "m", "quantity": "mass", "unit": "mg"}],
    })
    dataset = TabularParser(definition).parse({"run1": [str(path)]}, instrument_type="tga")
    assert dataset.data["mass_mg"].isna().sum() == 2
    note = "m: 2 value(s) that are not numbers stored as missing ('--', 'n/a'), from line 3"
    assert dataset.metadata["file_text"]["run1.txt"]["notes"] == [note]
    assert f"run1.txt: {note}" in dataset.metadata["schema_normalization"]["warnings"]


def test_tga_characterizer_never_replaces_mass_pct_from_the_file():
    from mfethuls.characterizers.tga import TGACharacterizer

    frame = pd.DataFrame({"mass_mg": [10.0, 9.0, 8.0], "mass_pct": [100.0, None, 79.5]})
    out = TGACharacterizer().characterize(frame)
    assert out["mass_pct"].tolist()[0] == 100.0 and out["mass_pct"].isna().tolist() == [False, True, False]
    assert out["mass_pct"].tolist()[2] == 79.5


def test_two_read_files_with_one_name_in_an_experiment_are_refused(tmp_path):
    from mfethuls.parsers.ingestion import ParseError
    from mfethuls.parsers.tabular import _refuse_same_names

    paths = [str(tmp_path / "LUB100" / "run1" / "data.txt"), str(tmp_path / "LUB100" / "run2" / "data.txt")]
    with pytest.raises(ParseError, match="same name"):
        _refuse_same_names({"exp": paths}, lambda path: True)
    _refuse_same_names({"exp": paths + [str(tmp_path / "notes.pdf")]}, lambda path: path.endswith("1/data.txt"))
