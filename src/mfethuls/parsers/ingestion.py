"""Shared parsing helpers: read files' lines, keep the text around tables, combine files, build the Dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional

import pandas as pd

# Added when an experiment has several files (a series or titration): the stem of
# the file each row came from, so the spectra or curves stay apart after combining.
SOURCE_FILE_COLUMN = "source_file"


# DataFrame.attrs key under which a parser hands over the text around its table.
FILE_TEXT_ATTR = "mfethuls_file_text"


class ParseError(ValueError):
    """Raw data files could not be read as the chosen instrument's data."""


# -- keeping everything: helpers for parsers ---------------------------------------
# mfethuls is an ETL platform first: a parser keeps every column, every row and the
# text around the table. These helpers do the common parts.

def read_lines(path) -> List[str]:
    """The file's lines; UTF-8, else Windows cp1252 (no character is silently dropped)."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1").splitlines()  # never reached: latin-1 decodes everything


def keep_text(df: pd.DataFrame, **parts: List[str]) -> pd.DataFrame:
    """Hand the text around a file's table to :func:`collect_dataframe_from_paths`.

    ``parts`` are lists of lines, e.g. ``preamble=[...]`` or ``footer=[...]``;
    empty ones are left out. Stored in the dataset's metadata under ``file_text``.
    """
    kept = {key: [str(line) for line in lines] for key, lines in parts.items() if lines}
    if kept:
        df.attrs[FILE_TEXT_ATTR] = kept
    return df


def collect_dataframe_from_paths(
    dict_paths,
    *,
    file_extension: str,
    parse_raw: Callable[[str], pd.DataFrame],
    logger,
    parser_label: str,
    passthrough_extensions: Iterable[str] = (".parquet",),
    should_parse_raw: Optional[Callable[[str], bool]] = None,
    file_text: Optional[dict] = None,
) -> pd.DataFrame:
    """Collect parser output DataFrame from nested file path mappings.

    The function handles case-insensitive extension checks and optional passthrough
    loading for parquet files. Every file is tried; if any cannot be read, or holds no
    data, :class:`ParseError` names them all, so wrong data is never stored silently
    (e.g. files of another instrument).

    When more than one file contributes rows, each row gets a ``source_file``
    column with the stem of its file (unless the parser already set one).

    With ``file_text``, the text each parser kept around its table (see
    :func:`keep_text`) is collected there, by file name.
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
                        text = parsed.attrs.pop(FILE_TEXT_ATTR, None)
                        if text and file_text is not None:
                            file_text[Path(path).name] = text
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


# Identifier columns every parser writes into its rows when the file has none.
_ROW_IDS = ("experiment_id", "sample_id", "run_id")


def build_dataset(
    df: pd.DataFrame,
    schema_report: dict,
    *,
    experiment_id: Optional[str] = None,
    sample_id: Optional[str] = None,
    run_id: Optional[str] = None,
    instrument_type: Optional[str] = None,
    instrument_model: Optional[str] = None,
    instrument_name: Optional[str] = None,
    experiment_name: Optional[str] = None,
    metadata: Optional[dict] = None,
    extra: Optional[dict] = None,
    file_text: Optional[dict] = None,
    **_ignored,
):
    """The parser's :class:`~mfethuls.dataset.Dataset`: id columns plus the standard metadata.

    ``extra`` adds parser-specific metadata; the registry's ``metadata`` wins over both.
    """
    from mfethuls.dataset import Dataset

    ids = {"experiment_id": experiment_id, "sample_id": sample_id, "run_id": run_id}
    if "experiment_id" not in df.columns:
        df["experiment_id"] = experiment_id
    for column in _ROW_IDS[1:]:
        if ids[column] is not None and column not in df.columns:
            df[column] = ids[column]

    meta = {
        "schema_version": schema_report.get("schema_version", "1.0"),
        **ids,
        "instrument_type": instrument_type,
        "instrument_model": instrument_model,
        "instrument_name": instrument_name,
        "experiment_name": experiment_name,
        "schema_normalization": schema_report,
        **({"file_text": file_text} if file_text else {}),
        **(extra or {}),
    }
    if metadata:
        meta.update(metadata)
    return Dataset(data=df, metadata=meta)
