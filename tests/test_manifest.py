"""Tests for the manifest module."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from mfethuls.manifest import (
    FileManifestBackend,
    MANIFEST_FILENAME,
    ManifestError,
    content_hash,
    find_data_files,
    generate_experiment_id,
)


# ── generate_experiment_id ────────────────────────────────────────────────────

def test_generate_experiment_id_is_12_char_hex():
    eid = generate_experiment_id()
    assert len(eid) == 12
    assert all(c in "0123456789abcdef" for c in eid)


def test_generate_experiment_id_is_unique():
    ids = {generate_experiment_id() for _ in range(100)}
    assert len(ids) == 100


# ── FileManifestBackend ───────────────────────────────────────────────────────

def test_file_manifest_creates_entry_on_first_call():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        eid = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="CL_dsc_001",
        )
        assert len(eid) == 12
        manifest_path = os.path.join(tmpdir, MANIFEST_FILENAME)
        assert os.path.exists(manifest_path)
        with open(manifest_path) as fh:
            data = json.load(fh)
        assert len(data["mappings"]) == 1
        assert data["mappings"][0]["experiment_id"] == eid


def test_file_manifest_is_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        eid1 = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="CL_dsc_001",
        )
        eid2 = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="CL_dsc_001",
        )
        assert eid1 == eid2


def test_file_manifest_different_instruments_get_different_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        eid_dsc = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="run_jan15",
            experiment_name="exp_dsc",
        )
        eid_tga = backend.get_or_create_experiment_id(
            instrument_name="tga",
            raw_data_filename="run_jan15",
            experiment_name="exp_tga",
        )
        assert eid_dsc != eid_tga


def test_file_manifest_keeps_the_id_and_records_a_changed_name():
    """The registry decides the name; the ID stays tied to the raw data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        eid = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="original_name",
        )
        renamed = backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="changed_name",
        )
        assert renamed == eid
        (entry,) = backend.all_mappings()
        assert entry["experiment_name"] == "changed_name"


def test_file_manifest_records_content_hash():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="poly1", experiment_name="p1")
        assert backend.all_mappings()[0]["content_hash"] is None

        backend.record_content_hash(instrument_name="dsc", raw_data_filename="poly1", content_hash="abc")
        assert backend.all_mappings()[0]["content_hash"] == "abc"


def test_content_hash_ignores_file_names_but_not_contents():
    with tempfile.TemporaryDirectory() as tmpdir:
        def write(name, text):
            path = os.path.join(tmpdir, name)
            with open(path, "w") as fh:
                fh.write(text)
            return path

        a, b = write("a.txt", "1"), write("b.txt", "2")
        renamed = [write("x.txt", "2"), write("y.txt", "1")]
        assert content_hash([a, b]) == content_hash(renamed)
        assert content_hash([a, b]) != content_hash([a, write("c.txt", "3")])


def test_file_manifest_atomic_write_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="test_run",
            experiment_name="exp_a",
        )
        assert [f for f in os.listdir(tmpdir) if f.endswith(".tmp")] == []


def test_corrupt_manifest_raises_and_is_left_untouched():
    """Starting over would assign new IDs to every experiment, so a broken manifest stops ingest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, MANIFEST_FILENAME)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"mappings": [{"experiment_id": "abc"')  # cut off mid-write

        backend = FileManifestBackend(tmpdir)
        with pytest.raises(ManifestError, match="not valid JSON"):
            backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="x", experiment_name="x")
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == '{"mappings": [{"experiment_id": "abc"'


def test_file_manifest_forget_and_relink():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        keep = backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="a", experiment_name="A")
        gone = backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="b", experiment_name="B")

        assert backend.forget(experiment_id=gone) is True
        assert backend.forget(experiment_id=gone) is False
        backend.relink(experiment_id=keep, raw_data_filename="a_renamed")
        assert backend.get_or_create_experiment_id(
            instrument_name="dsc", raw_data_filename="a_renamed", experiment_name="A"
        ) == keep
        assert [e["experiment_id"] for e in backend.all_mappings()] == [keep]
        with pytest.raises(KeyError):
            backend.relink(experiment_id=gone, raw_data_filename="b")


def test_concurrent_writers_do_not_lose_entries():
    """Without the lock, two read-modify-write cycles overlapping drop one writer's entry."""
    from concurrent.futures import ThreadPoolExecutor

    with tempfile.TemporaryDirectory() as tmpdir:
        def add(i):
            FileManifestBackend(tmpdir).get_or_create_experiment_id(
                instrument_name="dsc", raw_data_filename=f"run{i}", experiment_name=f"run{i}"
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, range(40)))
        assert len(FileManifestBackend(tmpdir).all_mappings()) == 40


