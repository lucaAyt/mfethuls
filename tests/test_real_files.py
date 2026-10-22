"""The lab's own test files still read as they did (local only: skipped without them, as in CI).

Point ``MFETHULS_REAL_DATA`` at a folder laid out like a data folder (one subfolder per
instrument). The test finds every experiment in it as **Register new data** does, reads
each with every instrument that can read it, and compares which readers succeed, their
row counts and columns with what was recorded the first time.

The record is a JSON file outside the repo: ``MFETHULS_REAL_DATA_EXPECTED``, by default
``~/.mfethuls/real_data_expected.json``. The first run writes it (and skips); after a
deliberate change, ``MFETHULS_REAL_DATA_UPDATE=1`` records the results again.

Nothing is written to the data folder (no ingest, no manifest) and nothing from it enters
the repo: these files are the lab's, not public.
"""

import json
import os
from pathlib import Path

import pandas as pd
import pytest

# Read when the module is imported: the conftest clears MFETHULS_* variables for each test.
REAL = os.environ.get("MFETHULS_REAL_DATA", "")
EXPECTED = Path(os.environ.get("MFETHULS_REAL_DATA_EXPECTED")
                or Path.home() / ".mfethuls" / "real_data_expected.json")
UPDATE = os.environ.get("MFETHULS_REAL_DATA_UPDATE") == "1"

needs_real_files = pytest.mark.skipif(not REAL or not Path(REAL).is_dir(),
                                      reason="MFETHULS_REAL_DATA is not set (the lab's own test files)")


def _read_all(data_root: str) -> dict:
    """``{"Folder/name": {instrument: {"rows": n, "columns": [...]}}}`` for every experiment found."""
    from mfethuls.discovery import discover_unregistered
    from mfethuls.experiments import Registry
    from mfethuls.instruments.configured import parser_for

    empty = Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))
    found = {}
    for item in discover_unregistered(empty, data_root):
        readings = {}
        for instrument in item.instruments:
            try:
                data = parser_for(instrument).parse({item.raw_data_filename: item.files}, experiment_id="real",
                                                    instrument_name=instrument).data
            except Exception:  # noqa: BLE001 - this instrument does not read these files
                continue
            if len(data):
                readings[instrument] = {"rows": int(len(data)), "columns": [str(c) for c in data.columns]}
        found[f"{item.folder_name}/{item.raw_data_filename}"] = readings
    return found


def _differences(expected: dict, found: dict) -> list:
    problems = [f"{key}: no instrument reads it any more" for key, readings in found.items() if not readings]
    for key in sorted(set(expected) - set(found)):
        problems.append(f"{key}: no longer found in the data folder")
    for key in sorted(set(found) - set(expected)):
        problems.append(f"{key}: new (record it with MFETHULS_REAL_DATA_UPDATE=1)")
    for key in sorted(set(expected) & set(found)):
        before, now = expected[key], found[key]
        for instrument in sorted(set(before) - set(now)):
            problems.append(f"{key}: {instrument} no longer reads it")
        for instrument in sorted(set(now) - set(before)):
            problems.append(f"{key}: {instrument} now reads it too")
        for instrument in sorted(set(before) & set(now)):
            if before[instrument]["rows"] != now[instrument]["rows"]:
                problems.append(f"{key} ({instrument}): {now[instrument]['rows']} rows instead of "
                                f"{before[instrument]['rows']}")
            if before[instrument]["columns"] != now[instrument]["columns"]:
                missing = [c for c in before[instrument]["columns"] if c not in now[instrument]["columns"]]
                added = [c for c in now[instrument]["columns"] if c not in before[instrument]["columns"]]
                problems.append(f"{key} ({instrument}): columns changed (missing {missing or '-'}, "
                                f"new {added or '-'})")
    return problems


@needs_real_files
def test_the_labs_files_read_as_recorded(monkeypatch):
    from mfethuls.settings import configure

    monkeypatch.setenv("PATH_TO_DATA", REAL)  # read only: storage stays in the test's temporary folder
    configure(None)
    found = _read_all(REAL)
    assert found, f"No experiments found in {REAL}"

    if UPDATE or not EXPECTED.exists():
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n", encoding="utf8")
        pytest.skip(f"Recorded how {len(found)} experiments read in {EXPECTED}; run again to compare.")

    problems = _differences(json.loads(EXPECTED.read_text(encoding="utf8")), found)
    assert not problems, "The lab's files read differently than recorded:\n" + "\n".join(problems)


def test_differences_are_reported():
    # The comparison itself, on made-up results: runs everywhere.
    before = {"DSC/a": {"dsc": {"rows": 10, "columns": ["temperature_C", "heat_flow_mW"]}}, "DSC/gone": {"dsc": {}}}
    now = {"DSC/a": {"dsc": {"rows": 9, "columns": ["temperature_C"]}, "tga": {"rows": 1, "columns": []}},
           "DSC/new": {}}
    problems = _differences(before, now)
    assert "DSC/a (dsc): 9 rows instead of 10" in problems
    assert any("missing ['heat_flow_mW']" in p for p in problems)
    assert "DSC/a: tga now reads it too" in problems and "DSC/gone: no longer found in the data folder" in problems
    assert "DSC/new: no instrument reads it any more" in problems
