"""Definition patterns are checked when loaded and run with a time limit; definitions cannot reach outside."""

import ast
import json
import time
from pathlib import Path

import pytest

from mfethuls.instruments import patterns
from mfethuls.instruments.definition import (
    MAX_DEFINITION_BYTES,
    DefinitionError,
    builtin_definitions,
    definition_json,
    load_definition,
    parse_definition,
)
from mfethuls.parsers.ingestion import ParseError
from mfethuls.parsers.tabular import TabularParser

SRC = Path(__file__).resolve().parents[1] / "src" / "mfethuls"


def _definition(**changes):
    data = {
        "name": "probe", "type": "probe", "model": "x",
        "file": {"extensions": [".txt"], "delimiter": "tab"},
        "columns": [{"source": "a", "column": "a"}],
    }
    data.update(changes)
    return data


def _problems(data):
    with pytest.raises(DefinitionError) as exc:
        parse_definition(data)
    return " | ".join(exc.value.problems)


# --- patterns -------------------------------------------------------------------------------------

@pytest.mark.parametrize("pattern", [
    r"^Sample Weight:\s*([0-9.]+)\s*mg",
    r"_0*([^_]+)$",
    r"\d{2}-\d{2}-\d{2}-(\d{1,3})$",
    r"^Sig\d+\t(.+)$",
    r"(\d{2}-)+x",         # the repeated part has a fixed length
    r"(?:\w++\s)+:",       # possessive: never backtracks
    r"^{sheet}\t([0-9]+\.[0-9]+)\t",
])
def test_accepts_ordinary_patterns(pattern):
    assert patterns.problem(pattern) is None


@pytest.mark.parametrize("pattern", [r"(\w+\s?)+:", r"(a*)*b", r"^(\s*\S+)*:", r"((ab)?c+)+", r"(?:x|(y+))*z"])
def test_refuses_a_repeat_inside_a_repeat(pattern):
    assert "repeats a part that itself repeats" in patterns.problem(pattern)


def test_refuses_long_invalid_and_groupless_patterns():
    assert "longer than" in patterns.problem("a" * (patterns.MAX_LENGTH + 1))
    assert "not a valid regular expression" in patterns.problem("(unclosed")
    assert "needs a group" in patterns.problem(r"^Sig\d+", groups=1)
    assert patterns.problem("") and patterns.problem(None)


def test_every_builtin_definition_passes():
    assert builtin_definitions()


def test_a_slow_pattern_times_out_instead_of_hanging():
    slow = r"^(.*?,){11}P"  # not caught by the shape check: a fixed count of a lazy repeat
    assert patterns.problem(slow) is None
    start = time.perf_counter()
    with pytest.raises(patterns.PatternError, match="took longer than"):
        patterns.search(slow, "1," * 40)
    # Afterwards it fails at once, not once more per file.
    with pytest.raises(patterns.PatternError):
        patterns.search(slow, "1," * 40)
    assert time.perf_counter() - start < 4 * patterns.TIMEOUT_S


def test_a_slow_pattern_fails_the_file_with_its_name(tmp_path):
    path = tmp_path / "run1.txt"
    path.write_text("Note: " + "1," * 40 + "\na\n1\n2\n", encoding="utf8")
    definition = parse_definition(_definition(
        file={"extensions": [".txt"], "delimiter": "tab", "header": {"starts_at": "a"}},
        from_header=[{"column": "note", "pattern": r"^Note: (.*?,){12}P"}]))
    with pytest.raises(ParseError, match="run1.txt.*took longer than"):
        TabularParser(definition).parse({"run1": [str(path)]}, instrument_type="probe")


def test_definition_patterns_only_run_through_the_patterns_module():
    """``re`` calls elsewhere must use a pattern written in the code, never one from a definition."""
    calls = ("search", "match", "fullmatch", "compile", "findall", "finditer", "sub", "subn", "split")
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "patterns.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                if "regex" in names:
                    offenders.append(f"{path.name}:{node.lineno} imports regex")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in calls
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "re"):
                first = node.args[0] if node.args else None
                literal = isinstance(first, ast.Constant) and isinstance(first.value, str)
                if not literal and not _module_constant(first):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno} re.{node.func.attr}")
    assert not offenders, offenders


def _module_constant(node) -> bool:
    """Patterns built in the code itself, e.g. ``re.escape(name) + r"..."`` or a module constant."""
    if isinstance(node, ast.Name) and node.id.isupper():
        return True
    if isinstance(node, ast.JoinedStr):  # f-strings in the code: only of escaped parts
        return all(isinstance(v, ast.Constant) or (isinstance(v, ast.FormattedValue) and _escaped(v.value))
                   for v in node.values)
    return False


