"""Tutorials that ship with mfethuls, as marimo notebooks.

``local_tutorial.py`` walks through registry, loading, comparing and plotting on a copy
of the example data in ``~/mfethuls-tutorial``. :func:`open_tutorial` (or the
``mfethuls-tutorial`` command) copies it there and opens it in marimo, so it can be
edited without touching the installed package.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

TUTORIAL_PATH = Path(__file__).resolve().with_name("local_tutorial.py")
TUTORIAL_WORKSPACE = Path.home() / "mfethuls-tutorial"


class MarimoMissing(RuntimeError):
    """marimo, which the tutorials need, is not installed."""


def tutorial_copy(folder: Optional[Path] = None) -> Path:
    """Copy the tutorial notebook into ``folder`` (default ``~/mfethuls-tutorial``) once; return its path."""
    folder = Path(folder) if folder is not None else TUTORIAL_WORKSPACE
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / TUTORIAL_PATH.name
    if not target.exists():  # keep the user's edits
        shutil.copyfile(TUTORIAL_PATH, target)
    return target


def open_tutorial(folder: Optional[Path] = None) -> Path:
    """Open the tutorial in marimo (a new browser tab) without waiting for it; returns the notebook path."""
    if importlib.util.find_spec("marimo") is None:
        raise MarimoMissing('The tutorial runs in marimo. Install it with: pip install "mfethuls[notebook]"')
    notebook = tutorial_copy(folder)
    subprocess.Popen([sys.executable, "-m", "marimo", "edit", str(notebook)], cwd=notebook.parent)
    return notebook


def main() -> int:
    """``mfethuls-tutorial``: open the tutorial in marimo."""
    try:
        notebook = open_tutorial()
    except MarimoMissing as exc:
        print(exc)
        return 1
    print(f"Opening {notebook} in marimo…")
    return 0
