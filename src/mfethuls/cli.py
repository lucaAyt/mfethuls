"""``mfethuls`` command: everything the app does, from a terminal or a script.

Each subcommand is a small function over the same core calls the app uses
(``Registry``, ``ingest_experiment_dataset``, ``reconcile``, ``discovery``,
``load_experiments``). Folders come from the saved settings, ``.env`` or the
environment, as in the app; ``--data-folder``, ``--registry`` and ``--storage``
override them for one run.

Exit codes: 0 done, 1 something failed (each failure is printed), 2 not run
(bad arguments, missing settings, or a blocked clean up).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Callable, List, Optional

import pandas as pd

from . import settings as _settings
from .storage.config import _get_package_version


class CommandError(Exception):
    """A problem the user can fix (no folder set, unknown experiment); printed without a traceback."""


# -- helpers --------------------------------------------------------------------------


def _print_table(frame: pd.DataFrame) -> None:
    print(frame.to_string(index=False) if not frame.empty else "(none)")


def _registry():
    from .experiments import Registry

    if not _settings.get_settings().registry_path:
        raise CommandError("No registry set. Run `mfethuls settings --registry PATH` or pass --registry.")
    return Registry.load()


def _require_data_folder() -> str:
    data_root = _settings.get_settings().data_root
    if not data_root:
        raise CommandError("No data folder set. Run `mfethuls settings --data-folder PATH` or pass --data-folder.")
    return data_root


def _unknown(names: List[str], registry) -> None:
    missing = [name for name in names if name not in registry]
    if missing:
        raise CommandError(f"Not in the registry (or skipped as invalid, see `mfethuls validate`): {', '.join(missing)}")


# -- subcommands ------------------------------------------------------------------------


def cmd_settings(args) -> int:
    """Show the folders in use; with options, save them (as Settings in the app does)."""
    values = {"data_root": args.set_data_folder, "registry_path": args.set_registry, "local_storage": args.set_storage}
    given = {name: os.path.abspath(value) for name, value in values.items() if value}
    if given:
        path = _settings.save_settings(**given)
        _settings.configure(None)
        print(f"Saved to {path}")
    current = _settings.get_settings()
    # As storage.config resolves them, without creating the folder.
    storage = current.local_storage or (current.data_root and os.path.join(current.data_root, "_storage"))
    catalog = current.duckdb_path or (storage and os.path.join(storage, "mfethuls.duckdb"))
    print(f"Data folder:    {current.data_root or '(not set)'}")
    print(f"Registry:       {current.registry_path or '(not set)'}")
    print(f"Storage folder: {storage or '(not set)'}")
    print(f"Catalog:        {catalog or '(not set)'}")
    print(f"Settings file:  {_settings.settings_file()}")
    return 0


def cmd_validate(args) -> int:
    """Check every registry row (and, with --check-files, that its raw data is there)."""
    from .experiments import Registry

    _registry()  # the "no registry set" message
    registry = Registry.load(check_data_paths=args.check_files)
    for problem in registry.problems:
        for message in problem.errors:
            print(f"ERROR    {problem.name or '(no name)'}: {message}")
        for message in problem.warnings:
            print(f"warning  {problem.name or '(no name)'}: {message}")
    skipped = sum(problem.skipped for problem in registry.problems)
    print(f"{len(registry.names)} valid rows, {skipped} skipped.")
    return 1 if skipped else 0


def cmd_ingest(args) -> int:
    """Read the raw data of the chosen experiments and store them (cached ones are only registered)."""
    from .config.loader import ingest_experiment_dataset
    from .stores import open_local_stores

    registry = _registry()
    _require_data_folder()
    if args.all:
        names = list(registry.names)
    elif args.instrument:
        wanted = {name.casefold() for name in args.instrument}
        names = [exp.name for exp in registry if (exp.instrument_name or "").casefold() in wanted]
        if not names:
            raise CommandError(f"No valid registry rows use {', '.join(args.instrument)} (see `mfethuls instruments`).")
    else:
        names = args.names
    if not names:
        raise CommandError("Name the experiments to ingest, or use --all or --instrument.")
    _unknown(names, registry)

    failed = 0
    with open_local_stores() as stores:
        for name in names:
            try:
                result = ingest_experiment_dataset(name, refresh=args.refresh, registry=registry, stores=stores) or {}
                status = result.get("status", "unknown")
            except Exception as exc:  # noqa: BLE001 - reported per experiment
                status = f"error: {exc}"
            failed += status.startswith(("error", "failed"))
            print(f"{name}: {status}")
    print(f"{len(names) - failed} of {len(names)} ingested.")
    return 1 if failed else 0


def cmd_list(args) -> int:
    """The ingested datasets in the catalog."""
    from .storage.duckdb_backend import DuckDBQueryBackend

    current = _settings.get_settings()
    if not (current.data_root or current.local_storage or current.duckdb_path):
        raise CommandError("No data folder set, so there is no catalog. Run `mfethuls settings --data-folder PATH`.")
    with DuckDBQueryBackend(read_only=True) as catalog:
        frame = pd.DataFrame(catalog.list_registered())
    columns = ["experiment_name", "instrument_name", "sample_id", "run_id", "rows", "table_name"]
    if args.instrument and not frame.empty:
        frame = frame[frame["instrument_name"].str.casefold().isin({i.casefold() for i in args.instrument})]
    _print_table(frame[columns].fillna("") if not frame.empty else frame)
    return 0


def cmd_discover(args) -> int:
    """Raw data in the data folder that no registry row describes yet."""
    from .discovery import discover_unregistered

    items = discover_unregistered(_registry(), _require_data_folder())
    _print_table(pd.DataFrame([
        {"folder": item.folder_name, "raw_data_filename": item.raw_data_filename, "layout": item.layout,
         "files": len(item.files), "modified": f"{item.modified:%Y-%m-%d %H:%M}", "instruments": ", ".join(item.instruments)}
        for item in items
    ]))
    if items:
        print("\nAdd a registry row for each (the app's Ingest > Register new data drafts them for you).")
    return 0


def cmd_cleanup(args) -> int:
    """Compare what was ingested with the registry; with --apply, bring it in line."""
    from .reconcile import ReconcileBlocked, apply, format_plan, plan
    from .stores import open_local_stores

    registry = _registry()
    _require_data_folder()
    with open_local_stores() as stores:
        current = plan(registry, stores)
        print(format_plan(current))
        if not args.apply:
            if current.actions:
                print("\nNothing was changed. Run again with --apply to carry this out.")
            return 0
        try:
            results = apply(current, registry, stores, force=args.force)
        except ReconcileBlocked as exc:
            print(f"\nNot applied: {exc}")
            return 2
    errors = [r for r in results if r["status"] == "error"]
    print(f"\nApplied {len(results) - len(errors)} of {len(results)} actions.")
    for result in errors:
        print(f"  Failed {result['kind']} of {result['name'] or result['experiment_id']}: {result['error']}")
    return 1 if errors else 0


def cmd_export(args) -> int:
    """Write one experiment's data to a .csv or .parquet file."""
    from .config.loader import load_experiment_dataset

    registry = _registry()
    _unknown([args.name], registry)
    extension = os.path.splitext(args.output)[1].lower()
    if extension not in {".csv", ".parquet"}:
        raise CommandError("The output file must end in .csv or .parquet.")
    dataset = load_experiment_dataset(args.name, registry=registry)
    if dataset is None:
        raise CommandError(f"{args.name} has no instrument, so there is no data to export.")
    if extension == ".csv":
        dataset.data.to_csv(args.output, index=False)
    else:
        dataset.data.to_parquet(args.output, index=False)
    print(f"Wrote {len(dataset.data)} rows to {args.output}")
    return 0


