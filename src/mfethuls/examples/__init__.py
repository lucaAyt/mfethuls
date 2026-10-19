"""Example instrument data shipped with mfethuls: DSC, TGA, FTIR and a fluorescence in-situ series.

``EXAMPLES_DIR`` holds ``data/`` (one folder per instrument) and ``experiments_registry.csv``
(every example registered). :func:`create_workspace` copies them to a folder of their own,
so trying mfethuls never writes into the installed package::

    from mfethuls.examples import create_workspace
    workspace = create_workspace()            # ~/mfethuls-example
    workspace.data_root, workspace.registry_path, workspace.storage
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import pandas as pd

from mfethuls.settings import Settings

EXAMPLES_DIR = Path(__file__).resolve().parent
DATA_DIR = EXAMPLES_DIR / "data"
REGISTRY_PATH = EXAMPLES_DIR / "experiments_registry.csv"
DEFAULT_WORKSPACE = Path.home() / "mfethuls-example"

# Registered when a walkthrough workspace is created; the other examples are left to
# register in the app ("Review & register").
WALKTHROUGH_REGISTERED = ("dsc_mettler_toledo_v1", "tga")


@dataclass(frozen=True)
class ExampleWorkspace:
    """A copy of the examples: raw data, a registry and a storage folder."""

    folder: Path

    @property
    def data_root(self) -> Path:
        return self.folder / "data"

    @property
    def registry_path(self) -> Path:
        return self.folder / "experiments_registry.csv"

    @property
    def storage(self) -> Path:
        return self.folder / "storage"

    def exists(self) -> bool:
        return self.data_root.is_dir() and self.registry_path.is_file()

    def settings(self, base: Settings) -> Settings:
        """``base`` with the data, registry and storage of this workspace (and its own DuckDB catalog)."""
        return replace(
            base,
            data_root=str(self.data_root),
            registry_path=str(self.registry_path),
            local_storage=str(self.storage),
            duckdb_path=None,
        )


def _make_writable_and_retry(function, path, _exc_info) -> None:
    """``shutil.rmtree`` error handler: Windows refuses to delete read-only files and folders."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def create_workspace(
    folder: Optional[Path | str] = None, *, register_all: bool = False, fresh: bool = False
) -> ExampleWorkspace:
    """Copy the examples to ``folder`` (default ``~/mfethuls-example``) and return the workspace.

    An existing workspace is reused as it is, so work done in it is kept; ``fresh=True``
    deletes it and starts again. Without ``register_all`` the registry describes only the
    DSC and TGA examples (see ``WALKTHROUGH_REGISTERED``).
    """

    workspace = ExampleWorkspace(Path(folder) if folder is not None else DEFAULT_WORKSPACE)
    if fresh and workspace.folder.exists():
        if not workspace.exists():
            raise ValueError(f"{workspace.folder} is not an example workspace; not deleting it.")
        shutil.rmtree(workspace.folder, onerror=_make_writable_and_retry)
    if workspace.exists():
        return workspace

    workspace.folder.mkdir(parents=True, exist_ok=True)
    # Copy contents only (not permissions): the installed files can be read-only, the copies must not be.
    shutil.copytree(DATA_DIR, workspace.data_root, ignore=shutil.ignore_patterns(".gitkeep"),
                    copy_function=shutil.copyfile, dirs_exist_ok=True)
    for directory in [workspace.data_root, *(p for p in workspace.data_root.rglob("*") if p.is_dir())]:
        directory.chmod(directory.stat().st_mode | stat.S_IWRITE)
    registry = pd.read_csv(REGISTRY_PATH)
    if not register_all:
        registry = registry[registry["instrument_name"].isin(WALKTHROUGH_REGISTERED)]
    registry.to_csv(workspace.registry_path, index=False)
    workspace.storage.mkdir(exist_ok=True)
    return workspace
