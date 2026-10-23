"""Guessing how to read an instrument's file, with no AI: shape of the file, known names, units."""

import pytest

from mfethuls.examples import DATA_DIR as EXAMPLE_DATA
from mfethuls.instruments.definition import parse_definition
from mfethuls.instruments.detect import detect, guess_column
from mfethuls.parsers.tabular import TabularParser


def _round_trip(path, detection, type_="test_type"):
    """The detected settings and guesses as a definition, reading ``path``."""
    data = detection.definition(name="x", type=type_, model="m")
    if not data["columns"]:
        data["columns"] = [{"source": detection.columns[0].source, "column": "first"}]
    return TabularParser(parse_definition(data)).parse({"x": [str(path)]}, instrument_type=type_).data


def _guesses(detection):
    return {g.source: (g.quantity, g.unit) for g in detection.columns}


def test_tga_example():
    path = EXAMPLE_DATA / "TGA" / "poly1.txt"
    detection = detect(path)
    assert detection.file == {"extensions": [".txt"], "encoding": "cp1252", "delimiter": "whitespace",
                              "decimal": ".", "header": {"rows": 2}, "data_ends": "first_non_numeric_row"}
    assert _guesses(detection) == {
        "Index [#]": (None, None),
        "Ts [°C]": ("sample_temperature", "°C"),
        "t [s]": ("time", "s"),
        "HF [mW]": ("heat_flow", "mW"),
        "Weight [mg]": ("mass", "mg"),
        "Tr [°C]": ("temperature", "°C"),
    }
    assert detection.type_guess == "tga"
    data = _round_trip(path, detection, "tga")
    assert len(data) == 2851 and data["mass_mg"].iloc[0] == pytest.approx(2.47986)


def test_dsc_example_with_a_column_name_containing_a_space():
    detection = detect(EXAMPLE_DATA / "DSC" / "poly1.txt")
    assert _guesses(detection)["Heat Flow [mW]"] == ("heat_flow", "mW")
    assert len(detection.columns) == 5


def test_ftir_example_starts_at_its_header_line():
    detection = detect(EXAMPLE_DATA / "FTIR" / "poly1.csv")
    assert detection.file["header"] == {"rows": 1, "starts_at": "cm-1"}
    assert _guesses(detection) == {"cm-1": ("wavenumber", None), "%T": ("transmittance", None)}
    assert detection.type_guess == "ftir"


def test_spectrum_without_column_names_starts_after_its_marker_line():
    path = next((EXAMPLE_DATA / "Fluorescence" / "poly3").glob("*.txt"))
    detection = detect(path)
    assert detection.file["header"] == {"rows": 0, "starts_at": ">>>>>Begin Spectral Data<<<<<", "skip_lines": 1}
    assert detection.file["delimiter"] == "tab"
    assert len(_round_trip(path, detection)) == 1044


def test_decimal_comma_semicolon_and_a_preamble_of_any_length(tmp_path):
    path = tmp_path / "run.csv"
    path.write_text(
        "Instrument;Photometer 3000\nOperator;LB\nDate;2026-10-15\n\n"
        "Zeit (min);Temperatur [°C];A600\n0,0;25,1;0,101\n0,5;25,3;0,152\n1,0;25,2;0,198\n",
        encoding="cp1252",
    )
    detection = detect(path)
    assert detection.file["encoding"] == "cp1252"
    assert (detection.file["delimiter"], detection.file["decimal"]) == ("semicolon", ",")
    assert detection.file["header"] == {"rows": 1, "starts_at": "Zeit (min)"}
    guesses = _guesses(detection)
    assert guesses["Zeit (min)"] == ("time", "min")  # from the unit alone
    assert guesses["Temperatur [°C]"] == ("temperature", "°C")
    data = _round_trip(path, detection)
    assert data["time_s"].tolist() == [0.0, 30.0, 60.0]
    assert data["A600"].tolist() == [0.101, 0.152, 0.198]  # not recognised: kept as it is


