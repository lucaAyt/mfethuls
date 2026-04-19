from __future__ import annotations

from typing import Callable, Iterable, Optional

import pandas as pd


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
    """

    df = pd.DataFrame()
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
                        df = pd.concat([df, parsed], axis=0)

                elif path_cf.endswith(passthrough_exts):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    logger.debug("Skipping unsupported %s path: %s", parser_label, path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed parsing %s path %s: %s", parser_label, path, exc)

    return df.reset_index(drop=True)