def cmd_plot(args) -> int:
    """Plot experiments together and save the figure (.png, .svg, .pdf, or .html for an interactive one)."""
    from .comparison import load_experiments
    from .plotting.comparison import plot_experiments

    registry = _registry()
    _unknown(args.names, registry)
    extension = os.path.splitext(args.output)[1].lower()
    if extension not in {".png", ".svg", ".pdf", ".html"}:
        raise CommandError("The output file must end in .png, .svg, .pdf or .html.")
    comparison = load_experiments(args.names, registry=registry)
    kwargs = {"mode": args.mode}
    if args.mode == "stacked":
        kwargs["stacked_offset"] = args.offset
    if extension == ".html":
        plot_experiments(comparison, backend="plotly", **kwargs).write_html(args.output)
    else:
        import matplotlib.pyplot as plt

        fig, _ = plot_experiments(comparison, backend="matplotlib", **kwargs)
        fig.savefig(args.output, bbox_inches="tight")
        plt.close(fig)
    print(f"Saved {args.output}")
    return 0


def cmd_instruments(args) -> int:
    """The instruments mfethuls knows, and any of the lab's definitions it could not use."""
    from .instruments.configured import builtin_names, definition_statuses, instrument_entries

    data_root = _settings.get_settings().data_root
    builtin = builtin_names()
    _print_table(pd.DataFrame([
        {"name": entry["name"], "type": entry.get("type"), "model": entry.get("model"),
         "folder": entry.get("folder_name"), "source": "built-in" if entry["name"] in builtin else "lab definition"}
        for entry in instrument_entries(data_root)
    ]))
    problems = [status for status in definition_statuses(data_root) if status.problems or status.warnings]
    for status in problems:
        for message in status.problems:
            print(f"NOT USED {status.source}: {message}")
        for message in status.warnings:
            print(f"warning  {status.source}: {message}")
    return 0


