from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

# Added when an experiment has several files (a series or titration): the stem of
# the file each row came from, so the spectra or curves stay apart after combining.
SOURCE_FILE_COLUMN = "source_file"


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

    The function handles case-insensitive extension checks, optional passthrough
    loading for parquet files, and per-path exception isolation so one malformed
    file does not abort the whole parse batch.

    When more than one file contributes rows, each row gets a ``source_file``
    column with the stem of its file (unless the parser already set one).
    """

    frames: list[tuple[str, pd.DataFrame]] = []
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
                    if not parsed.empty:
                        frames.append((Path(path).stem, parsed))

                elif path_cf.endswith(passthrough_exts):
                    frames.append((Path(path).stem, pd.read_parquet(path)))

                else:
                    logger.debug("Skipping unsupported %s path: %s", parser_label, path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed parsing %s path %s: %s", parser_label, path, exc)

    if not frames:
        return pd.DataFrame()
    if len(frames) > 1:
        frames = [
            (stem, frame if SOURCE_FILE_COLUMN in frame.columns else frame.assign(**{SOURCE_FILE_COLUMN: stem}))
            for stem, frame in frames
        ]
    return pd.concat([frame for _, frame in frames], axis=0).reset_index(drop=True)
