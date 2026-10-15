"""Files of one instrument registered as another: caught in Review & register, and never stored by ingest."""

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.discovery import discover_unregistered, probe_raw_data, proposed_rows, validate_proposed
from mfethuls.parsers.ingestion import ParseError
from mfethuls.stores import open_local_stores


def _shimadzu_file(path, offset):
    lines = ['"LUB621"', '"Wavelength nm."\t"Absorbance"'] + [f"{200 + i}.0\t{0.1 * i + offset:.3f}" for i in range(20)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A titration folder of Shimadzu UV-Vis files, the kind that gets proposed as in-situ (Flame) data."""
    data = tmp_path / "data"
    for i in range(3):
        _shimadzu_file(data / "UV_Vis" / "LUB621" / f"LUB621_{i:03d}.txt", i)
    monkeypatch.setenv("PATH_TO_DATA", str(data))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    return data


def test_shimadzu_files_do_not_read_as_flame_data(lab):
    assert "Flame" in probe_raw_data("uv_insitu", "LUB621")
    assert probe_raw_data("uv_vis", "LUB621") is None


def test_review_and_register_rejects_the_wrong_instrument(lab):
    registry = Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))
    rows = proposed_rows(discover_unregistered(registry), registry, split=set())  # the folder as one experiment
    assert list(rows["instrument_name"]) == ["uv_insitu"]  # the suggestion that went wrong

    (result,) = validate_proposed(registry, rows)
    assert not result["valid"]
    assert any("does not read as uv_insitu data" in e["message"] for e in result["errors"])

    rows.loc[0, "instrument_name"] = "uv_vis"
    (result,) = validate_proposed(registry, rows)
    assert result["valid"], result["errors"]


def test_ingest_fails_instead_of_storing_wrong_data(lab):
    registry = Registry.from_frame(pd.DataFrame([
        {"name": "LUB621", "instrument_name": "uv_insitu", "raw_data_filename": "LUB621"},
    ]))
    with open_local_stores() as stores:
        with pytest.raises(ParseError, match="Flame"):
            ingest_experiment_dataset("LUB621", refresh=True, registry=registry, stores=stores)
        assert stores.catalog.list_registered() == []

    right = Registry.from_frame(pd.DataFrame([
        {"name": "LUB621", "instrument_name": "uv_vis", "raw_data_filename": "LUB621"},
    ]))
    with open_local_stores() as stores:
        result = ingest_experiment_dataset("LUB621", refresh=True, registry=right, stores=stores)
        assert result["status"] == "persisted"
        (row,) = stores.catalog.list_registered()
    assert row["instrument_name"] == "uv_vis" and row["rows"] == 60
