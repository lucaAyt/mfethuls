"""Giving an instrument another folder of the data folder (``DMA data`` instead of ``DMA``)."""

import json
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.discovery import discover_unregistered, proposed_rows, suggest_instruments, unclaimed_folders, validate_proposed
from mfethuls.examples import DATA_DIR
from mfethuls.instruments.configured import folder_links, folders_file, instrument_definitions, instrument_entries, link_folder, save_definition

from test_lab_definitions import PHOTOMETER, _sample


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("PATH_TO_DATA", str(root))
    yield root
    instrument_definitions(data_root="")  # unregister the lab parsers again


def _folder(name: str) -> str:
    return next(e for e in instrument_entries() if e["name"] == name)["folder_name"]


def _empty_registry() -> Registry:
    return Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))


@pytest.mark.parametrize("folder, suggested", [
    ("DMA data", "DMA"), ("dma_Q800", "DMA"), ("Rheometer 2024", "Rheology"), ("UV-Vis", "UV_Vis"),
    ("Tensile", "tensile_tester"), ("Misc", None), ("DMA and TGA", None),
])
def test_folder_names_suggest_their_instrument(data_root, folder, suggested):
    assert suggest_instruments(folder) == suggested


def test_a_built_in_instrument_reads_a_linked_folder(data_root):
    (data_root / "DSC data").mkdir()
    (data_root / "DSC data" / "poly 2.txt").write_bytes((DATA_DIR / "DSC" / "poly2.txt").read_bytes())
    (folder,) = unclaimed_folders()
    assert (folder.folder_name, folder.suggested) == ("DSC data", "DSC")
    dsc = [e["name"] for e in instrument_entries() if e["folder_name"] == "DSC"]

    link_folder(dsc, "DSC data")

    assert json.loads(folders_file().read_text(encoding="utf8")) == {name: "DSC data" for name in sorted(dsc)}
    assert unclaimed_folders() == []
    entry = next(e for e in instrument_entries() if e["name"] == "dsc_mettler_toledo_v1")
    assert (entry["folder_name"], entry["default_folder"]) == ("DSC data", "DSC")
    registry = _empty_registry()
    rows = proposed_rows(discover_unregistered(registry), registry)
    rows["instrument_name"] = "dsc_mettler_toledo_v1"
    (result,) = validate_proposed(registry, rows)
    assert result["valid"], result["errors"]


def test_linking_back_to_the_own_folder_removes_the_link(data_root):
    link_folder(["dma"], "DMA data")
    assert folder_links() == {"dma": "DMA data"}
    link_folder(["dma"], "DMA")
    assert folder_links() == {} and _folder("dma") == "DMA"


def test_one_kind_of_measurement_per_folder(data_root):
    with pytest.raises(ValueError, match="already the folder of tga"):
        link_folder(["dma"], "TGA")
    # Instruments of the same type may share a folder, as the DSC models do.
    link_folder(["dsc_default"], "DSC")
    with pytest.raises(ValueError, match="plain name"):
        link_folder(["dma"], "../elsewhere")
    with pytest.raises(ValueError, match="Unknown instrument"):
        link_folder(["no_such_instrument"], "X")


def test_a_lab_instrument_gets_its_folder_changed_in_its_file(data_root, tmp_path):
    # Saved with the wrong folder: it can still be pointed at the right one.
    path = save_definition({**PHOTOMETER, "folder_name": "Wrong"}, _sample(tmp_path / "s.dat"))
    link_folder(["photometer"], "Photometer data")

    assert json.loads(Path(path).read_text(encoding="utf8"))["folder_name"] == "Photometer data"
    assert _folder("photometer") == "Photometer data"
    assert folder_links() == {}


def test_bad_links_are_ignored(data_root):
    folders_file().parent.mkdir(parents=True)
    folders_file().write_text(json.dumps({"dma": "../outside", "tga": "TGA runs"}), encoding="utf8")
    assert folder_links() == {"tga": "TGA runs"}
    assert _folder("dma") == "DMA"
