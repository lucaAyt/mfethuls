"""Folders and instruments: each folder is one instrument's, each file read by the reader that recognises it."""

import json
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.discovery import (
    discover_unregistered,
    proposed_rows,
    recognise_files,
    suggest_type,
    unclaimed_folders,
    validate_proposed,
)
from mfethuls.examples import DATA_DIR
from mfethuls.instruments.configured import (
    assign_folder,
    get_instrument,
    instrument_for_folder,
    instruments_dir,
    reader_definitions,
    reader_for,
    save_definition,
    set_folder,
)

from test_lab_definitions import PHOTOMETER, _sample

SHIMADZU = '"compound A"\n"Wavelength nm."\t"Abs."\n400.0\t0.50\n401.0\t0.52\n402.0\t0.55\n'


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("PATH_TO_DATA", str(root))
    yield root
    reader_definitions(data_root="")  # unregister the lab parsers again


def _empty_registry() -> Registry:
    return Registry.from_frame(pd.DataFrame(columns=["name", "instrument_name", "raw_data_filename"]))


def _flame_series(folder: Path) -> None:
    folder.mkdir(parents=True)
    for path in sorted((DATA_DIR / "Fluorescence" / "poly3").glob("*.txt"))[:3]:
        (folder / path.name).write_bytes(path.read_bytes())


@pytest.mark.parametrize("folder, type_", [
    ("DMA data", "dma"), ("dma_Q800", "dma"), ("Rheometer 2024", "rheometer"), ("Rheology", "rheometer"),
    ("UV-Vis", "uv_vis"), ("inSitu_UV", "uv_vis"), ("Tensile", "tensile"), ("DSC room B", "dsc"),
    ("Misc", None), ("DMA and TGA", None),
])
def test_folder_names_suggest_their_measurement_type(data_root, folder, type_):
    assert suggest_type(folder) == type_


def test_a_folder_no_instrument_reads_is_unclaimed_until_one_does(data_root):
    (data_root / "DSC data").mkdir()
    (data_root / "DSC data" / "poly 2.txt").write_bytes((DATA_DIR / "DSC" / "poly2.txt").read_bytes())
    (folder,) = unclaimed_folders()
    assert (folder.folder_name, folder.suggested_type, folder.files) == ("DSC data", "dsc", ["poly 2.txt"])

    assert assign_folder("DSC data", "dsc") == "dsc"  # no DSC folder: the built-in dsc reads it
    assert unclaimed_folders() == [] and instrument_for_folder("dsc DATA").name == "dsc"
    registry = _empty_registry()
    rows = proposed_rows(discover_unregistered(registry), registry)
    assert rows[["raw_data_filename", "instrument_name"]].values.tolist() == [["poly 2", "dsc"]]
    (result,) = validate_proposed(registry, rows)
    assert result["valid"], result["errors"]


def test_the_files_tell_their_type(data_root):
    dsc, tga, flame = (DATA_DIR / "DSC" / "poly1.txt", DATA_DIR / "TGA" / "poly1.txt",
                       next((DATA_DIR / "Fluorescence" / "poly3").glob("*.txt")))
    # A Mettler DSC and a TGA export share the "Index" header; their columns tell them apart.
    assert recognise_files([str(dsc)]) == {"dsc_mettler_toledo_v1": 1}
    assert recognise_files([str(tga)]) == {"tga": 1}
    # Flame spectra are the same format for UV-Vis and fluorescence: both read them.
    assert set(recognise_files([str(flame)])) == {"fluorescence_insitu", "uv_insitu"}
    notes = data_root / "notes.txt"
    notes.write_text("nothing to read\n", encoding="utf8")
    assert recognise_files([str(notes)]) == {}


