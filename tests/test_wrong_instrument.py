"""Each export format is read by its own reader; data of another type is caught in Review & register,
and never stored by ingest."""

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.discovery import discover_unregistered, probe_raw_data, proposed_rows, validate_proposed
from mfethuls.examples import DATA_DIR
from mfethuls.parsers.ingestion import ParseError
from mfethuls.stores import open_local_stores


def _shimadzu_file(path, offset):
    lines = ['"LUB621"', '"Wavelength nm."\t"Absorbance"'] + [f"{200 + i}.0\t{0.1 * i + offset:.3f}" for i in range(20)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A titration folder of Shimadzu UV-Vis files next to in-situ (Flame) series: both are UV-Vis data."""
    data = tmp_path / "data"
    for i in range(3):
        _shimadzu_file(data / "UV_Vis" / "LUB621" / f"LUB621_{i:03d}.txt", i)
    (data / "UV_Vis" / "switch_A").mkdir(parents=True)
    for path in sorted((DATA_DIR / "Fluorescence" / "poly3").glob("*.txt"))[:3]:
        (data / "UV_Vis" / "switch_A" / path.name).write_bytes(path.read_bytes())
    monkeypatch.setenv("PATH_TO_DATA", str(data))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    return data


def test_each_series_is_read_by_the_reader_of_its_format(lab):
    assert probe_raw_data("uv_vis", "LUB621") is None
    assert probe_raw_data("uv_vis", "switch_A") is None
    registry = Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))
    rows = proposed_rows(discover_unregistered(registry), registry, split=set())  # each folder as one experiment
    assert sorted(rows["raw_data_filename"]) == ["LUB621", "switch_A"] and set(rows["instrument_name"]) == {"uv_vis"}
    assert all(r["valid"] for r in validate_proposed(registry, rows))

    with open_local_stores() as stores:
        for name in ("LUB621", "switch_A"):
            one = Registry.from_frame(pd.DataFrame([{"name": name, "instrument_name": "uv_vis",
                                                     "raw_data_filename": name}]))
            assert ingest_experiment_dataset(name, refresh=True, registry=one, stores=stores)["status"] == "persisted"
        readers = {row["experiment_name"]: (row["reader"], row["rows"]) for row in stores.catalog.list_registered()}
    assert readers["LUB621"] == ("uv_vis", 60) and readers["switch_A"][0] == "uv_insitu"


def test_data_of_another_type_is_refused(lab):
    (lab / "UV_Vis" / "poly1.txt").write_bytes((DATA_DIR / "DSC" / "poly1.txt").read_bytes())  # a DSC export
    assert "missing" in probe_raw_data("uv_vis", "poly1")
    registry = Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))
    rows = proposed_rows([i for i in discover_unregistered(registry) if i.raw_data_filename == "poly1"], registry)
    (result,) = validate_proposed(registry, rows)
    assert not result["valid"]
    assert any("does not read as uv_vis data" in e["message"] for e in result["errors"])

    wrong = Registry.from_frame(pd.DataFrame([{"name": "poly1", "instrument_name": "uv_vis",
                                               "raw_data_filename": "poly1"}]))
    with open_local_stores() as stores:
        with pytest.raises(ParseError, match="do not look like uv_vis data"):
            ingest_experiment_dataset("poly1", refresh=True, registry=wrong, stores=stores)
        assert stores.catalog.list_registered() == []