def test_file_manifest_roundtrip_survives_new_backend_instance():
    """Simulates a DB reset — new backend reads existing manifest file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        backend1 = FileManifestBackend(tmpdir)
        eid = backend1.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="CL_dsc_001",
        )

        backend2 = FileManifestBackend(tmpdir)
        eid2 = backend2.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="CL_dsc_001",
        )
        assert eid == eid2


# ── find_data_files ───────────────────────────────────────────────────────────

def test_find_data_files_locates_file_in_subfolder():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub = os.path.join(tmpdir, "batch_jan", "chitosan")
        os.makedirs(sub)
        open(os.path.join(sub, "chitosan_jan15.txt"), "w").close()
        open(os.path.join(sub, "chitosan_jan15_notes.txt"), "w").close()

        parent, files = find_data_files(tmpdir, "chitosan_jan15")
        assert parent == sub
        assert any("chitosan_jan15.txt" in f for f in files)


def test_find_data_files_ignores_other_files_in_same_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub = os.path.join(tmpdir, "exp_folder")
        os.makedirs(sub)
        for fname in ["sample.txt", "sample_run2.txt", "sample_notes.csv"]:
            open(os.path.join(sub, fname), "w").close()

        parent, files = find_data_files(tmpdir, "sample")
        assert parent == sub
        assert files == [os.path.join(sub, "sample.txt")]


def test_find_data_files_shared_folder_returns_own_file_only():
    """Several experiments in one folder each get only their own file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in [".gitkeep", "poly1.txt", "poly2.txt"]:
            open(os.path.join(tmpdir, fname), "w").close()

        _, files1 = find_data_files(tmpdir, "poly1")
        _, files2 = find_data_files(tmpdir, "poly2")
        assert files1 == [os.path.join(tmpdir, "poly1.txt")]
        assert files2 == [os.path.join(tmpdir, "poly2.txt")]


def test_find_data_files_collects_all_extensions_for_stem():
    with tempfile.TemporaryDirectory() as tmpdir:
        for fname in ["poly1.txt", "poly1.csv", "poly2.txt"]:
            open(os.path.join(tmpdir, fname), "w").close()

        _, files = find_data_files(tmpdir, "poly1")
        assert {os.path.basename(f) for f in files} == {"poly1.txt", "poly1.csv"}


def test_find_data_files_raises_file_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(FileNotFoundError):
            find_data_files(tmpdir, "nonexistent_file")


def test_find_data_files_raises_on_ambiguous_match():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub1 = os.path.join(tmpdir, "dir1")
        sub2 = os.path.join(tmpdir, "dir2")
        os.makedirs(sub1)
        os.makedirs(sub2)
        open(os.path.join(sub1, "myfile.txt"), "w").close()
        open(os.path.join(sub2, "myfile.txt"), "w").close()

        with pytest.raises(ValueError, match="multiple directories"):
            find_data_files(tmpdir, "myfile")


def test_find_data_files_excludes_parquet_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub = os.path.join(tmpdir, "exp")
        os.makedirs(sub)
        open(os.path.join(sub, "mydata.txt"), "w").close()
        open(os.path.join(sub, "mydata.parquet"), "w").close()

        parent, files = find_data_files(tmpdir, "mydata")
        assert not any(f.endswith(".parquet") for f in files)
        assert any("mydata.txt" in f for f in files)


# ── Directory-name fallback tests ─────────────────────────────────────────────

def test_find_data_files_matches_directory_name():
    """A folder named after raw_data_filename returns all files inside it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        exp_folder = os.path.join(tmpdir, "kinetics_jan15")
        os.makedirs(exp_folder)
        for fname in ["t001.txt", "t002.txt", "t003.txt"]:
            open(os.path.join(exp_folder, fname), "w").close()

        parent, files = find_data_files(tmpdir, "kinetics_jan15")
        assert len(files) == 3
        assert all(os.path.dirname(f) == exp_folder for f in files)
        assert parent == exp_folder


def test_find_data_files_raises_on_file_and_directory():
    """A matching file AND a matching folder elsewhere is ambiguous and raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        open(os.path.join(tmpdir, "sample_A.txt"), "w").close()
        folder = os.path.join(tmpdir, "sample_A")
        os.makedirs(folder)
        open(os.path.join(folder, "meas_001.csv"), "w").close()

        with pytest.raises(ValueError, match="both a file and a directory"):
            find_data_files(tmpdir, "sample_A")


