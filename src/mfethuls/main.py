import os
import logging

import mfethuls.parsers
from mfethuls.config_loader import prepare_instruments, load_experiment_dataset
from mfethuls.experiments import load_experiment_registry


def main():
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
    
    
    # Example: load the template registry shipped with the package.
    registry_path = os.environ.get('MFETHULS_TEST_REGISTRY')

    print(f"Loading experiment registry from: {registry_path}")
    df_registry = load_experiment_registry(registry_path)
    print("Registered experiments:\n", df_registry[["name", "experiment_id", "instrument_name"]])

    # Choose experiments to analyse; here we filter by status when available.
    if "status" in df_registry.columns:
        selected = df_registry[df_registry["status"] == "to_analyse"]["name"].tolist()
    else:
        selected = df_registry["name"].tolist()

    print("Selected experiments:", selected)

    for name in selected:
        print(f"\nLoading dataset for experiment: {name}")
        try:
            ds = load_experiment_dataset(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  Failed to load dataset: {exc!r}")
            continue

        print(f"  Dataset type: {type(ds).__name__}")
        print(f"  experiment_id: {ds.experiment_id}")
        print(f"  data shape: {ds.data.shape}")
        print(f"  metadata keys: {sorted(ds.metadata.keys())}")
        print(f"  data head: {ds.data.head(5)}")


if __name__ == "__main__":
    main()
