from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

# Added when an experiment has several files (a series or titration): the stem of
# the file each row came from, so the spectra or curves stay apart after combining.
SOURCE_FILE_COLUMN = "source_file"


class ParseError(ValueError):
    """Raw data files could not be read as the chosen instrument's data."""


def collect_dataframe_from_paths(
    dict_paths,
    *,
    file_extension: str,
    parse_raw: Callable[[str], pd.DataFrame],
    logger,
    parser_label: str,
    passthrough_extensions: Iterable[str] = (".parquet",),
    should_parse_raw: Optional[Callable[[str], bool]] = None,
) -> pd.DataFrame:
    """Collect parser output DataFrame from nested file path mappings.

    The function handles case-insensitive extension checks and optional passthrough
    loading for parquet files. Every file is tried; if any cannot be read, or holds no
    data, :class:`ParseError` names them all, so wrong data is never stored silently
    (e.g. files of another instrument).

    When more than one file contributes rows, each row gets a ``source_file``
    column with the stem of its file (unless the parser already set one).
    """

    frames: list[tuple[str, pd.DataFrame]] = []
    failures: list[str] = []
    normalized_ext = file_extension.casefold()
    passthrough_exts = tuple(ext.casefold() for ext in passthrough_extensions)

    for paths in dict_paths.values():
        for path in paths:
            path_cf = str(path).casefold()

            try:
                parse_raw_path = (
                    should_parse_raw(path)
                    if should_parse_raw is not None
                    else path_cf.endswith(normalized_ext)
                )

                if parse_raw_path:
                    parsed = parse_raw(path)
                    if parsed.empty:
                        failures.append(f"{Path(path).name}: no data found")
                    else:
                        frames.append((Path(path).stem, parsed))

                elif path_cf.endswith(passthrough_exts):
                    frames.append((Path(path).stem, pd.read_parquet(path)))

                else:
                    logger.debug("Skipping unsupported %s path: %s", parser_label, path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{Path(path).name}: {exc}")

    if failures:
        shown = "; ".join(failures[:5]) + (f"; and {len(failures) - 5} more" if len(failures) > 5 else "")
        raise ParseError(f"The {parser_label} parser could not read {len(failures)} file(s): {shown}")

    if not frames:
        return pd.DataFrame()
    if len(frames) > 1:
        frames = [
            (stem, frame if SOURCE_FILE_COLUMN in frame.columns else frame.assign(**{SOURCE_FILE_COLUMN: stem}))
            for stem, frame in frames
        ]
    return pd.concat([frame for _, frame in frames], axis=0).reset_index(drop=True)
