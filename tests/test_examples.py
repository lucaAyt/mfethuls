"""The bundled examples and the example workspace used by the app's getting-started page."""

import pandas as pd
import pytest

from mfethuls.examples import DATA_DIR, REGISTRY_PATH, WALKTHROUGH_REGISTERED, create_workspace
from mfethuls.settings import Settings


def test_examples_are_shipped_with_the_package():
    assert REGISTRY_PATH.is_file()
    assert {p.name for p in DATA_DIR.iterdir()} >= {"DSC", "TGA", "FTIR", "Fluorescence"}


def test_walkthrough_workspace_registers_only_some_examples(tmp_path):
    workspace = create_workspace(tmp_path / "example")

    registry = pd.read_csv(workspace.registry_path)
    assert set(registry["instrument_name"]) == set(WALKTHROUGH_REGISTERED)
    assert (workspace.data_root / "FTIR" / "poly1.csv").is_file()  # left to register in the app
    assert not list(workspace.data_root.rglob(".gitkeep"))
    assert workspace.storage.is_dir()


def test_existing_workspace_is_kept_and_fresh_starts_again(tmp_path):
    workspace = create_workspace(tmp_path / "example")
    pd.DataFrame([{"name": "mine", "instrument_name": "dsc"}]).to_csv(workspace.registry_path, index=False)

    assert list(pd.read_csv(create_workspace(tmp_path / "example").registry_path)["name"]) == ["mine"]
    again = create_workspace(tmp_path / "example", fresh=True, register_all=True)
    assert len(pd.read_csv(again.registry_path)) == len(pd.read_csv(REGISTRY_PATH))


def test_fresh_never_deletes_a_folder_that_is_not_a_workspace(tmp_path):
    (tmp_path / "precious.txt").write_text("keep me")

    with pytest.raises(ValueError, match="not an example workspace"):
        create_workspace(tmp_path, fresh=True)
    assert (tmp_path / "precious.txt").exists()


def test_workspace_settings_use_its_own_folders_and_catalog(tmp_path):
    workspace = create_workspace(tmp_path / "example")
    settings = workspace.settings(Settings(data_root="/mine", duckdb_path="/mine/catalog.duckdb"))

    assert settings.data_root == str(workspace.data_root)
    assert settings.registry_path == str(workspace.registry_path)
    assert settings.local_storage == str(workspace.storage)
    assert settings.duckdb_path is None  # the catalog goes in the workspace storage
