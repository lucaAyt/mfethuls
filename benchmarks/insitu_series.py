"""Benchmark a long in-situ UV-Vis series: ingest, load, and what the app draws (not run in CI).

Builds a synthetic series in a temporary folder from the public Flame example: ``N`` spectra of
1,044 points, one second apart (1,500 spectra = 1.57 M rows, like a long kinetics run). Then times:

- ingest (read every file, store), and loading the stored dataset;
- the app's data in memory (text columns as categories, as the page keeps them);
- the line plot coloured by time (an even spread of the spectra), a single line through every
  point (thinned for the screen), and the heatmap: build time and the size of the figure the
  browser receives.

It never reads ``.env`` or the app's saved settings::

    python benchmarks/insitu_series.py            # 1,500 spectra
    python benchmarks/insitu_series.py 300 --keep # 300 spectra, keep the folder (path printed)
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path


def _timed(label: str, fn):
    start = time.perf_counter()
    result = fn()
    print(f"  {label:44s} {time.perf_counter() - start:7.2f} s")
    return result


def _make_series(root: Path, count: int) -> None:
    from mfethuls.examples import DATA_DIR

    sample = sorted((DATA_DIR / "Fluorescence" / "poly3").glob("*.txt"))[0].read_text(encoding="utf-8")
    start = datetime(2025, 5, 11, 18, 11, 9)
    series = root / "data" / "UV_Vis" / "EXPBIG"
    series.mkdir(parents=True)
    for i in range(count):
        moment = start + timedelta(seconds=i)
        text = sample.replace("Date: Sun May 11 18:11:09 CEST 2025",
                              f"Date: {moment:%a %b %d %H:%M:%S} CEST {moment:%Y}")
        (series / f"EXPBIG__{i}__{moment:%H-%M-%S}-000.txt").write_text(text, encoding="utf-8")
    (root / "registry.csv").write_text("name,instrument_name,raw_data_filename\nEXPBIG,uv_vis,EXPBIG\n",
                                       encoding="utf-8")
    (root / "storage").mkdir()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spectra", nargs="?", type=int, default=1500)
    parser.add_argument("--keep", action="store_true", help="keep the temporary data folder")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="mfethuls-bench-"))
    os.environ.update({"MFETHULS_SETTINGS_FILE": str(root / "settings.json"), "PATH_TO_DATA": str(root / "data"),
                       "PATH_TO_REGISTRY": str(root / "registry.csv"), "PATH_TO_LOCAL_STORAGE": str(root / "storage"),
                       "MFETHULS_DUCKDB_PATH": str(root / "storage" / "catalog.duckdb")})
    from mfethuls import settings

    settings.disable_dotenv()
    settings.configure(None)
    try:
        _run(root, args.spectra)
    finally:
        if args.keep:
            print(f"kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


def _run(root: Path, count: int) -> None:
    import pandas as pd

    from mfethuls.config.loader import ingest_experiment_dataset, load_experiment_dataset
    from mfethuls.plotting.backend import render
    from mfethuls.plotting.heatmap import heatmap_grid, plotly_heatmaps
    from mfethuls.plotting.spec import Panel, PlotSpec, Trace
    from mfethuls.plotting.thin import spread_values, thin_spec
    from mfethuls.stores import open_local_stores

    print(f"{count:,} spectra in {root}")
    _make_series(root, count)
    with open_local_stores() as stores:
        _timed("ingest", lambda: ingest_experiment_dataset("EXPBIG", refresh=True, stores=stores))
    data = _timed("load from storage", lambda: load_experiment_dataset("EXPBIG")).data
    print(f"  {len(data):,} rows, {data.memory_usage(deep=True).sum() / 1e6:.0f} MB as loaded")
    try:
        from mfethuls.app.page import compact_text
    except ImportError:  # without the app extra
        compact_text = None
    if compact_text is not None:
        data = _timed("text columns as categories (the app's copy)", lambda: compact_text(data.copy()))
        print(f"  {data.memory_usage(deep=True).sum() / 1e6:.0f} MB in the app")

    def sent(label, fig):
        size = len(_timed(f"{label}: figure to JSON", fig.to_json)) / 1e6
        print(f"  {'':44s} {size:7.1f} MB sent to the browser")

    # Colour by time: an even spread of the spectra on the colour scale.
    def coloured():
        shown = spread_values(data["time_s"])
        subset = data[data["time_s"].isin(shown)]
        traces = [Trace(rows["wavelength_nm"].to_numpy(), rows["transmittance_pct"].to_numpy(), color_value=t)
                  for t, rows in subset.groupby("time_s", observed=True)]
        return thin_spec(PlotSpec([Panel(traces=traces)]))[0]

    sent("spectra coloured by time", render(_timed("spectra coloured by time: spec", coloured), backend="plotly"))
    # One line through every point: thinned above 300,000 points.
    one = PlotSpec([Panel(traces=[Trace(data["wavelength_nm"].to_numpy(), data["transmittance_pct"].to_numpy())])])
    thinned, shown, total = _timed("one line, every point: thin", lambda: thin_spec(one))
    print(f"  {'':44s} {shown:,} of {total:,} points")
    sent("one line", render(thinned, backend="plotly"))
    grid = _timed("heatmap: grid", lambda: heatmap_grid(data, x="wavelength_nm", value="transmittance_pct",
                                                       rows="time_s"))
    print(f"  {'':44s} {grid.z.shape[0]} x {grid.z.shape[1]} cells")
    sent("heatmap", plotly_heatmaps([grid]))
    pd.set_option("display.width", 120)


if __name__ == "__main__":
    main()
