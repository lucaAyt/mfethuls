"""Tests for the manifest module."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from mfethuls.manifest import (
    FileManifestBackend,
    MANIFEST_FILENAME,
    find_data_files,
    generate_experiment_id,
    get_manifest_backend,
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


def test_file_manifest_raises_on_experiment_name_mismatch():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="chitosan_jan15",
            experiment_name="original_name",
        )
        with pytest.raises(ValueError, match="experiment_name"):
            backend.get_or_create_experiment_id(
                instrument_name="dsc",
                raw_data_filename="chitosan_jan15",
                experiment_name="changed_name",
            )


def test_file_manifest_atomic_write_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = FileManifestBackend(tmpdir)
        backend.get_or_create_experiment_id(
            instrument_name="dsc",
            raw_data_filename="test_run",
            experiment_name="exp_a",
        )
        tmp_file = os.path.join(tmpdir, MANIFEST_FILENAME + ".tmp")
        assert not os.path.exists(tmp_file)


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


# ── get_manifest_backend factory ─────────────────────────────────────────────

def test_get_manifest_backend_returns_file_backend_when_no_db_url():
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = get_manifest_backend(data_root=tmpdir, db_url=None)
        assert isinstance(backend, FileManifestBackend)


def test_get_manifest_backend_raises_without_data_root_or_db_url():
    with pytest.raises(ValueError):
        get_manifest_backend(data_root=None, db_url=None)


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


def test_find_data_files_collects_all_files_in_same_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        sub = os.path.join(tmpdir, "exp_folder")
        os.makedirs(sub)
        for fname in ["sample.txt", "sample_run2.txt", "sample_notes.csv"]:
            open(os.path.join(sub, fname), "w").close()

        parent, files = find_data_files(tmpdir, "sample")
        assert len(files) == 3
        assert all(os.path.dirname(f) == sub for f in files)


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


def test_find_data_files_combines_file_and_directory():
    """When a matching file AND a matching folder both exist, results are combined."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Anchor file co-located in tmpdir
        open(os.path.join(tmpdir, "sample_A.txt"), "w").close()
        # Subfolder with individual measurements
        folder = os.path.join(tmpdir, "sample_A")
        os.makedirs(folder)
        open(os.path.join(folder, "meas_001.csv"), "w").close()
        open(os.path.join(folder, "meas_002.csv"), "w").close()

        _parent, files = find_data_files(tmpdir, "sample_A")
        basenames = {os.path.basename(f) for f in files}
        assert "sample_A.txt" in basenames
        assert "meas_001.csv" in basenames
        assert "meas_002.csv" in basenames


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