def test_each_file_of_a_folder_is_read_by_the_reader_that_recognises_it(data_root):
    uv = data_root / "UV_Vis"
    _flame_series(uv / "insitu_A")
    (uv / "compoundA.txt").write_text(SHIMADZU, encoding="utf8")
    insitu = sorted(str(p) for p in (uv / "insitu_A").iterdir())

    assert reader_for("uv_vis", insitu).name == "uv_insitu"
    assert reader_for("uv_vis", [str(uv / "compoundA.txt")]).name == "uv_vis"
    with pytest.raises(ValueError, match="no uv_vis reader reads these files"):
        reader_for("uv_vis", [str(uv / "plot.png")])

    registry = _empty_registry()
    rows = proposed_rows(discover_unregistered(registry), registry)
    assert sorted(rows[["raw_data_filename", "instrument_name"]].values.tolist()) == [
        ["compoundA", "uv_vis"], ["insitu_A", "uv_vis"]]
    assert all(r["valid"] for r in validate_proposed(registry, rows)), validate_proposed(registry, rows)


def test_a_file_no_reader_of_its_type_recognises_is_reported(data_root):
    (data_root / "DSC").mkdir()
    (data_root / "DSC" / "other.txt").write_text("Some other export\nx\ty\n1\t2\n", encoding="utf8")
    with pytest.raises(ValueError, match="other.txt is none of the dsc formats mfethuls reads"):
        reader_for("dsc", [str(data_root / "DSC" / "other.txt")])
    registry = _empty_registry()
    rows = proposed_rows(discover_unregistered(registry), registry)
    (result,) = validate_proposed(registry, rows)
    assert not result["valid"] and "none of the dsc formats" in " ".join(e["message"] for e in result["errors"])


def test_in_situ_spectra_kept_apart_are_a_second_uv_vis_instrument(data_root):
    (data_root / "UV_Vis").mkdir()
    (data_root / "UV_Vis" / "compoundA.txt").write_text(SHIMADZU, encoding="utf8")
    _flame_series(data_root / "inSitu_UV" / "switch_A")
    (folder,) = unclaimed_folders()
    assert (folder.folder_name, folder.suggested_type) == ("inSitu_UV", "uv_vis")

    # UV_Vis is there: the built-in uv_vis keeps it, a new instrument reads the in-situ folder.
    assert assign_folder("inSitu_UV", "uv_vis") == "insitu_uv"
    assert json.loads((instruments_dir() / "insitu_uv.json").read_text(encoding="utf8")) == {
        "spec_version": 1, "name": "insitu_uv", "type": "uv_vis", "folder_name": "inSitu_UV"}
    assert (get_instrument("uv_vis").folder_name, get_instrument("insitu_uv").folder_name) == ("UV_Vis", "inSitu_UV")
    registry = _empty_registry()
    rows = proposed_rows(discover_unregistered(registry), registry)
    assert sorted(rows[["raw_data_filename", "instrument_name"]].values.tolist()) == [
        ["compoundA", "uv_vis"], ["switch_A", "insitu_uv"]]
    assert all(r["valid"] for r in validate_proposed(registry, rows))


def test_one_type_of_data_per_folder(data_root):
    with pytest.raises(ValueError, match="already the folder of the instrument tga"):
        set_folder("dma", "TGA")
    with pytest.raises(ValueError, match="plain name"):
        set_folder("dma", "../elsewhere")
    with pytest.raises(ValueError, match="Unknown instrument"):
        set_folder("no_such_instrument", "X")


def test_a_lab_reader_of_a_new_type_gets_the_folder_of_its_files(data_root, tmp_path):
    (data_root / "Photometer data").mkdir()
    save_definition(PHOTOMETER, _sample(data_root / "Photometer data" / "kin1.dat"))
    (folder,) = unclaimed_folders()
    assert folder.suggested_type == "absorbance_kinetics"  # by its reader's name, photometer
    assert recognise_files([str(data_root / "Photometer data" / "kin1.dat")]) == {"photometer": 1}

    assert assign_folder("Photometer data", "absorbance_kinetics") == "photometer_data"
    assert reader_for("photometer_data", [str(data_root / "Photometer data" / "kin1.dat")]).name == "photometer"


def test_new_instrument_names_come_from_their_folder(data_root):
    from mfethuls.instruments.configured import name_from_folder

    assert name_from_folder("inSitu_UV", "uv_vis") == "insitu_uv"
    assert name_from_folder("UV Vis (2)", "uv_vis") == "uv_vis_2"
    assert name_from_folder("UV_Vis", "uv_vis") == "uv_vis_uv_vis"  # uv_vis is taken
    assert name_from_folder("((", "dsc") == "dsc_2"  # dsc is taken
