"""Experiment identity: raw data names ignore case, IDs come from their key, renamed data keeps its ID,
and names that would share a catalog table are refused."""

import json
import shutil

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.discovery import discover_unregistered
from mfethuls.examples import EXAMPLES_DIR
from mfethuls.manifest import (
    MANIFEST_FILENAME,
    FileManifestBackend,
    find_data_files,
    generate_experiment_id,
)
from mfethuls.reconcile import _key, plan
from mfethuls.registry_validator import validate_registry_dataframe
from mfethuls.stores import open_local_stores


def _errors(rows):
    results = validate_registry_dataframe(pd.DataFrame(rows))["rows"]
    return [" | ".join(e["message"] for e in r["errors"]) for r in results]


# --- raw data names ignore case -------------------------------------------------------------------

def test_files_are_found_whatever_the_case_of_the_registry_name(tmp_path):
    (tmp_path / "LUB446.txt").write_text("x", encoding="utf8")
    (tmp_path / "Series01").mkdir()
    (tmp_path / "Series01" / "a.txt").write_text("x", encoding="utf8")
    assert [p.split("\\")[-1].split("/")[-1] for p in find_data_files(str(tmp_path), "lub446")[1]] == ["LUB446.txt"]
    assert find_data_files(str(tmp_path), "lub446.TXT")[1][0].endswith("LUB446.txt")
    assert find_data_files(str(tmp_path), "SERIES01")[1][0].endswith("a.txt")


def test_names_differing_only_in_case_are_ambiguous(tmp_path, monkeypatch):
    import mfethuls.manifest as manifest

    # Windows cannot hold both files in one folder; walk a fake listing like a Linux server.
    monkeypatch.setattr(manifest.os, "walk", lambda _: iter([(str(tmp_path), [], ["LUB446.txt", "lub446.txt"])]))
    with pytest.raises(ValueError, match="differ only in case"):
        find_data_files(str(tmp_path), "LUB446")


def test_the_manifest_key_ignores_the_case_of_the_raw_data_name(tmp_path):
    manifest = FileManifestBackend(str(tmp_path))
    first = manifest.get_or_create_experiment_id(instrument_name="tga", raw_data_filename="LUB446",
                                                 experiment_name="LUB446")
    again = manifest.get_or_create_experiment_id(instrument_name="tga", raw_data_filename="lub446",
                                                 experiment_name="lub446")
    assert first == again and len(manifest.all_mappings()) == 1
    assert _key("TGA", "LUB446") == _key("tga", "lub446")


def test_data_registered_in_another_case_is_not_proposed_again(tmp_path):
    (tmp_path / "TGA").mkdir()
    (tmp_path / "TGA" / "LUB446.txt").write_text("x", encoding="utf8")
    registry = Registry.from_frame(pd.DataFrame([{"name": "lub446", "instrument_name": "tga"}]))
    assert [i.raw_data_filename for i in discover_unregistered(registry, str(tmp_path)) if i.folder_name == "TGA"] == []


def test_the_registry_refuses_raw_data_used_twice_in_another_case():
    errors = _errors([{"name": "a", "instrument_name": "tga", "raw_data_filename": "LUB446"},
                      {"name": "b", "instrument_name": "tga", "raw_data_filename": "lub446"}])
    assert all("used by more than one tga row" in e for e in errors)


# --- names that would share a catalog table -------------------------------------------------------

@pytest.mark.parametrize("first, second", [("PEG-1", "PEG_1"), ("LUB446", "lub446"), ("a b", "a_b")])
def test_names_sharing_a_table_name_are_refused(first, second):
    errors = _errors([{"name": first, "instrument_name": "tga"}, {"name": second, "instrument_name": "tga"}])
    assert all("would share the table name" in e for e in errors), errors


def test_names_with_their_own_table_name_are_accepted():
    assert _errors([{"name": "PEG-1", "instrument_name": "tga"}, {"name": "PEG-2", "instrument_name": "tga"}]) == ["", ""]


# --- IDs from their key -----------------------------------------------------------------------------

def test_ids_are_derived_from_the_key(tmp_path):
    a, b = FileManifestBackend(str(tmp_path / "pc_a")), FileManifestBackend(str(tmp_path / "pc_b"))
    (tmp_path / "pc_a").mkdir()
    (tmp_path / "pc_b").mkdir()
    ids = [m.get_or_create_experiment_id(instrument_name="tga", raw_data_filename="LUB446", experiment_name="x")
           for m in (a, b)]
    assert ids[0] == ids[1] == generate_experiment_id("tga", "lub446")  # two machines, one ID
    assert generate_experiment_id("tga", "LUB447") != ids[0]
    assert generate_experiment_id("dsc", "LUB446") != ids[0]
    assert len(generate_experiment_id()) == 12 and generate_experiment_id() != generate_experiment_id()


def test_a_taken_id_gives_the_next_one_for_that_key(tmp_path):
    taken = generate_experiment_id("tga", "LUB446")
    (tmp_path / MANIFEST_FILENAME).write_text(json.dumps({"version": "1.0", "mappings": [
        {"instrument_name": "tga", "raw_data_filename": "renamed", "experiment_id": taken}]}), encoding="utf8")
    new = FileManifestBackend(str(tmp_path)).get_or_create_experiment_id(
        instrument_name="tga", raw_data_filename="LUB446", experiment_name="LUB446")
    assert new == generate_experiment_id("tga", "LUB446", attempt=1) != taken