def test_find_data_files_file_inside_its_namesake_folder_is_the_folder():
    """LUB055/LUB055.txt: the name means the folder; the file name means the file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = os.path.join(tmpdir, "LUB055")
        os.makedirs(folder)
        for name in ["LUB055.txt", "LUB055_b.txt"]:
            open(os.path.join(folder, name), "w").close()

        parent, files = find_data_files(tmpdir, "LUB055")
        assert parent == folder
        assert [os.path.basename(f) for f in files] == ["LUB055.txt", "LUB055_b.txt"]

        _, files = find_data_files(tmpdir, "LUB055.txt")
        assert [os.path.basename(f) for f in files] == ["LUB055.txt"]


def test_find_data_files_raises_on_ambiguous_directory():
    """Same directory name in two different locations raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        for parent in ["batch1", "batch2"]:
            folder = os.path.join(tmpdir, parent, "kinetics_jan15")
            os.makedirs(folder)
            open(os.path.join(folder, "data.txt"), "w").close()

        with pytest.raises(ValueError, match="multiple locations"):
            find_data_files(tmpdir, "kinetics_jan15")


def test_find_data_files_raises_when_nothing_found():
    """Unrelated files and directories raise FileNotFoundError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "other_folder"))
        open(os.path.join(tmpdir, "other_file.txt"), "w").close()

        with pytest.raises(FileNotFoundError):
            find_data_files(tmpdir, "kinetics_jan15")


def test_manifest_write_survives_a_briefly_locked_file(monkeypatch):
    """Windows refuses to replace a file another process (virus scanner, OneDrive) has open for a moment."""
    import mfethuls._files as files

    real_replace = os.replace
    failures = {"left": 2}

    def flaky_replace(source, target):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(5, "Access is denied")
        real_replace(source, target)

    monkeypatch.setattr(files.os, "replace", flaky_replace)
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        eid = backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="a", experiment_name="A")
        assert [e["experiment_id"] for e in backend.all_mappings()] == [eid]
        assert failures["left"] == 0

        failures["left"] = 100  # locked for good: give up with the error, leave no temp file behind
        with pytest.raises(PermissionError):
            backend.get_or_create_experiment_id(instrument_name="dsc", raw_data_filename="b", experiment_name="B")
        assert [f for f in os.listdir(tmpdir) if f.endswith(".tmp")] == []


def test_find_data_files_collects_an_experiment_folder_with_its_subfolders(tmp_path):
    """Bruker NMR: EXP014/1/pdata/1/1r. Hidden folders and parquet files stay out."""
    for relative in ["EXP014/1/acqus", "EXP014/1/fid", "EXP014/1/pdata/1/1r", "EXP014/1/pdata/1/procs",
                     "EXP014/.cache/x", "EXP014/1/old.parquet"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    parent, files = find_data_files(str(tmp_path), "EXP014")
    assert parent == str(tmp_path / "EXP014")
    assert sorted(os.path.relpath(f, parent).replace(os.sep, "/") for f in files) == [
        "1/acqus", "1/fid", "1/pdata/1/1r", "1/pdata/1/procs"]


def test_a_series_is_listed_in_numeric_order(tmp_path):
    """One file per spectrum: poly3__2 comes before poly3__10, as it was measured."""
    series = tmp_path / "Fluorescence" / "poly3"
    series.mkdir(parents=True)
    for i in (0, 1, 2, 10, 11, 20):
        (series / f"poly3__{i}__18-11-{i:02d}.txt").write_text("x")
    _, files = find_data_files(str(tmp_path / "Fluorescence"), "poly3")
    assert [os.path.basename(f).split("__")[1] for f in files] == ["0", "1", "2", "10", "11", "20"]


def test_natural_key_compares_numbers_as_numbers():
    from mfethuls.naming import natural_key

    names = ["run10.txt", "Run2.txt", "run1.txt", "run1a.txt"]
    assert sorted(names, key=natural_key) == ["run1.txt", "run1a.txt", "Run2.txt", "run10.txt"]
