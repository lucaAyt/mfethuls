"""The ``mfethuls`` command, on a copy of examples/."""

import json
import shutil

import pandas as pd
import pytest

from mfethuls.cli import main
from mfethuls.examples import EXAMPLES_DIR


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A copy of examples/ set through the environment; returns (data folder, registry path)."""
    copy = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, copy)
    monkeypatch.setenv("PATH_TO_DATA", str(copy / "data"))
    monkeypatch.setenv("PATH_TO_REGISTRY", str(copy / "experiments_registry.csv"))
    return copy / "data", copy / "experiments_registry.csv"


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "ingest" in capsys.readouterr().out


def test_missing_registry_is_a_message_not_a_traceback(capsys):
    assert main(["ingest", "--all"]) == 2
    assert "No registry set" in capsys.readouterr().err


def test_settings_saves_the_folders_the_app_uses(tmp_path, capsys):
    data = tmp_path / "lab"
    data.mkdir()
    assert main(["settings", "--data-folder", str(data), "--registry", str(tmp_path / "r.csv")]) == 0
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["data_root"] == str(data)
    assert f"Data folder:    {data}" in capsys.readouterr().out
    assert not (data / "_storage").exists()  # showing settings creates nothing


def test_validate_ingest_list_export_and_plot(lab, tmp_path, capsys):
    assert main(["validate"]) == 0
    assert "valid rows, 0 skipped" in capsys.readouterr().out

    assert main(["ingest", "LB_dsc_001", "LB_dsc_002"]) == 0
    out = capsys.readouterr().out
    assert "LB_dsc_001: persisted" in out and "2 of 2 ingested" in out

    assert main(["list"]) == 0
    assert "LB_dsc_002" in capsys.readouterr().out

    csv = tmp_path / "dsc.csv"
    assert main(["export", "LB_dsc_001", "-o", str(csv)]) == 0
    assert len(pd.read_csv(csv)) > 0

    svg, html = tmp_path / "dsc.svg", tmp_path / "dsc.html"
    assert main(["plot", "LB_dsc_001", "LB_dsc_002", "-o", str(svg)]) == 0
    assert b"<svg" in svg.read_bytes()
    assert main(["plot", "LB_dsc_001", "--mode", "stacked", "-o", str(html)]) == 0
    assert "plotly" in html.read_text(encoding="utf8").lower()


def test_unknown_experiment_is_refused(lab, capsys):
    assert main(["ingest", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_folders_given_for_one_run_override_the_environment(lab, tmp_path, capsys, monkeypatch):
    data, registry = lab
    monkeypatch.setenv("PATH_TO_REGISTRY", str(tmp_path / "missing.csv"))
    assert main(["--registry", str(registry), "validate"]) == 0


def test_cleanup_shows_the_plan_and_applies_only_when_asked(lab, tmp_path, capsys):
    _, registry = lab
    assert main(["ingest", "--instrument", "tga"]) == 0
    frame = pd.read_csv(registry)
    smaller = tmp_path / "smaller.csv"
    frame[frame["name"] != "LB_tga_002"].to_csv(smaller, index=False)
    capsys.readouterr()

    assert main(["--registry", str(smaller), "cleanup"]) == 0
    out = capsys.readouterr().out
    assert "Forget" in out and "LB_tga_002" in out and "--apply" in out

    assert main(["--registry", str(smaller), "cleanup", "--apply"]) == 0
    assert "Applied" in capsys.readouterr().out
    assert main(["list"]) == 0
    assert "LB_tga_002" not in capsys.readouterr().out


def test_discover_and_instruments(lab, tmp_path, capsys):
    data, registry = lab
    (data / "DSC" / "new_run.txt").write_bytes((data / "DSC" / "poly1.txt").read_bytes())
    assert main(["discover"]) == 0
    assert "new_run" in capsys.readouterr().out

    assert main(["instruments"]) == 0
    out = capsys.readouterr().out
    assert "dsc_mettler_toledo_v1" in out and "built-in" in out


def test_a_missing_optional_package_names_the_extra(lab, tmp_path, capsys, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_matplotlib(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_matplotlib)
    assert main(["plot", "LB_dsc_001", "-o", str(tmp_path / "d.png")]) == 2
    assert 'pip install "mfethuls[viz]"' in capsys.readouterr().err


def test_ingest_all_walks_each_instrument_folder_once(lab, monkeypatch):
    import os
    from collections import Counter

    data, _ = lab
    real_walk = os.walk
    walks = Counter()

    def counting_walk(top, *args, **kwargs):
        walks[os.path.normcase(os.path.abspath(top))] += 1
        return real_walk(top, *args, **kwargs)

    monkeypatch.setattr(os, "walk", counting_walk)
    assert main(["ingest", "--all"]) == 0
    folders = {os.path.normcase(str(p)) for p in data.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))}
    assert folders and all(walks[folder] == 1 for folder in folders), walks