def test_conflict_copies_of_a_synced_manifest_are_merged(tmp_path):
    manifest = FileManifestBackend(str(tmp_path))
    mine = manifest.get_or_create_experiment_id(instrument_name="tga", raw_data_filename="A", experiment_name="A")
    copy = tmp_path / ".mfethuls_manifest-PC-B.json"
    copy.write_text(json.dumps({"version": "1.0", "mappings": [
        {"instrument_name": "tga", "raw_data_filename": "A", "experiment_id": "ffffffffffff"},  # disagrees: main wins
        {"instrument_name": "tga", "raw_data_filename": "B", "experiment_id": generate_experiment_id("tga", "B"),
         "content_hash": "h"},
    ]}), encoding="utf8")

    by_name = {e["raw_data_filename"]: e for e in manifest.all_mappings()}  # reading merges, changes nothing
    assert by_name["A"]["experiment_id"] == mine and by_name["B"]["content_hash"] == "h" and copy.exists()

    manifest.get_or_create_experiment_id(instrument_name="tga", raw_data_filename="C", experiment_name="C")
    assert not copy.exists() and (tmp_path / (copy.name + ".merged")).exists()  # kept, not deleted
    saved = json.loads((tmp_path / MANIFEST_FILENAME).read_text(encoding="utf8"))
    assert sorted(e["raw_data_filename"] for e in saved["mappings"]) == ["A", "B", "C"]


# --- renamed raw data keeps its ID at ingest ------------------------------------------------------

def test_renamed_raw_data_keeps_its_id_when_ingested_before_clean_up(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    frame = pd.read_csv(copy / "experiments_registry.csv")
    registry = Registry.from_frame(frame)
    with open_local_stores() as stores:
        ingest_experiment_dataset("LB_tga_001", registry=registry, stores=stores)
        before = {e["raw_data_filename"]: e["experiment_id"] for e in stores.manifest.all_mappings()
                  if e["instrument_name"] == "tga"}

        (copy / "data" / "TGA" / "poly1.txt").rename(copy / "data" / "TGA" / "polymer_one.txt")
        frame.loc[frame["name"] == "LB_tga_001", "raw_data_filename"] = "polymer_one"
        renamed = Registry.from_frame(frame)
        result = ingest_experiment_dataset("LB_tga_001", registry=renamed, stores=stores)

        entries = {e["raw_data_filename"]: e["experiment_id"] for e in stores.manifest.all_mappings()
                   if e["instrument_name"] == "tga"}
        assert entries["polymer_one"] == before["poly1"] and "poly1" not in entries
        assert result["status"] == "registered"  # its stored data was reused, not parsed again
        assert [a.kind for a in plan(renamed, stores).actions if a.name == "LB_tga_001"] == []


def test_new_raw_data_with_the_content_of_a_registered_experiment_gets_its_own_id(tmp_path, monkeypatch):
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    frame = pd.read_csv(copy / "experiments_registry.csv")
    shutil.copy(copy / "data" / "TGA" / "poly1.txt", copy / "data" / "TGA" / "poly1_copy.txt")
    row = frame[frame["name"] == "LB_tga_001"].assign(name="LB_tga_copy", raw_data_filename="poly1_copy",
                                                       sample_id="S009")
    registry = Registry.from_frame(pd.concat([frame, row], ignore_index=True))
    with open_local_stores() as stores:
        ingest_experiment_dataset("LB_tga_001", registry=registry, stores=stores)
        ingest_experiment_dataset("LB_tga_copy", registry=registry, stores=stores)  # LB_tga_001 is still registered
        ids = {e["raw_data_filename"]: e["experiment_id"] for e in stores.manifest.all_mappings()}
        assert ids["poly1"] != ids["poly1_copy"]


def test_a_registry_without_raw_data_filename_keeps_identical_experiments_apart(tmp_path, monkeypatch):
    # Rows named after their files and no raw_data_filename column, like many lab registries;
    # two experiments with identical raw data (the real-data NMR case EXP014 / EXP015).
    data = tmp_path / "data"
    (data / "TGA").mkdir(parents=True)
    shutil.copy(EXAMPLES_DIR / "data" / "TGA" / "poly1.txt", data / "TGA" / "EXP014.txt")
    shutil.copy(EXAMPLES_DIR / "data" / "TGA" / "poly1.txt", data / "TGA" / "EXP015.txt")
    monkeypatch.setenv("PATH_TO_DATA", str(data))
    registry = Registry.from_frame(pd.DataFrame([{"name": "EXP014", "instrument_name": "TGA", "sample_id": "S004"},
                                                 {"name": "EXP015", "instrument_name": "TGA", "sample_id": "S003"}]))
    with open_local_stores() as stores:
        for name in ("EXP014", "EXP015"):
            ingest_experiment_dataset(name, registry=registry, stores=stores)
        ids = {e["raw_data_filename"]: e["experiment_id"] for e in stores.manifest.all_mappings()}
        assert set(ids) == {"EXP014", "EXP015"} and ids["EXP014"] != ids["EXP015"]
        current = plan(registry, stores)
        assert [a.kind for a in current.actions] == []
        assert current.duplicates == [["EXP014", "EXP015"]]
