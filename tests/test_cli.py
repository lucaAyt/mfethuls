"""Smoke test for the debugging CLI (``python -m mfethuls.main``) on a copy of examples/."""

import shutil
from pathlib import Path

from mfethuls import experiments as experiments_module
from mfethuls.main import main

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_cli_loads_compares_and_saves_plot(tmp_path, monkeypatch, capsys):
    examples = tmp_path / "examples"
    shutil.copytree(EXAMPLES_DIR, examples)
    monkeypatch.setenv("PATH_TO_DATA", str(examples / "data"))
    monkeypatch.setenv("PATH_TO_REGISTRY", str(examples / "experiments_registry.csv"))
    monkeypatch.setattr(experiments_module, "_EXPERIMENT_REGISTRY", {})
    output = tmp_path / "comparison.svg"

    main(["--name", "LB_dsc_001", "--name", "LB_dsc_002", "--plot", "--plot-output", str(output)])

    printed = capsys.readouterr().out
    assert "Registered experiments" in printed
    assert "Loaded comparison set with 2 experiments" in printed
    assert output.exists() and b"<svg" in output.read_bytes()