def _escaped(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "escape")


# --- other untrusted input in definitions ---------------------------------------------------------

@pytest.mark.parametrize("folder", ["../Windows", "C:/Users", "a/b", "..", "/etc", "x\\y", "a:b"])
def test_an_instruments_folder_is_one_plain_folder(folder):
    from mfethuls.instruments.configured import parse_instrument

    with pytest.raises(DefinitionError, match="'folder_name'"):
        parse_instrument({"name": "probe", "type": "tga", "folder_name": folder})


@pytest.mark.parametrize("sample", ["../../secret.txt", "C:/secret.txt", "sub/x.txt", ".."])
def test_check_sample_is_a_file_next_to_the_definition(sample):
    assert "'check.sample'" in _problems(_definition(check={"sample": sample}))


def test_timezone_is_a_zone_name_not_a_file(tmp_path):
    zone_file = tmp_path / "zone"
    zone_file.write_text("not a zone", encoding="utf8")
    for timezone in (str(zone_file), "../zone", "Not/AZone"):
        values = [{"column": "t", "pattern": "(.+)", "type": "datetime", "timezone": timezone}]
        assert "not a known time zone" in _problems(_definition(from_header=values))
    values = [{"column": "t", "pattern": "(.+)", "type": "datetime", "timezone": "Europe/Zurich"}]
    assert parse_definition(_definition(from_header=values)).from_header[0].timezone == "Europe/Zurich"


def test_characterizer_and_plot_take_known_keys_only():
    assert "'characterizer'" in _problems(_definition(characterizer={"type": "os.system"}))
    assert "'characterizer.sensitivity'" in _problems(
        _definition(characterizer={"type": "dsc_profiling", "sensitivity": "1; rm"}))
    assert "unknown key 'path'" in _problems(_definition(characterizer={"type": "tga", "path": "x"}))
    assert "unknown key 'kind'" in _problems(_definition(plot={"x": "a", "y": "a", "kind": "x"}))


def test_oversized_and_deeply_nested_json_are_refused(tmp_path):
    with pytest.raises(DefinitionError, match="nested too deeply"):
        definition_json("[" * 100_000 + "]" * 100_000)
    with pytest.raises(DefinitionError, match="larger than"):
        definition_json(json.dumps({"description": "x" * MAX_DEFINITION_BYTES}))
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"description": "x" * MAX_DEFINITION_BYTES}), encoding="utf8")
    with pytest.raises(DefinitionError, match="larger than"):
        load_definition(big)


def test_a_broken_lab_file_does_not_hide_the_others(tmp_path):
    from mfethuls.instruments.configured import LAB_INSTRUMENTS, LAB_READERS, lab_statuses

    for folder in (LAB_READERS, LAB_INSTRUMENTS):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "nested.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf8")
    (tmp_path / LAB_READERS / "probe.json").write_text(json.dumps(_definition()), encoding="utf8")
    (tmp_path / LAB_INSTRUMENTS / "probe.json").write_text(
        json.dumps({"name": "probe", "type": "probe", "folder_name": "Probe"}), encoding="utf8")
    statuses = {(s.kind, Path(s.source).name): s for s in lab_statuses(str(tmp_path))}
    assert statuses["reader", "probe.json"].active and statuses["instrument", "probe.json"].active
    for kind in ("reader", "instrument"):
        assert not statuses[kind, "nested.json"].active and statuses[kind, "nested.json"].problems


def test_app_messages_show_markdown_as_text():
    pytest.importorskip("streamlit")
    from mfethuls.app.instruments import _plain

    shown = _plain("unknown key '![x](https://example.com/b.png)' and [a link](https://example.com) $x$")
    assert "![x](" not in shown and "](https" not in shown and "$x$" not in shown


def test_a_characterizer_only_goes_with_its_instrument_type():
    from mfethuls.factory import create_characterizer

    assert "works on dsc data, not probe" in _problems(_definition(characterizer={"type": "dsc_profiling"}))
    assert create_characterizer("tga", {"type": "dsc_profiling"}) is None
    assert create_characterizer("dsc", {"type": "dsc_profiling", "sensitivity": 0.2}).__class__.__name__ == "DSCProfiling"
    assert create_characterizer("tga", {"type": "tga"}).__class__.__name__ == "TGACharacterizer"
