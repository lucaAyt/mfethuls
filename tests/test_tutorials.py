"""The packaged tutorial: copied once (edits are kept) and opened in marimo."""

import sys

import pytest

import mfethuls.tutorials as tutorials


def test_tutorial_is_copied_once_and_edits_are_kept(tmp_path):
    notebook = tutorials.tutorial_copy(tmp_path)
    assert notebook.read_text(encoding="utf-8") == tutorials.TUTORIAL_PATH.read_text(encoding="utf-8")

    notebook.write_text("# my edits", encoding="utf-8")
    assert tutorials.tutorial_copy(tmp_path).read_text(encoding="utf-8") == "# my edits"


def test_open_tutorial_starts_marimo_on_the_copy(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(tutorials.subprocess, "Popen", lambda args, cwd: started.append((args, cwd)))
    monkeypatch.setattr(tutorials.importlib.util, "find_spec", lambda name: object())

    notebook = tutorials.open_tutorial(tmp_path)
    assert started == [([sys.executable, "-m", "marimo", "edit", str(notebook)], tmp_path)]


def test_open_tutorial_says_how_to_install_marimo(tmp_path, monkeypatch):
    monkeypatch.setattr(tutorials.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(tutorials.MarimoMissing, match=r"mfethuls\[notebook\]"):
        tutorials.open_tutorial(tmp_path)