def cmd_app(args) -> int:
    """Start the app (extra arguments go to `streamlit run`)."""
    from .app.launch import main as launch

    return launch(args.streamlit_args)


def cmd_tutorial(args) -> int:
    """Open the Python tutorial notebook in marimo."""
    from .tutorials import main as tutorial

    return tutorial()


# -- parser -----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mfethuls",
        description="From scattered instrument files to analysis-ready data. "
                    "Run `mfethuls COMMAND --help` for the options of a command.",
    )
    parser.add_argument("--version", action="version", version=f"mfethuls {_get_package_version()}")
    parser.add_argument("--data-folder", metavar="PATH", help="Data folder for this run (one subfolder per instrument).")
    parser.add_argument("--registry", metavar="PATH", help="Registry file (.csv or .xlsx) for this run.")
    parser.add_argument("--storage", metavar="PATH", help="Storage folder for this run (default: _storage in the data folder).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show informational log messages.")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    def command(name: str, func: Callable, **kwargs) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=func.__doc__.splitlines()[0], description=func.__doc__, **kwargs)
        sub.set_defaults(func=func)
        return sub

    sub = command("settings", cmd_settings)
    sub.add_argument("--data-folder", dest="set_data_folder", metavar="PATH", help="Save the data folder.")
    sub.add_argument("--registry", dest="set_registry", metavar="PATH", help="Save the registry file.")
    sub.add_argument("--storage", dest="set_storage", metavar="PATH", help="Save the storage folder.")

    sub = command("validate", cmd_validate)
    sub.add_argument("--check-files", action="store_true", help="Also check that each row's raw data is there.")

    sub = command("ingest", cmd_ingest)
    sub.add_argument("names", nargs="*", metavar="NAME", help="Experiment names (the registry's name column).")
    sub.add_argument("--all", action="store_true", help="Every valid registry row.")
    sub.add_argument("--instrument", action="append", metavar="NAME", help="Every row of this instrument (repeatable).")
    sub.add_argument("--refresh", action="store_true", help="Read the raw data again even if it was stored before.")

    sub = command("list", cmd_list)
    sub.add_argument("--instrument", action="append", metavar="NAME", help="Only this instrument (repeatable).")

    command("discover", cmd_discover)

    sub = command("cleanup", cmd_cleanup)
    sub.add_argument("--apply", action="store_true", help="Carry out the plan (default: only show it).")
    sub.add_argument("--force", action="store_true", help="Apply even if it would forget many experiments.")

    sub = command("export", cmd_export)
    sub.add_argument("name", metavar="NAME", help="Experiment name.")
    sub.add_argument("-o", "--output", required=True, help="Output file, .csv or .parquet.")

    sub = command("plot", cmd_plot)
    sub.add_argument("names", nargs="+", metavar="NAME", help="Experiment names.")
    sub.add_argument("-o", "--output", required=True, help="Output file: .png, .svg, .pdf or .html (interactive).")
    sub.add_argument("--mode", choices=["auto", "overlay", "stacked", "facet"], default="auto",
                     help="auto: overlay when the x-axes match, else one panel each. stacked: overlay shifted up.")
    sub.add_argument("--offset", type=float, default=1.0, help="Shift between experiments for --mode stacked.")

    command("instruments", cmd_instruments)

    sub = command("app", cmd_app)
    sub.add_argument("streamlit_args", nargs=argparse.REMAINDER, help="Passed to `streamlit run`.")

    command("tutorial", cmd_tutorial)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # A Windows console may not show every character of a file or folder name: print a "?" instead of failing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    if args.data_folder or args.registry or args.storage:
        _settings.use_folders(
            data_root=args.data_folder and os.path.abspath(args.data_folder),
            registry_path=args.registry and os.path.abspath(args.registry),
            local_storage=args.storage and os.path.abspath(args.storage),
        )
    try:
        return args.func(args)
    except CommandError as exc:
        print(f"mfethuls {args.command}: {exc}", file=sys.stderr)
        return 2
    except ModuleNotFoundError as exc:
        # Plotting and the app need the optional viz extra.
        print(f"mfethuls {args.command} needs {exc.name}, which is not installed. "
              f'Install it with: pip install "mfethuls[viz]"', file=sys.stderr)
        return 2
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"mfethuls {args.command}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