def test_utf8_bom_and_quoted_csv_header(tmp_path):
    path = tmp_path / "x.csv"
    path.write_bytes('﻿"Wavelength (nm)","Absorbance"\n400,0.1\n401,0.2\n'.encode("utf-8"))
    detection = detect(path)
    assert detection.file["encoding"] == "utf-8"
    guesses = _guesses(detection)
    assert guesses["Wavelength (nm)"] == ("wavelength", "nm")
    assert guesses["Absorbance"] == ("absorbance", None)


def test_no_table_is_a_clear_error(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("just some notes\nnothing numeric\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no table of numbers found"):
        detect(path)


@pytest.mark.parametrize("name,expected", [
    ("Weight [g]", ("mass", "g")),
    ("Temperature (K)", ("temperature", "K")),
    ("Value [Wg^-1]", ("specific_heat_flow", "Wg^-1")),  # per gram: not a heat flow in mW
    ("Index [#]", (None, None)),
    ("Viscosity [mPa·s]", ("viscosity", "mPa s")),
    ("Storage Modulus [MPa]", ("storage_modulus", "MPa")),
    ("q [1/nm]", ("q", "nm-1")),
])
def test_column_guesses(name, expected):
    guess = guess_column(name, set())
    assert (guess.quantity, guess.unit) == expected


def test_a_quantity_is_guessed_only_once():
    taken = set()
    first = guess_column("T1 [°C]", taken)
    taken.add(first.quantity)
    second = guess_column("T2 [°C]", taken)
    assert (first.quantity, second.quantity) == ("temperature", "sample_temperature")


def test_outline_shows_the_whole_file_part_by_part(tmp_path):
    from mfethuls.instruments.detect import file_outline

    lines = ["Instrument X", "Time;A", *[f"{i};{i * 2}" for i in range(50)], "", "Results",
             "Peak;Area;Height", *[f"{i};{i};{i}" for i in range(5)], "End of file"]
    path = tmp_path / "x.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert file_outline(path) == [
        "The file has 61 lines:",
        "lines 1–2: text (2 lines)",
        "lines 3–52: numbers in 2 columns (50 rows)",
        "lines 54–55: text (2 lines)",
        "lines 56–60: numbers in 3 columns (5 rows)",
        "line 61: text, starting 'End of file'",
    ]
    assert "lines 56–60: numbers in 3 columns (5 rows)" in detect(path).summary()


def test_long_outlines_are_shortened(tmp_path):
    from mfethuls.instruments.detect import outline

    lines = [("1;2" if i % 2 else "text") for i in range(100)]
    parts = outline(lines, "semicolon", ".", max_parts=6)
    assert parts[0] == "The file has 100 lines:" and len(parts) == 7
    assert parts[4] == "… 95 more parts …"


def test_column_names_listed_before_the_table(tmp_path):
    """TA Q800 style: 'SigN<tab>name' lines name the columns of a table without a header line."""
    path = tmp_path / "dma.txt"
    path.write_text(
        "Instrument\tDMA Q800\nNsig\t3\nSig1\tTime (min)\nSig2\tTemperature (°C)\nSig3\tStorage Modulus (MPa)\n"
        "Time\t12:12:15\nStartOfData\n\n1.5\t27.4\t14.6\n2.0\t27.5\t14.7\n", encoding="utf-8")
    detection = detect(path)
    assert detection.file["header"]["names_from"] == r"^Sig\d+\t(.+)$"
    assert [(g.quantity, g.unit) for g in detection.columns][:2] == [("time", "min"), ("temperature", "°C")]


def test_a_file_of_several_tables_is_pointed_out(tmp_path):
    path = tmp_path / "LUB650.txt"
    block = "Interval and data points:\t{n}\t3\nPoint No.\tTime\tG'\n\t[s]\t[Pa]\n1\t0\t10\n2\t1\t11\n3\t2\t12\n"
    path.write_text("Project: x\n\n" + "".join(block.format(n=n) for n in (1, 2, 3)), encoding="utf-8")
    detection = detect(path)
    assert any("appears 3 times" in note and "Several tables" in note for note in detection.notes)
