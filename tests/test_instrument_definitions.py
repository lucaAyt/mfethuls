"""Instrument definitions: validation, units, the tabular reader and the built-in definitions."""

import json

import pandas as pd
import pytest

from mfethuls.examples import DATA_DIR as EXAMPLE_DATA
from mfethuls.instruments.configured import readers
from mfethuls.instruments.definition import DefinitionError, builtin_definitions, parse_definition
from mfethuls.instruments.units import QUANTITIES, conversion, normalize_unit
from mfethuls.parsers.ingestion import ParseError
from mfethuls.parsers.registry import get_parser
from mfethuls.parsers.tabular import TabularParser, read_table
from mfethuls.instruments.definition import BUILTIN_DIR as BUILTIN


def _definition(**overrides):
    data = {
        "name": "test_tga",
        "type": "tga",
        "model": "test",
        "file": {"extensions": [".txt"], "delimiter": "whitespace"},
        "columns": [
            {"source": "T [°C]", "quantity": "temperature", "unit": "°C"},
            {"source": "m [g]", "quantity": "mass", "unit": "g"},
        ],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return parse_definition(data)


def _parse(definition, path):
    return TabularParser(definition).parse({"x": [str(path)]}, experiment_id="e1", instrument_type=definition.type)


# --- units -----------------------------------------------------------------

@pytest.mark.parametrize("quantity,unit,value,expected", [
    ("mass", "g", 2.5, 2500.0),
    ("mass", "µg", 1000.0, 1.0),
    ("mass", "mg", 3.0, 3.0),
    ("temperature", "K", 273.15, 0.0),
    ("temperature", "°F", 212.0, 100.0),
    ("time", "min", 2.0, 120.0),
    ("retention_time", "s", 90.0, 1.5),
    ("wavelength", "µm", 0.5, 500.0),
    ("q", "1/Å", 0.1, 1.0),
    ("viscosity", "mPa·s", 1000.0, 1.0),
])
def test_unit_conversion_into_the_stored_unit(quantity, unit, value, expected):
    factor, offset = conversion(QUANTITIES[quantity], unit)
    assert value * factor + offset == pytest.approx(expected)


def test_modulus_is_stored_in_mpa_for_dma_and_pa_otherwise():
    modulus = QUANTITIES["storage_modulus"]
    assert modulus.target("dma") == ("storage_modulus_mpa", "MPa")
    assert modulus.target("rheometer") == ("storage_modulus_pa", "Pa")
    assert conversion(modulus, "Pa", "dma") == pytest.approx((1e-6, 0.0))
    assert conversion(modulus, "MPa", "rheometer") == pytest.approx((1e6, 0.0))


def test_unit_spellings_are_tolerated_but_case_matters():
    assert normalize_unit("cm^-1") == normalize_unit("1/cm") == normalize_unit("cm-1")
    assert normalize_unit("°C") == normalize_unit("degC") == normalize_unit("C")
    assert normalize_unit("MPa") != normalize_unit("mPa")
    with pytest.raises(ValueError, match="Unknown unit 'lb'"):
        conversion(QUANTITIES["mass"], "lb")


def test_stored_columns_match_the_type_schemas():
    """Every column a schema declares that is a physical quantity has a matching quantity."""
    from mfethuls.schema_normalization import _load_instrument_schema

    stored = {q.target(t)[0] for q in QUANTITIES.values() for t in ("dma", "other")}
    not_quantities = {"detector_name", "nucleus", "solvent"}
    for type_ in ("dma", "dsc", "fluorescence", "ftir", "ms", "nmr", "rheometer", "saxs", "sec", "tga", "uv_vis"):
        declared = set(_load_instrument_schema(type_).get("dtypes", {})) - not_quantities
        assert declared <= stored, (type_, sorted(declared - stored))


# --- validation ------------------------------------------------------------

def test_every_problem_is_reported_at_once():
    with pytest.raises(DefinitionError) as info:
        parse_definition({
            "name": "Bad Name",
            "type": "tga",
            "model": "x",
            "file": {"extensions": [".txt"], "delimiter": "pipe", "header": {"rows": 3}},
            "columns": [
                {"source": "m", "quantity": "mass", "unit": "lb"},
                {"source": "q", "quantity": "nonsense"},
                {"source": "x", "quantity": "mass", "column": "x"},
            ],
            "derived": [{"op": "integrate", "column": "mass_mg", "into": "x"}],
        })
    text = str(info.value)
    for fragment in ("'name'", "'file.delimiter'", "'file.header.rows'",
                     "Unknown unit 'lb'", "unknown quantity 'nonsense'", "not both", "'op' must be"):
        assert fragment in text
    assert len(info.value.problems) == 7


def test_two_columns_cannot_be_stored_under_one_name():
    with pytest.raises(DefinitionError, match="both stored as 'mass_mg'"):
        _definition(columns=[
            {"source": "a", "quantity": "mass", "unit": "mg"},
            {"source": "b", "quantity": "mass", "unit": "g"},
        ])


def test_decimal_comma_needs_another_delimiter():
    with pytest.raises(DefinitionError, match="other than comma"):
        _definition(file={"delimiter": "comma", "decimal": ","})


def test_fingerprint_changes_when_the_definition_changes():
    assert _definition().fingerprint == _definition().fingerprint
    assert _definition().fingerprint != _definition(file={"encoding": "cp1252"}).fingerprint
    # Renaming the reader does not change how files are read.
    assert _definition().fingerprint == _definition(name="tga_b", data_layout="folder").fingerprint


# --- reading files ---------------------------------------------------------

def test_preamble_two_line_header_and_footer(tmp_path):
    path = tmp_path / "run1.txt"
    path.write_text(
        "Instrument XY\nOperator: me\n"
        "   Index     T       m\n"
        "     [#]  [°C]     [g]\n"
        "       0  25.0   0.0100\n"
        "       1  26.0   0.0095\n"
        "Results: done\n",
        encoding="cp1252",
    )
    definition = _definition(file={"encoding": "cp1252", "header": {"starts_at": "Index", "rows": 2},
                                   "data_ends": "first_non_numeric_row"})
    dataset = _parse(definition, path)
    data = dataset.data

    assert data["temperature_C"].tolist() == [25.0, 26.0]
    assert data["mass_mg"].tolist() == pytest.approx([10.0, 9.5])  # converted from g
    assert "Index [#]" in data.columns  # columns without a mapping are kept
    assert dataset.metadata["file_text"]["run1.txt"] == {
        "preamble": ["Instrument XY", "Operator: me"], "footer": ["Results: done"]}
    assert set(data["name"]) == {"run1"}
    assert set(data["experiment_id"]) == {"e1"}


def test_decimal_comma_semicolon_and_end_marker(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("Temp;Mass\n25,5;1,25\n26,5;1,20\n[END]\nignored;row\n", encoding="utf-8")
    definition = _definition(
        file={"extensions": [".csv"], "delimiter": "semicolon", "decimal": ",", "data_ends": "[END]"},
        columns=[{"source": "Temp", "quantity": "temperature", "unit": "°C"},
                 {"source": "Mass", "quantity": "mass", "unit": "mg"}],
    )
    data = _parse(definition, path).data
    assert data["temperature_C"].tolist() == [25.5, 26.5]
    assert data["mass_mg"].tolist() == [1.25, 1.20]


def test_no_header_uses_numbered_columns(tmp_path):
    path = tmp_path / "chrom.csv"
    path.write_text("5.0,0.2\n5.1,0.25\n", encoding="utf-8")
    definition = _definition(
        type="sec",
        file={"extensions": [".csv"], "delimiter": "comma", "header": {"rows": 0}},
        columns=[{"source": "column_1", "quantity": "retention_time", "unit": "min"},
                 {"source": "column_2", "quantity": "detector_response", "unit": "a.u."}],
    )
    data = _parse(definition, path).data
    assert data["retention_time_min"].tolist() == [5.0, 5.1]


def test_text_columns_stay_text(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("T,m,comment\n1,2,ok\n3,4,\n", encoding="utf-8")
    table = read_table(path, _definition(file={"delimiter": "comma"}).formats[0].file)
    assert table["T"].dtype == "float64"
    assert table["comment"].tolist() == ["ok", None]  # an empty cell is missing


def test_missing_header_text_names_the_file(tmp_path):
    path = tmp_path / "wrong.txt"
    path.write_text("a b\n1 2\n", encoding="utf-8")
    definition = _definition(file={"header": {"starts_at": "Index"}})
    with pytest.raises(ParseError, match="wrong.txt: no line contains the header text 'Index'"):
        _parse(definition, path)


def test_mapped_column_without_numbers_is_an_error(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("T m\nwarm heavy\n", encoding="utf-8")
    definition = _definition(columns=[{"source": "T", "quantity": "temperature", "unit": "°C"}])
    with pytest.raises(ParseError, match="holds no numbers"):
        _parse(definition, path)


def test_nothing_in_the_file_is_dropped(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text(
        "Sample LUB1\nT m extra\n1 2 3 4\n# paused\n5 6 7\nEND\nLUB1, 11.02.2026\n", encoding="utf-8")
    definition = _definition(
        file={"comment": "#", "data_ends": "first_non_numeric_row", "header": {"skip_lines": 1}},
        columns=[{"source": "T", "quantity": "temperature", "unit": "°C"}],
    )
    dataset = _parse(definition, path)
    data = dataset.data
    assert data["temperature_C"].tolist() == [1.0, 5.0]
    assert data["m"].tolist() == [2.0, 6.0]
    assert data["extra"].tolist() == [3.0, 7.0]
    assert data["column_4"].iloc[0] == 4.0 and pd.isna(data["column_4"].iloc[1])  # extra field kept
    assert dataset.metadata["file_text"] == {"t.txt": {
        "preamble": ["Sample LUB1"], "footer": ["END", "LUB1, 11.02.2026"], "comments": ["# paused"]}}


def test_rows_before_the_first_number_are_data_not_the_end(tmp_path):
    """A rheometer marks its first points '1  (invalid)': the data starts there, it does not end."""
    path = tmp_path / "r.txt"
    path.write_text("Point\tT [°C]\tStart\n1 (invalid)\t\t12/09/2026\n2\t21.5\t12/09/2026\n3\t21.6\t12/09/2026\nEnd\n",
                    encoding="utf-8")
    definition = _definition(
        file={"delimiter": "tab", "header": {"starts_at": "Point"}, "data_ends": "first_non_numeric_row"},
        columns=[{"source": "T [°C]", "quantity": "temperature", "unit": "°C"}],
    )
    dataset = _parse(definition, path)
    data = dataset.data
    assert data["Point"].tolist() == ["1 (invalid)", "2", "3"]
    assert data["temperature_C"].iloc[1:].tolist() == [21.5, 21.6] and pd.isna(data["temperature_C"].iloc[0])
    assert data["Start"].tolist() == ["12/09/2026"] * 3
    assert dataset.metadata["file_text"]["r.txt"]["footer"] == ["End"]


def test_file_column_with_a_stored_name_is_kept_beside_it(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("T temperature_C\n1 99\n", encoding="utf-8")
    definition = _definition(columns=[{"source": "T", "quantity": "temperature", "unit": "°C"}])
    data = _parse(definition, path).data
    assert data["temperature_C"].tolist() == [1.0]
    assert data["temperature_C (file)"].tolist() == [99.0]


def test_derived_never_overwrites(tmp_path):
    with pytest.raises(DefinitionError, match="'into' must"):
        _definition(derived=[{"op": "scale", "column": "mass_mg", "factor": 2}])
    with pytest.raises(DefinitionError, match="'into' must differ"):
        _definition(derived=[{"op": "scale", "column": "mass_mg", "factor": 2, "into": "mass_mg"}])

    path = tmp_path / "t.txt"
    path.write_text("T m pct\n1 10 7\n2 0 8\n", encoding="utf-8")
    definition = _definition(
        columns=[{"source": "T", "quantity": "temperature", "unit": "°C"},
                 {"source": "m", "quantity": "mass", "unit": "mg"},
                 {"source": "pct", "quantity": "mass_pct", "unit": "%"}],
        derived=[{"op": "normalize_pct", "column": "mass_mg", "into": "mass_pct"}],
    )
    dataset = _parse(definition, path)
    assert dataset.data["mass_pct"].tolist() == [7.0, 8.0]
    assert any("already comes from the file" in w for w in dataset.metadata["schema_normalization"]["warnings"])


def test_several_formats_are_chosen_by_extension_and_contained_text(tmp_path):
    definition = parse_definition({
        "name": "multi", "type": "tga", "model": "m",
        "formats": [
            {"label": "v1", "file": {"extensions": [".txt"], "delimiter": "whitespace", "contains": "Version 1",
                                     "header": {"skip_lines": 1}},
             "columns": [{"source": "Temp", "quantity": "temperature", "unit": "°C"}]},
            {"label": "v2", "file": {"extensions": [".txt"], "delimiter": "tab", "contains": "Version 2",
                                     "header": {"skip_lines": 1}},
             "columns": [{"source": "T (K)", "quantity": "temperature", "unit": "K"}]},
            {"label": "csv", "file": {"extensions": [".csv"]},
             "columns": [{"source": "temperature", "quantity": "temperature", "unit": "°C"}]},
        ],
    })
    (tmp_path / "a.txt").write_text("Version 1\nTemp\n25\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Version 2\nT (K)\n300.15\n", encoding="utf-8")
    (tmp_path / "c.csv").write_text("temperature\n30\n", encoding="utf-8")
    (tmp_path / "d.txt").write_text("Version 3\nTemp\n1\n", encoding="utf-8")

    parser = TabularParser(definition)
    assert parser.file_extension == ".txt" and parser.extra_extensions == (".csv",)
    paths = [str(tmp_path / n) for n in ("a.txt", "b.txt", "c.csv")]
    dataset = parser.parse({"x": paths}, experiment_id="e", instrument_type="tga")
    assert dataset.data["temperature_C"].tolist() == pytest.approx([25.0, 27.0, 30.0])
    assert {k: v["format"] for k, v in dataset.metadata["file_text"].items()} == {
        "a.txt": "v1", "b.txt": "v2", "c.csv": "csv"}

    with pytest.raises(ParseError, match="d.txt: the file matches none of the multi formats"):
        parser.parse({"x": [str(tmp_path / "d.txt")]}, experiment_id="e", instrument_type="tga")


def test_formats_and_top_level_file_are_exclusive_and_keys_are_checked():
    with pytest.raises(DefinitionError) as info:
        parse_definition({"name": "x", "type": "tga", "model": "m",
                          "file": {"extensions": [".txt"], "delimeter": ";"},
                          "columns": [{"source": "a", "quantity": "mass"}],
                          "formats": [{"file": {"extensions": [".csv"]}, "columns": [{"source": "a", "column": "a"}]}],
                          "keep_other_columns": False})
    text = str(info.value)
    assert "not both" in text
    assert "unknown key 'keep_other_columns'" in text
    with pytest.raises(DefinitionError, match="file: unknown key 'delimeter'"):
        _definition(file={"delimeter": ";"})


def test_derived_operations(tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("T m\n1 10\n2 5\n3 0\n", encoding="utf-8")
    definition = _definition(
        columns=[{"source": "T", "quantity": "temperature", "unit": "°C"},
                 {"source": "m", "quantity": "mass", "unit": "mg"}],
        derived=[{"op": "normalize_pct", "column": "mass_mg", "into": "mass_pct"},
                 {"op": "offset", "column": "temperature_C", "value": 273.15, "into": "T_kelvin"},
                 {"op": "scale", "column": "mass_mg", "factor": 2, "into": "mass_2x"}],
    )
    data = _parse(definition, path).data
    assert data["mass_pct"].tolist() == [100.0, 50.0, 0.0]
    assert data["T_kelvin"].tolist() == pytest.approx([274.15, 275.15, 276.15])
    assert data["mass_2x"].tolist() == [20.0, 10.0, 0.0]
    assert data["mass_mg"].tolist() == [10.0, 5.0, 0.0]


# --- built-in definitions --------------------------------------------------

def test_builtin_definitions_are_valid_and_listed():
    names = {reader.name for reader in readers()}
    for definition in builtin_definitions():
        assert definition.name in names
        assert isinstance(get_parser(definition.type, definition.model), TabularParser)


def test_builtin_definition_files_are_plain_json():
    from mfethuls.instruments.definition import BUILTIN_DIR

    for path in BUILTIN_DIR.glob("*.json"):
        assert json.loads(path.read_text(encoding="utf8"))["spec_version"] == 1


def test_ftir_example_reads_as_before_the_migration():
    """Values the former code parser (parsers/ftir.py) produced for the example file."""
    parser = get_parser("ftir", "bruker")
    dataset = parser.parse({"x": [str(EXAMPLE_DATA / "FTIR" / "poly1.csv")]}, experiment_id="e",
                           instrument_type="ftir", instrument_model="bruker")
    data = dataset.data
    assert list(data.columns) == ["wavenumber_cm_inv", "transmittance_pct", "name", "experiment_id"]
    assert len(data) == 3401
    assert data.iloc[0][["wavenumber_cm_inv", "transmittance_pct"]].tolist() == [4000.0, 88.38]
    assert data["wavenumber_cm_inv"].dtype == "float64"
    assert dataset.metadata["instrument_definition"] == "ftir"
    assert dataset.metadata["schema_normalization"]["renamed_columns"] == {
        "wavenumber_cm_inv": "cm-1", "transmittance_pct": "%T"}
    pd.testing.assert_series_equal(data["name"], pd.Series(["poly1"] * 3401, name="name"))


# --- format description for chatbots ---------------------------------------

def test_spec_card_example_is_a_valid_definition():
    from mfethuls.instruments.spec import _EXAMPLE

    parse_definition(_EXAMPLE)


def test_spec_card_holds_rules_quantities_and_only_the_file_head(tmp_path):
    from mfethuls.instruments.spec import spec_card

    path = tmp_path / "export.txt"
    path.write_text("".join(f"line {i}\n" for i in range(100)), encoding="utf-8")
    card = spec_card(path, max_lines=5, hints="Use the sample temperature.")

    assert "Reply with the JSON only" in card
    assert all(f"`{name}`" in card for name in QUANTITIES)
    assert "line 4" in card and "line 5" not in card
    assert "Use the sample temperature." in card


def test_json_schema_lists_every_quantity_and_operation():
    from mfethuls.instruments.definition import DERIVED_OPS
    from mfethuls.instruments.spec import json_schema

    schema = json_schema()
    quantity_enum = schema["properties"]["columns"]["items"]["oneOf"][0]["properties"]["quantity"]["enum"]
    assert set(quantity_enum) == set(QUANTITIES)
    assert schema["properties"]["derived"]["items"]["properties"]["op"]["enum"] == list(DERIVED_OPS)
    json.dumps(schema)  # serialisable


def test_tga_example_reads_as_before_the_migration():
    """Values the former code parser (parsers/tga.py) produced for the example file, plus what it dropped."""
    dataset = get_parser("tga", "tgaX").parse({"x": [str(EXAMPLE_DATA / "TGA" / "poly1.txt")]}, experiment_id="e",
                                              instrument_type="tga", instrument_model="tgaX")
    data = dataset.data
    assert len(data) == 2851
    first = data.iloc[0]
    assert first["temperature_C"] == 25.0 and first["time_s"] == 0.0
    assert first["mass_mg"] == pytest.approx(2.47986)
    assert first["heat_flow_mW"] == pytest.approx(29.8255)
    assert first["temperature_sample_C"] == pytest.approx(32.1864)
    # % of the initial mass (TGA convention); the code parser scaled min-max (98.08 % here).
    assert first["mass_pct"] == 100.0
    assert data["mass_pct"].iloc[-1] == pytest.approx(data["mass_mg"].iloc[-1] / first["mass_mg"] * 100)
    assert "Index [#]" in data.columns
    assert dataset.metadata["file_text"]["poly1.txt"]["footer"] == ["LUB457, 11.02.2026 10:03:11"]


def test_range_warnings_point_at_wrong_units():
    from mfethuls.instruments.units import range_warnings

    frame = pd.DataFrame({"temperature_C": [25.0, 600.0], "mass_mg": [10_000.0, 9_000.0], "other": [1e9, 2e9]})
    (warning,) = range_warnings(frame, "tga")
    assert warning.startswith("Mass (mass_mg) goes from 9000 to 1e+04 mg")
    assert range_warnings(pd.DataFrame({"storage_modulus_mpa": [1e9]}), "dma") == []  # no range: no warning


def test_problems_prompt_for_the_chatbot():
    from mfethuls.instruments.spec import problems_prompt

    text = problems_prompt(["'model' is missing"], {"name": "x"})
    assert text.splitlines()[:2] == [
        "mfethuls checked your instrument definition against the file and found these problems:",
        "- 'model' is missing"]
    assert "reply with the corrected JSON only" in text and '"name": "x"' in text


def test_detection_summary_for_the_chatbot():
    from mfethuls.instruments.detect import detect

    summary = detect(EXAMPLE_DATA / "TGA" / "poly1.txt").summary()
    assert "- column 'Weight [mg]': mass (mg)" in summary
    assert "- column 'Index [#]': not recognised" in summary
    assert "looks like measurement type 'tga'" in summary


def test_text_in_number_columns_is_found_with_its_line(tmp_path):
    from mfethuls.parsers.tabular import text_in_numbers

    path = tmp_path / "t.txt"
    path.write_text("T m\n1 2\n3 4\n5 6\nResults: fine\nMax 6\n", encoding="utf-8")
    fmt = _definition(file={"delimiter": "whitespace"}).formats[0].file
    assert text_in_numbers(path, fmt) == {"rows": 2, "columns": ["T", "m"], "first_line": 5, "first_text": "Results: fine"}
    ended = _definition(file={"delimiter": "whitespace", "data_ends": "first_non_numeric_row"}).formats[0].file
    assert text_in_numbers(path, ended) is None


def test_prompt_holds_the_start_and_the_end_of_the_file(tmp_path):
    from mfethuls.instruments.spec import spec_card

    path = tmp_path / "long.txt"
    path.write_text("".join(f"line {i}\n" for i in range(1, 101)), encoding="utf-8")
    card = spec_card(path, max_lines=5, tail_lines=3, other_files={"b.txt": ["The file has 9 lines:"]})
    assert "The first 5 and last 3 of its 100 lines of `long.txt`:" in card
    assert "line 5\n… 92 lines left out …\nline 98" in card and "line 100" in card and "line 6\n" not in card
    assert "Another file of this instrument, `b.txt`" in card and "The file has 9 lines:" in card
    short = tmp_path / "short.txt"
    short.write_text("a\nb\n", encoding="utf-8")
    assert "All 2 lines of `short.txt`:" in spec_card(short)


def test_decimal_comma_survives_text_rows_after_the_table(tmp_path):
    """Text rows keep a column as text; its numbers must still be read with the decimal comma."""
    path = tmp_path / "s.dat"
    path.write_text("T;m\n25,5;1,5\n26,5;1,25\nResults;done\n", encoding="utf-8")
    definition = _definition(
        file={"extensions": [".dat"], "delimiter": "semicolon", "decimal": ","},
        columns=[{"source": "T", "quantity": "temperature", "unit": "°C"},
                 {"source": "m", "quantity": "mass", "unit": "mg"}],
    )
    data = _parse(definition, path).data
    assert data["temperature_C"].tolist()[:2] == [25.5, 26.5]
    assert data["mass_mg"].tolist()[:2] == [1.5, 1.25]
    assert len(data) == 3  # the text row is kept (and flagged by the check)


# --- names listed before the table, values from the file name and header -------

DMA_TEXT = (
    "Instrument\tDMA Q800 V21.3\nNsig\t3\nSig1\tTime (min)\nSig2\tTemperature (°C)\nSig3\tStorage Modulus (MPa)\n"
    "Time\t12:12:15\nStartOfData\n\n1.5\t27.4\t14.6\n2.0\t27.5\t14.7\n"
)


def test_column_names_listed_one_per_line_before_the_table(tmp_path):
    """DMA Q800: 'SigN<tab>name' lines name the columns; minutes are stored as seconds."""
    path = tmp_path / "run.txt"
    path.write_text(DMA_TEXT, encoding="utf-8")
    definition = parse_definition(json.loads((BUILTIN / "dma.json").read_text(encoding="utf8")))
    data = _parse(definition, path).data
    assert data["time_s"].tolist() == [90.0, 120.0]
    assert data["temperature_C"].tolist() == [27.4, 27.5]
    assert data["storage_modulus_mpa"].tolist() == [14.6, 14.7]


def test_names_from_needs_a_group_and_no_header_rows():
    with pytest.raises(DefinitionError) as exc:
        _definition(file={"header": {"rows": 1, "names_from": "^Sig"}})
    assert "one group" in str(exc.value)
    with pytest.raises(DefinitionError) as exc:
        _definition(file={"header": {"rows": 1, "names_from": r"^Sig\d+\t(.+)$"}})
    assert "set 'file.header.rows' to 0" in str(exc.value)


def test_file_name_values_are_looked_up(tmp_path):
    """SEC: the detector code at the end of the file name becomes ri / uv; unknown codes are kept."""
    definition = parse_definition(json.loads((BUILTIN / "sec.json").read_text(encoding="utf8")))
    for stem, detector in (("LUB425.dx_RID1A", "ri"), ("LUB425.dx_VWD1A", "uv"), ("S1_MALS", "ls"),
                           ("S1_visc", "viscometer"), ("S1.dx_XYZ1A", "XYZ1A")):
        path = tmp_path / f"{stem}.CSV"
        path.write_text("0.0056,349.74\n0.0128,349.2\n", encoding="utf-8")
        data = _parse(definition, path).data
        assert data["detector_name"].tolist() == [detector] * 2, stem
        assert data["retention_time_min"].tolist() == [0.0056, 0.0128]


def test_header_date_plus_file_name_milliseconds_give_the_timestamp():
    """Flame: 'Date: ... CEST 2025' in the header + '-757' in the file name, stored in UTC."""
    definition = parse_definition(json.loads((BUILTIN / "fluorescence_insitu.json").read_text(encoding="utf8")))
    folder = EXAMPLE_DATA / "Fluorescence" / "poly3"
    files = sorted(str(p) for p in folder.glob("*.txt"))[:2]
    data = TabularParser(definition).parse({"x": files}, experiment_id="e1").data
    first = data[data["source_file"] == "poly3__0__18-11-09-757"]
    assert str(first["header_time"].iloc[0]) == "2025-05-11 16:11:09+00:00"
    assert first["file_time_ms"].iloc[0] == 757.0
    assert str(first["timestamp"].iloc[0]) == "2025-05-11 16:11:09.757000+00:00"
    assert set(data["name"]) == {"poly3"}
    assert {"wavelength_nm", "emission_counts", "time_s"} <= set(data.columns)


def test_header_values_of_each_type(tmp_path):
    path = tmp_path / "x.txt"
    path.write_text("Sample: LUB9\nWeight: 9,30 mg\nStart: 2025-01-02 10:00:00\nT;m\n1;2\n", encoding="utf-8")
    definition = _definition(
        file={"extensions": [".txt"], "delimiter": "semicolon", "decimal": ",", "header": {"starts_at": "T;m"}},
        columns=[{"source": "T", "quantity": "temperature"}],
        from_header=[
            {"column": "sample", "pattern": "^Sample: (.+)$"},
            {"column": "weight_mg", "pattern": r"^Weight: ([\d,]+)", "type": "number"},
            {"column": "start", "pattern": "^Start: (.+)$", "type": "datetime", "timezone": "Europe/Zurich"},
            {"column": "missing", "pattern": "^Nothing: (.+)$", "type": "number"},
        ],
    )
    data = _parse(definition, path).data
    assert data["sample"].tolist() == ["LUB9"]
    assert data["weight_mg"].tolist() == [9.3]
    assert str(data["start"].iloc[0]) == "2025-01-02 09:00:00+00:00"  # winter time, UTC+1
    assert data["missing"].isna().all()


def test_captured_values_are_checked():
    with pytest.raises(DefinitionError) as exc:
        _definition(
            from_header=[{"column": "a", "pattern": "(x", "type": "text"},
                         {"column": "b", "pattern": "x", "type": "date"},
                         {"column": "c", "pattern": "x", "timezone": "Europe/Zurich"},
                         {"column": "d", "pattern": "x", "type": "datetime", "timezone": "Mars/Base"}],
            from_file_name=[{"column": "e", "pattern": "x", "values": {"ri": "(RI"}},
                            {"column": "g", "pattern": "y"}, {"column": "g", "pattern": "z"}],
            derived=[{"op": "add_time", "column": "e", "into": "t"},
                     {"op": "scale", "column": "e", "into": "f", "factor": 2, "unit": "ms"}],
        )
    text = str(exc.value)
    for expected in ("not a valid regular expression", "'type' must be one of", "only goes with type datetime",
                     "not a known time zone", "'values' pattern of 'ri'", "filled twice",
                     "add_time needs 'amount'", "only go with add_time"):
        assert expected in text, expected


# --- several tables in one file (blocks) -----------------------------------------

RHEO_TEXT = (
    "Project:\tUV\n\nTest:\tCL081_sampleCL061\n\nResult:\tMeasurement 1\n\n"
    "Interval and data points:\t1\t2\n"
    "Interval data:\tPoint No.\tTime\tStorage Modulus\tStatus\n\t\t\t\t\n\t\t[s]\t[Pa]\t\n"
    "\t1\t1\t7831.7\tME-,WMa\n\t2\t2\t8178.7\t\n\n"
    "Interval and data points:\t2\t1\n"
    "Interval data:\tPoint No.\tTime\tStorage Modulus\tStatus\n\t\t\t\t\n\t\t[s]\t[Pa]\t\n"
    "\t1\t61\t8274.5\tWMa\n"
)


def test_one_table_per_interval_labels_its_rows(tmp_path):
    """Anton Paar: each interval repeats its header; rows get the interval number, no header row is data."""
    path = tmp_path / "CL081.csv"
    path.write_text(RHEO_TEXT, encoding="utf-8")
    definition = parse_definition(json.loads((BUILTIN / "rheometer.json").read_text(encoding="utf8")))
    dataset = _parse(definition, path)
    data = dataset.data
    assert data["interval"].tolist() == [1, 1, 2]
    assert data["time_s"].tolist() == [1.0, 2.0, 61.0]
    assert data["storage_modulus_pa"].tolist() == [7831.7, 8178.7, 8274.5]
    assert data["Status"].tolist() == ["ME-,WMa", None, "WMa"]  # an empty text cell is missing, not ""
    text = dataset.metadata["file_text"]["CL081.csv"]
    assert text["preamble"] == ["Project:\tUV", "Test:\tCL081_sampleCL061", "Result:\tMeasurement 1"]
    assert text["blocks"] == ["Interval and data points:\t1\t2", "Interval and data points:\t2\t1"]


def test_blocks_without_a_label_are_numbered_and_may_differ_in_columns(tmp_path):
    path = tmp_path / "steps.txt"
    path.write_text("== step\nT;m\n1;2\n== step\nT;m;p\n3;4;5\n", encoding="utf-8")
    definition = _definition(
        file={"extensions": [".txt"], "delimiter": "semicolon", "header": {"rows": 1},
              "blocks": {"starts_at": "== step", "column": "step"}},
        columns=[{"source": "T", "quantity": "temperature"}],
    )
    data = _parse(definition, path).data
    assert data["step"].tolist() == [1, 2]
    assert data["temperature_C"].tolist() == [1.0, 3.0]
    assert data["p"].isna().tolist() == [True, False]


def test_blocks_are_checked(tmp_path):
    with pytest.raises(DefinitionError) as exc:
        _definition(file={"blocks": {"starts_at": "", "column": "x"}})
    assert "'file.blocks.starts_at'" in str(exc.value)
    with pytest.raises(DefinitionError) as exc:
        _definition(file={"blocks": {"starts_at": "Interval", "label": "Interval"}})
    assert "'file.blocks.label' must be a regular expression with one group" in str(exc.value)
    path = tmp_path / "x.txt"
    path.write_text("T [°C] m [g]\n1 2\n", encoding="utf-8")
    data = _parse(_definition(file={"blocks": {"starts_at": "Interval"}}), path).data  # no block line: block 1
    assert data["block"].tolist() == [1] and len(data) == 1


def test_duplicate_rows_and_text_tables(tmp_path):
    path = tmp_path / "s.txt"
    path.write_text("T m\n1 5\n1 5\n1 6\n2 7\nResults\nPeak at\n1.5 7 sharp\n\n9 x\nEnd\n3 3\n", encoding="utf-8")
    definition = _definition(
        file={"header": {"rows": 1}, "data_ends": "Results", "duplicate_rows": "drop"},
        columns=[{"source": "T", "quantity": "temperature", "unit": "°C"}],
        tables=[{"name": "peaks", "starts_at": "Peak at", "ends_at": "End", "columns": ["T", "height"]}],
    )
    dataset = _parse(definition, path)
    assert dataset.data["temperature_C"].tolist() == [1.0, 1.0, 2.0]
    assert dataset.data["m"].tolist() == [5.0, 6.0, 7.0]
    assert dataset.metadata["tables"] == {"peaks": {"s.txt": [
        {"T": 1.5, "height": 7.0, "column_3": "sharp"}, {"T": 9.0, "height": "x"}]}}
    text = dataset.metadata["file_text"]["s.txt"]
    assert text["footer"][0] == "Results" and "3 3" in text["footer"]  # the lines stay in the text
    assert text["notes"] == ["1 row(s) repeating an earlier row in every field left out"]
    # Kept by default.
    kept = _parse(_definition(file={"header": {"rows": 1}, "data_ends": "Results"},
                              columns=[{"source": "T", "quantity": "temperature", "unit": "°C"}]), path)
    assert len(kept.data) == 4 and "tables" not in kept.metadata


@pytest.mark.parametrize(("change", "problem"), [
    ({"file": {"duplicate_rows": "yes"}}, "'file.duplicate_rows' must be keep or drop"),
    ({"tables": {"name": "x"}}, "'tables' must be a list"),
    ({"tables": [{"name": "bad name", "starts_at": "P"}]}, "needs a simple 'name'"),
    ({"tables": [{"name": "p"}]}, "'starts_at' must be text"),
    ({"tables": [{"name": "p", "starts_at": "P", "columns": "mz"}]}, "'columns' must list simple names"),
    ({"tables": [{"name": "p", "starts_at": "P"}, {"name": "p", "starts_at": "Q"}]}, "another table has this name"),
    ({"tables": [{"name": "p", "starts_at": "P", "end": "E"}]}, "unknown key 'end'"),
])
def test_duplicate_rows_and_tables_are_checked(change, problem):
    with pytest.raises(DefinitionError) as info:
        _definition(**change)
    assert any(problem in line for line in info.value.problems), info.value.problems


def test_mettler_old_and_new_exports_are_each_read_by_their_own_definition(tmp_path):
    from mfethuls.instruments.configured import get_reader, reader_for

    # A made-up file in the old STARe report layout (title block, "Curve Values:", per-gram values).
    old = tmp_path / "old.txt"
    old.write_text("Title                                    01.01.2024 10:00\n\nCurve Name:\n  sample\nCurve Values:\n"
                   "          Index              t             Ts             Tr          Value\n"
                   "                           [s]           [°C]           [°C]        [Wg^-1]\n"
                   + "".join(f"{i:15d}{i:15d}{20 + i:15.3f}{20 + i:15.3f}{0.01 * i:15.6f}\n" for i in range(5))
                   + "\nSample:\n  made-up, 5.000 mg\n", encoding="cp1252")
    new = EXAMPLE_DATA / "DSC" / "poly1.txt"

    v0, v1 = get_reader("dsc_mettler_toledo_v0").parser, get_reader("dsc_mettler_toledo_v1").parser
    # In one DSC folder, each export goes to its own reader.
    assert [reader_for("dsc", [str(f)]).name for f in (old, new)] == ["dsc_mettler_toledo_v0", "dsc_mettler_toledo_v1"]
    assert "heat_flow_W_g" in v0.parse({"x": [str(old)]}, experiment_id="e").data
    assert len(v1.parse({"x": [str(new)]}, experiment_id="e").data) > 1000
    with pytest.raises(Exception, match="no 'Curve Values:'"):
        v1.parse({"x": [str(old)]}, experiment_id="e")
    with pytest.raises(Exception, match="'Curve Values:'"):
        v0.parse({"x": [str(new)]}, experiment_id="e")


def test_not_contains_must_be_text():
    with pytest.raises(DefinitionError, match="file.not_contains"):
        _definition(file={"not_contains": ""})
    assert _definition(file={"not_contains": "Curve Values:"}).formats[0].file.not_contains == "Curve Values:"
