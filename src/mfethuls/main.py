import os
import logging
import argparse

import mfethuls.parsers
import mfethuls.factory as factory
from mfethuls.config_loader import load_experiment_dataset
from mfethuls.experiments import load_experiment_registry
from mfethuls.plotting.core import plot_dataset


def _resolve_registry_path(cli_registry_path: str | None, registry_env: str) -> str:
    """Resolve registry path from CLI and environment fallbacks."""

    if cli_registry_path:
        return cli_registry_path

    if registry_env == "test":
        keys = ("MFETHULS_TEST_REGISTRY", "PATH_TO_REGISTRY")
    else:
        keys = ("PATH_TO_REGISTRY", "MFETHULS_TEST_REGISTRY")

    for key in keys:
        value = os.environ.get(key)
        if value:
            return value

    raise ValueError(
        "No registry path provided. Use --registry or set PATH_TO_REGISTRY "
        "(or MFETHULS_TEST_REGISTRY for test/dev)."
    )


def _apply_runtime_env_mode(registry_env: str) -> None:
    """Apply runtime environment overrides for selected mode.

    In ``test`` mode, test-specific variables are promoted to runtime vars so
    data loading, registry selection and storage all point to test resources.
    """

    if registry_env != "test":
        return

    test_data_root = os.environ.get("MFETHULS_TEST_DATA_ROOT")
    if test_data_root:
        os.environ["PATH_TO_DATA"] = test_data_root
        # factory.DATA_ROOT_PATH is initialized at import-time, so keep it aligned.
        factory.DATA_ROOT_PATH = test_data_root

    test_local_storage = os.environ.get("MFETHULS_TEST_LOCAL_STORAGE")
    if test_local_storage:
        os.environ["PATH_TO_LOCAL_STORAGE"] = test_local_storage

    test_registry = os.environ.get("MFETHULS_TEST_REGISTRY")
    if test_registry:
        os.environ["PATH_TO_REGISTRY"] = test_registry

def mainX(argv: list[str] | None = None):
    """Small demo for manual testing of the experiment/Dataset flow.

    This function is intentionally simple and prints shapes / metadata rather
    than performing any heavy analysis. It can be adapted or removed later
    once a more formal CLI is in place.
    """
    # Logging config
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    parser = argparse.ArgumentParser(description="Run mfethuls experiment loading demo")
    parser.add_argument(
        "--registry",
        help="Path to experiment registry CSV/XLSX. Defaults to PATH_TO_REGISTRY then MFETHULS_TEST_REGISTRY.",
    )
    parser.add_argument(
        "--registry-env",
        choices=["path", "test"],
        default="path",
        help=(
            "Choose default registry env source when --registry is not provided: "
            "'path' prioritizes PATH_TO_REGISTRY, 'test' prioritizes MFETHULS_TEST_REGISTRY."
        ),
    )
    parser.add_argument(
        "--status",
        default="to_analyse",
        help="Filter registry by status value (set empty string to disable status filtering).",
    )
    parser.add_argument(
        "--name",
        action="append",
        help="Explicit experiment name(s) to run. Repeatable.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force fresh parse and overwrite local storage cache.",
    )
    parser.add_argument(
        "--no-storage",
        action="store_true",
        help="Disable local storage cache for this run.",
    )
    args = parser.parse_args(argv)

    _apply_runtime_env_mode(args.registry_env)

    registry_path = _resolve_registry_path(args.registry, args.registry_env)

    print(f"Loading experiment registry from: {registry_path}")
    df_registry = load_experiment_registry(registry_path)
    print("Registered experiments:\n", df_registry[["name", "experiment_id", "instrument_name"]])

    if args.name:
        selected = args.name
    elif args.status and "status" in df_registry.columns:
        selected = df_registry[df_registry["status"] == args.status]["name"].tolist()
    else:
        selected = df_registry["name"].tolist()

    print("Selected experiments:", selected)

    for name in selected:
        print(f"\nLoading dataset for experiment: {name}")
        try:
            ds = load_experiment_dataset(
                name,
                use_storage=not args.no_storage,
                refresh=args.refresh,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  Failed to load dataset: {exc!r}")
            continue

        print(f"  Dataset type: {type(ds).__name__}")
        print(f"  experiment_id: {ds.experiment_id}")
        print(f"  data shape: {ds.data.shape}")
        print(f"  metadata keys: {sorted(ds.metadata.keys())}")
        provenance = ds.metadata.get("provenance", {}) if isinstance(ds.metadata, dict) else {}
        if provenance:
            print(f"  mfethuls_version: {provenance.get('mfethuls_version')}")
            print(f"  saved_at_utc: {provenance.get('saved_at_utc')}")
            print(f"  parser_key: {(provenance.get('instrument') or {}).get('parser_key')}")
            print(f"  source_file_count: {(provenance.get('source') or {}).get('source_file_count')}")
        print(f"  data head: {ds.data.head(5)}")

def main():
    """Simple debugging entrypoint"""
    # _apply_runtime_env_mode("test")
    registry_path = os.environ.get('MFETHULS_TEST_REGISTRY')
    df_registry = load_experiment_registry(registry_path)
    ds = load_experiment_dataset('EXP013')
    fig, ax = plot_dataset(ds)

if __name__ == "__main__":
    main()
