"""Reconcile: bringing the manifest, catalog and stored datasets back in line with the registry."""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from mfethuls import Registry
from mfethuls.config.loader import ingest_experiment_dataset
from mfethuls.reconcile import ReconcileBlocked, apply, plan
from mfethuls.stores import open_local_stores as open_stores

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A copy of examples/ with every example ingested; returns (data_root, storage_root, registry frame)."""

    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    monkeypatch.setenv("PATH_TO_LOCAL_STORAGE", str(tmp_path / "storage"))
    monkeypatch.delenv("MFETHULS_DUCKDB_PATH", raising=False)
    frame = pd.read_csv(copy / "experiments_registry.csv")
    registry = Registry.from_frame(frame)
    with open_stores() as stores:
        for name in registry.names:
            ingest_experiment_dataset(name, refresh=True, registry=registry, stores=stores)
    return copy / "data", tmp_path / "storage", frame


def _plan(frame, **kwargs):
    with open_stores() as stores:
        return plan(Registry.from_frame(frame), stores, **kwargs)


def _apply(frame, **kwargs):
    registry = Registry.from_frame(frame)
    with open_stores() as stores:
        return apply(plan(registry, stores), registry, stores, **kwargs)


def _state():
    """Catalog rows and manifest entries, by experiment name."""
    with open_stores() as stores:
        catalog = {row["experiment_name"]: row for row in stores.catalog.list_registered()}
        manifest = {entry["experiment_name"]: entry for entry in stores.manifest.all_mappings()}
    return catalog, manifest


def _kinds(current):
    return [(action.kind, action.name) for action in current.actions]


def test_nothing_to_do_after_ingesting_the_registry(lab):
    _, _, frame = lab
    current = _plan(frame)

    assert current.actions == []
    assert current.pending == [] and current.duplicates == []
    assert not current.blocked


def test_removed_row_is_forgotten_everywhere_but_raw_data_stays(lab):
    data_root, storage_root, frame = lab
    catalog, manifest = _state()
    gone = manifest["LB_tga_002"]

    current = _plan(frame[frame["name"] != "LB_tga_002"])
    assert _kinds(current) == [("forget", "LB_tga_002")]
    (action,) = current.actions
    assert action.table_names == [catalog["LB_tga_002"]["table_name"]]
    assert action.paths and all(Path(p).exists() for p in action.paths)

    results = _apply(frame[frame["name"] != "LB_tga_002"])
    catalog, manifest = _state()
    assert [r["status"] for r in results] == ["done"]
    assert "LB_tga_002" not in catalog and "LB_tga_002" not in manifest
    assert not (storage_root / "tga" / gone["experiment_id"]).exists()
    assert (data_root / "TGA" / "poly2.txt").exists()
    assert _plan(frame[frame["name"] != "LB_tga_002"]).actions == []


def test_renamed_experiment_is_refreshed_and_keeps_its_id(lab):
    _, _, frame = lab
    _, manifest = _state()
    renamed = frame.replace({"name": {"LB_dsc_001": "LB_dsc_first"}})

    current = _plan(renamed)
    assert _kinds(current) == [("refresh", "LB_dsc_first")]
    assert "experiment_name" in current.actions[0].reason

    _apply(renamed)
    catalog, _ = _state()
    assert "LB_dsc_001" not in catalog
    assert catalog["LB_dsc_first"]["experiment_id"] == manifest["LB_dsc_001"]["experiment_id"]
    assert _plan(renamed).actions == []


def test_sample_change_refreshes_and_removes_the_old_file(lab):
    _, storage_root, frame = lab
    _, manifest = _state()
    experiment_dir = storage_root / "dsc_mettler_toledo" / manifest["LB_dsc_002"]["experiment_id"]
    old_files = sorted(p.name for p in experiment_dir.iterdir())
    changed = frame.copy()
    changed.loc[changed["name"] == "LB_dsc_002", "sample_id"] = "S009"

    current = _plan(changed)
    assert _kinds(current) == [("refresh", "LB_dsc_002"), ("remove_files", "LB_dsc_002")]
    assert sorted(Path(p).name for p in current.actions[1].paths) == old_files

    _apply(changed)
    new_files = sorted(p.name for p in experiment_dir.iterdir())
    assert new_files and not set(new_files) & set(old_files)
    assert all("S009" in name for name in new_files)
    assert _plan(changed).actions == []


def test_renamed_raw_file_is_relinked_and_keeps_its_id_and_data(lab):
    data_root, storage_root, frame = lab
    _, manifest = _state()
    old = manifest["LB_dsc_002"]
    (data_root / "DSC" / "poly2.txt").rename(data_root / "DSC" / "polymer2.txt")
    moved = frame.copy()
    moved.loc[moved["name"] == "LB_dsc_002", "raw_data_filename"] = "polymer2"

    current = _plan(moved)
    assert _kinds(current) == [("relink", "LB_dsc_002"), ("refresh", "LB_dsc_002")]
    assert current.forgets == 0

    _apply(moved)
    catalog, manifest = _state()
    assert manifest["LB_dsc_002"]["experiment_id"] == old["experiment_id"]
    assert manifest["LB_dsc_002"]["raw_data_filename"] == "polymer2"
    assert catalog["LB_dsc_002"]["raw_data_filename"] == "polymer2"
    assert (storage_root / "dsc_mettler_toledo" / old["experiment_id"]).exists()
    assert _plan(moved).actions == []


def test_forgetting_many_experiments_is_blocked_unless_forced(lab):
    _, _, frame = lab
    partial = frame.head(2)  # e.g. a half-synced registry file

    current = _plan(partial)
    assert current.forgets == len(frame) - 2 and current.blocked
    with pytest.raises(ReconcileBlocked, match="partly synced"):
        _apply(partial)
    _, manifest = _state()
    assert len(manifest) == len(frame)  # nothing was changed

    _apply(partial, force=True)
    _, manifest = _state()
    assert sorted(manifest) == sorted(partial["name"])


def test_invalid_rows_still_protect_their_data(lab):
    _, _, frame = lab
    broken = frame.copy()
    broken.loc[broken["name"] == "LB_dsc_001", "sample_id"] = "not-a-sample"

    assert "LB_dsc_001" not in Registry.from_frame(broken)
    assert _plan(broken).forgets == 0


def test_new_rows_are_pending_and_unknown_stored_data_is_removed(lab):
    data_root, storage_root, frame = lab
    shutil.copyfile(data_root / "DSC" / "poly1.txt", data_root / "DSC" / "poly9.txt")  # raw data: copy bytes, not text
    stray = storage_root / "dsc" / "0123456789ab"
    stray.mkdir(parents=True)
    (stray / "0123456789ab_S001_R001.parquet").write_bytes(b"")
    extra = pd.concat([frame, pd.DataFrame([{"name": "LB_dsc_009", "instrument_name": "dsc_mettler_toledo",
                                             "sample_id": "S009", "raw_data_filename": "poly9"}])])

    current = _plan(extra)
    assert current.pending == ["LB_dsc_009"]
    assert _kinds(current) == [("remove_files", None)]

    _apply(extra)
    assert not stray.exists()


def test_identical_raw_data_is_reported_as_duplicates(lab):
    data_root, _, frame = lab
    shutil.copyfile(data_root / "DSC" / "poly1.txt", data_root / "DSC" / "poly9.txt")  # raw data: copy bytes, not text
    extra = pd.concat([frame, pd.DataFrame([{"name": "LB_dsc_009", "instrument_name": "dsc_mettler_toledo",
                                             "sample_id": "S009", "raw_data_filename": "poly9"}])])
    registry = Registry.from_frame(extra)
    with open_stores() as stores:
        ingest_experiment_dataset("LB_dsc_009", registry=registry, stores=stores)

    assert _plan(extra).duplicates == [["LB_dsc_001", "LB_dsc_009"]]


def test_command_line_shows_the_plan_and_applies_only_when_asked(lab, tmp_path, capsys):
    from mfethuls.reconcile import main

    _, _, frame = lab
    registry_path = tmp_path / "registry.csv"
    frame[frame["name"] != "LB_tga_002"].to_csv(registry_path, index=False)

    assert main(["--registry", str(registry_path)]) == 0
    out = capsys.readouterr().out
    assert "Forget" in out and "LB_tga_002" in out and "--apply" in out
    assert "LB_tga_002" in _state()[1]  # only shown, not changed

    assert main(["--registry", str(registry_path), "--apply"]) == 0
    assert "Applied 1 of 1" in capsys.readouterr().out
    assert "LB_tga_002" not in _state()[1]
