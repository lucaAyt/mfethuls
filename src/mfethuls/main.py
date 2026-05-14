import os
import logging
import argparse

import matplotlib.pyplot as plt

import mfethuls.parsers
import mfethuls.factory as factory
from mfethuls import load_experiments, plot_experiments
from mfethuls.experiments import load_experiment_registry
from mfethuls.storage import get_postgres_db_url


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
        "--experiment",
        "--name",
        dest="experiments",
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
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Render a comparison plot for the selected experiments.",
    )
    parser.add_argument(
        "--plot-mode",
        choices=["auto", "overlay", "stacked", "facet"],
        default="auto",
        help="Plot mode to use when --plot is enabled.",
    )
    parser.add_argument(
        "--plot-output",
        help="Optional path to save the plot instead of only creating it in memory.",
    )
    parser.add_argument(
        "--commit-to-db",
        action="store_true",
        help="Register dataset metadata in Postgres. Uses MFETHULS_POSTGRES_URL from .env, or --db-url if provided.",
    )
    parser.add_argument(
        "--db-url",
        help="Postgres database URL (overrides .env). Format: 'postgresql://user:pass@host/dbname'.",
    )

    args = parser.parse_args(argv)

    _apply_runtime_env_mode(args.registry_env)

    df_registry = load_experiment_registry(args.registry)
    print("Loading experiment registry from configured environment/path defaults")
    print("Registered experiments:\n", df_registry[["name", "experiment_id", "instrument_name"]])

    if args.experiments:
        selected = args.experiments
    elif args.status and "status" in df_registry.columns:
        selected = df_registry[df_registry["status"] == args.status]["name"].tolist()
    else:
        selected = df_registry["name"].tolist()

    print("Selected experiments:", selected)

    # Determine database URL: CLI flags override .env config
    db_url = None

    # First, try loading from .env (MFETHULS_POSTGRES_ENABLED + MFETHULS_POSTGRES_URL)
    env_db_url = get_postgres_db_url()

    # CLI flags can override or disable .env config
    if args.commit_to_db:
        # User explicitly requested DB registration via CLI
        if args.db_url:
            db_url = args.db_url
        elif env_db_url:
            db_url = env_db_url
        else:
            print("ERROR: --commit-to-db requires either --db-url CLI flag or MFETHULS_POSTGRES_URL in .env")
            return
    elif env_db_url:
        # Use .env config if not explicitly disabled
        db_url = env_db_url

    try:
        comparison = load_experiments(
            selected,
            use_storage=not args.no_storage,
            refresh=args.refresh,
            db_url=db_url,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  Failed to load experiments: {exc!r}")
        return

    print(f"Loaded comparison set with {len(comparison.datasets)} experiments")
    print("Comparison labels:", comparison.labels)

    families = []
    for dataset in comparison.datasets:
        metadata = dataset.metadata if isinstance(dataset.metadata, dict) else {}
        instrument_type = metadata.get("instrument_type") or "unknown"
        registry_profile = metadata.get("registry_measurement_profile") or "-"
        canonical_profile = metadata.get("measurement_profile") or "-"
        families.append((instrument_type, registry_profile, canonical_profile))

    print("Experiment families / profiles:")
    print("  (instrument_type / registry_measurement_profile -> canonical_measurement_profile)")
    for label, (family, raw_profile, canonical_profile) in zip(comparison.labels, families):
        profile_str = f"{raw_profile} -> {canonical_profile}" if raw_profile != canonical_profile else canonical_profile
        print(f"  - {label}: {family} / {profile_str}")

    combined = comparison.to_dataframe()
    print(f"Combined dataframe shape: {combined.shape}")
    print(f"Combined dataframe columns: {list(combined.columns)}")
    print(f"Combined dataframe head:\n{combined.head(5)}")

    if args.plot:
        fig, ax = plot_experiments(comparison, mode=args.plot_mode)
        if args.plot_output:
            fig.savefig(args.plot_output, bbox_inches="tight")
            print(f"Saved comparison plot to: {args.plot_output}")
        else:
            print("Created comparison plot in memory. Use --plot-output to save it.")
        plt.close(fig)

def main(argv: list[str] | None = None):
    """Simple debugging entrypoint."""

    mainX(argv)

if __name__ == "__main__":
    main()
