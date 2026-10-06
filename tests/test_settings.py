from mfethuls.settings import Settings, configure, get_settings, using


def test_defaults_without_environment():
    settings = Settings.from_env({})

    assert settings.mode == "local"
    assert settings.data_root is None
    assert settings.registry_path is None
    assert settings.disable_storage is False
    assert settings.api_url == "http://localhost:8000"
    assert settings.job_timeout_s == 1800
    assert settings.postgres.enabled is False
    assert settings.postgres.host == "localhost"


def test_from_env_parses_values():
    settings = Settings.from_env(
        {
            "MFETHULS_MODE": "Server",
            "PATH_TO_DATA": "/data",
            "PATH_TO_REGISTRY": "/registry.csv",
            "PATH_TO_STORAGE": "/storage",
            "MFETHULS_DISABLE_STORAGE": "yes",
            "MFETHULS_JOB_TIMEOUT_SECONDS": "60",
            "MFETHULS_POSTGRES_ENABLED": "true",
            "MFETHULS_POSTGRES_USER": "lab",
            "MFETHULS_S3_BUCKET": "bucket",
            "DSC_FOLDER_NAME": "Calorimetry",
        }
    )

    assert settings.mode == "service"
    assert settings.is_service_mode
    assert (settings.data_root, settings.registry_path, settings.local_storage) == (
        "/data",
        "/registry.csv",
        "/storage",
    )
    assert settings.disable_storage is True
    assert settings.job_timeout_s == 60
    assert settings.postgres.enabled is True
    assert settings.postgres.user == "lab"
    assert settings.s3.bucket == "bucket"
    assert settings.instrument_folders == {"dsc": "Calorimetry"}


def test_local_storage_prefers_path_to_local_storage():
    settings = Settings.from_env({"PATH_TO_LOCAL_STORAGE": "/a", "PATH_TO_STORAGE": "/b"})

    assert settings.local_storage == "/a"


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

    assert get_settings() is outer


def test_with_test_paths_reports_missing_variables():
    settings, missing = Settings(data_root="/runtime", registry_path="/runtime.csv").with_test_paths(
        {"MFETHULS_TEST_DATA_ROOT": "/test-data"}
    )

    assert settings.data_root == "/test-data"
    assert settings.registry_path == "/runtime.csv"
    assert missing == ["MFETHULS_TEST_REGISTRY", "MFETHULS_TEST_LOCAL_STORAGE"]
