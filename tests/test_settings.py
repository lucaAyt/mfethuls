import logging
import os

import pytest

from mfethuls.settings import Settings, configure, get_settings, use_test_env, using


def test_defaults_without_environment():
    settings = Settings.from_env({})

    assert settings.data_root is None
    assert settings.registry_path is None


def test_from_env_parses_values():
    settings = Settings.from_env(
        {
            "PATH_TO_DATA": "/data",
            "PATH_TO_REGISTRY": "/registry.csv",
            "PATH_TO_LOCAL_STORAGE": "/storage",
        }
    )

    assert (settings.data_root, settings.registry_path, settings.local_storage) == (
        "/data",
        "/registry.csv",
        "/storage",
    )


def test_get_settings_follows_the_environment_until_configured(monkeypatch):
    monkeypatch.setenv("PATH_TO_DATA", "/first")
    assert get_settings().data_root == "/first"

    monkeypatch.setenv("PATH_TO_DATA", "/second")
    assert get_settings().data_root == "/second"

    configure(Settings(data_root="/pinned"))
    monkeypatch.setenv("PATH_TO_DATA", "/third")
    assert get_settings().data_root == "/pinned"

    configure(None)
    assert get_settings().data_root == "/third"


def test_using_restores_previous_settings():
    outer = Settings(data_root="/outer")
    configure(outer)

    with using(Settings(data_root="/inner")):
        assert get_settings().data_root == "/inner"

    assert get_settings() == outer.with_defaults()


def test_with_test_paths_reports_missing_variables():
    settings, missing = Settings(data_root="/runtime", registry_path="/runtime.csv").with_test_paths(
        {"MFETHULS_TEST_DATA_ROOT": "/test-data"}
    )

    assert settings.data_root == "/test-data"
    assert settings.registry_path == "/runtime.csv"
    assert missing == ["MFETHULS_TEST_REGISTRY", "MFETHULS_TEST_LOCAL_STORAGE"]


@pytest.fixture
def runtime_paths(monkeypatch):
    for runtime_key in ("PATH_TO_DATA", "PATH_TO_REGISTRY", "PATH_TO_LOCAL_STORAGE"):
        monkeypatch.setenv(runtime_key, f"original_{runtime_key}")
    return monkeypatch


def test_use_test_env_switches_settings_to_test_paths(runtime_paths):
    runtime_paths.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    runtime_paths.setenv("MFETHULS_TEST_REGISTRY", "test/registry.csv")
    runtime_paths.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    use_test_env()

    settings = get_settings()
    assert (settings.data_root, settings.registry_path, settings.local_storage) == (
        "test/data",
        "test/registry.csv",
        "test/storage",
    )
    # The environment itself is left alone.
    assert os.environ["PATH_TO_DATA"] == "original_PATH_TO_DATA"


def test_use_test_env_warns_and_keeps_value_when_test_var_missing(runtime_paths, caplog):
    runtime_paths.setenv("MFETHULS_TEST_DATA_ROOT", "test/data")
    runtime_paths.setenv("MFETHULS_TEST_LOCAL_STORAGE", "test/storage")

    with caplog.at_level(logging.WARNING, logger="mfethuls.settings"):
        use_test_env()

    assert get_settings().data_root == "test/data"
    assert get_settings().registry_path == "original_PATH_TO_REGISTRY"
    assert "MFETHULS_TEST_REGISTRY is not set" in caplog.text


def test_saved_settings_take_precedence_over_the_environment(monkeypatch, tmp_path):
    from mfethuls.settings import load_saved_settings, save_settings

    monkeypatch.setenv("PATH_TO_DATA", "/from-env")
    monkeypatch.setenv("PATH_TO_REGISTRY", "/env-registry.csv")
    assert get_settings().data_root == "/from-env"

    path = save_settings(data_root="/saved-in-app")
    assert path == tmp_path / "settings.json"  # MFETHULS_SETTINGS_FILE from conftest
    assert get_settings().data_root == "/saved-in-app"
    assert get_settings().registry_path == "/env-registry.csv"  # not saved: the environment still applies

    save_settings(data_root=None)
    assert load_saved_settings() == {}
    assert get_settings().data_root == "/from-env"


def test_unreadable_or_unknown_saved_settings(tmp_path):
    from mfethuls.settings import load_saved_settings, save_settings

    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    assert load_saved_settings() == {}
    with pytest.raises(ValueError, match="can be saved"):
        save_settings(api_key="secret")


def test_use_folders_wins_over_saved_settings_for_this_session(monkeypatch, tmp_path):
    from mfethuls.settings import save_settings, use_folders

    save_settings(data_root="/saved", registry_path="/saved.csv")
    use_folders(data_root="/notebook")

    assert get_settings().data_root == "/notebook"
    assert get_settings().registry_path == "/saved.csv"  # not given: unchanged


def test_registry_defaults_to_a_file_in_the_data_folder(tmp_path):
    from mfethuls.settings import DEFAULT_REGISTRY_NAME, use_folders

    with using(Settings(data_root=str(tmp_path))):
        assert get_settings().registry_path == os.path.join(str(tmp_path), DEFAULT_REGISTRY_NAME)
    with using(Settings(data_root=str(tmp_path), registry_path="/elsewhere/list.csv")):
        assert get_settings().registry_path == "/elsewhere/list.csv"
    with using(Settings()):
        assert get_settings().registry_path is None
        # Another data folder brings its own default registry, not the previous folder's.
        with using(Settings(data_root="/first")):
            settings = use_folders(data_root="/second")
            assert settings.registry_path == os.path.join("/second", DEFAULT_REGISTRY_NAME)
            assert get_settings().registry_path == os.path.join("/second", DEFAULT_REGISTRY_NAME)
