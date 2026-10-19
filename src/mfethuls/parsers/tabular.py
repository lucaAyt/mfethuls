"""The one parser behind every instrument definition.

:class:`TabularParser` reads text files that hold one table (an optional
preamble, a header of one or two lines, rows of values, an optional footer) as
an :class:`~mfethuls.instruments.definition.InstrumentDefinition` describes them,
then maps the columns to standard quantities and units.

Nothing is dropped: columns without a mapping keep their file name, every row is
kept (empty lines aside, and rows repeating an earlier row in every field when the
format says ``duplicate_rows: drop``), and the text before and after the table is
stored in the dataset's metadata under ``file_text``.
"""

from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from mfethuls.instruments.definition import (
    AUTO_ENCODING,
    CONTAINS_LINES,
    TIME_UNITS,
    CapturedValue,
    ColumnMapping,
    FileFormat,
    InstrumentDefinition,
    TextTable,
)
from mfethuls.instruments.units import QUANTITIES, conversion, convert
from mfethuls.instruments import patterns, workbook
from mfethuls.parsers.ingestion import ParseError, build_dataset, collect_dataframe_from_paths, read_lines
from mfethuls.parsers.registry import reader_fingerprint, reads
from mfethuls.schema_normalization import apply_dataframe_schema

logger = logging.getLogger(__name__)

# Columns parsers add themselves; a definition never renames them.
_BOOKKEEPING = ("name", "source_file")
# DataFrame.attrs keys set by TabularParser.parse_raw_data.
_FORMAT_ATTR = "mfethuls_format"
_TEXT_ATTR = "mfethuls_file_text"
_TABLES_ATTR = "mfethuls_tables"


def _split(line: str, fmt: FileFormat) -> List[str]:
    if fmt.separator is None:
        return line.split()
    return [field.strip() for field in next(csv.reader([line], delimiter=fmt.separator))]


def _split_header(line: str, fmt: FileFormat, width: int) -> List[str]:
    """Header fields; with whitespace columns, names may contain single spaces ("Heat Flow").

    When splitting at every space gives another count than the data has columns,
    the header is split at runs of two or more spaces instead, if that fits.
    """
    fields = _split(line, fmt)
    if fmt.separator is None and width and len(fields) != width:
        wide = [f for f in re.split(r"\s{2,}|	", line.strip()) if f]
        if len(wide) == width:
            return wide
    return fields


def _spans(line: str, fields: List[str]) -> List[Tuple[int, int]]:
    """Where each field sits in ``line`` (start, end), searching left to right."""
    spans, at = [], 0
    for field in fields:
        start = line.find(field, at)
        if start < 0:
            return []
        spans.append((start, start + len(field)))
        at = start + len(field)
    return spans


def _aligned(parts: List[List[str]], lines: List[str]) -> List[List[str]]:
    """Header lines with fewer fields than the longest one, placed under it by position.

    In whitespace-aligned files a units line may leave a column out (no unit under
    ``Index``); its fields belong to the columns they stand under, not to the first ones.
    Lines that do not line up one field per column are left as they are.
    """
    widest = max(range(len(parts)), key=lambda i: len(parts[i]))
    reference = _spans(lines[widest].expandtabs(), parts[widest])
    if not reference:
        return parts
    out = []
    for fields, line in zip(parts, lines):
        spans = _spans(line.expandtabs(), fields)
        if len(fields) >= len(reference) or not spans:
            out.append(fields)
            continue

        def column(span: Tuple[int, int]) -> int:
            overlap = [min(span[1], end) - max(span[0], start) for start, end in reference]
            centre = sum(span) / 2
            return max(range(len(reference)),
                       key=lambda i: (overlap[i], -abs(centre - sum(reference[i]) / 2)))

        columns = [column(span) for span in spans]
        if len(set(columns)) != len(columns) or columns != sorted(columns):
            out.append(fields)
            continue
        placed = [""] * len(reference)
        for i, field in zip(columns, fields):
            placed[i] = field
        out.append(placed)
    return out


def _is_number(text: str, fmt: FileFormat) -> bool:
    text = text.strip()
    if fmt.decimal == ",":
        text = text.replace(",", ".")
    try:
        float(text)
    except ValueError:
        return False
    return True


def _unique(names: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name} ({count + 1})")
    return out


def _header_index(lines: List[str], fmt: FileFormat) -> int:
    start = 0
    if fmt.header_starts_at:
        found = next((i for i, line in enumerate(lines) if fmt.header_starts_at in line), None)
        if found is None:
            raise ValueError(f"no line contains the header text {fmt.header_starts_at!r}")
        start = found
    return start + fmt.skip_lines


def _sheet_hint(fmt: FileFormat) -> Optional[str]:
    """Text on the table's sheet, for workbooks without ``file.sheet``."""
    return fmt.header_starts_at or (fmt.blocks.starts_at if fmt.blocks else None)


def read_text(path, fmt: FileFormat) -> List[str]:
    if fmt.workbook:
        return workbook.sheet_lines(path, fmt.sheet, _sheet_hint(fmt))[1]
    if fmt.encoding == AUTO_ENCODING:
        return read_lines(path)
    text = Path(path).read_text(encoding=fmt.encoding)
    return text.removeprefix("﻿").splitlines()  # a UTF-8 byte order mark is not data


@dataclass
class _Scan:
    """A file split into its parts: column names, rows (with their line numbers) and text."""

    names: List[str]
    rows: List[List[str]]
    row_lines: List[int]  # 1-based line number of each row in the file
    text: Dict[str, List[str]]
    labels: Optional[List[Optional[str]]] = None  # segment of each row (``segment_lines``)
    unnamed: Tuple[str, ...] = ()  # columns without a name in the header
    before: Tuple[str, ...] = ()  # every line before the table (``from_header`` searches them)


def _first_field(fields: List[str]) -> str:
    """The first filled field (lines of tab-separated exports often start with a tab)."""
    return next((f for f in fields if f.strip()), "")


def _scan_blocks(path, fmt: FileFormat) -> Tuple[List[str], List[Tuple[Optional[str], _Scan]]]:
    """The lines before the first block and each block's ``(label, scan)``.

    Without ``blocks`` the whole file is one block without a label. With it, a
    block starts at every line containing ``blocks.starts_at``; the lines after it
    are read like a file of their own. Its label is the first group of ``blocks.label`` found on that
    line, else its number (1, 2, ...). A file without such a line is one block, 1.
    """
    return _scan_lines(read_text(path, fmt), fmt)


def _scan_lines(lines: List[str], fmt: FileFormat) -> Tuple[List[str], List[Tuple[Optional[str], _Scan]]]:
    """:func:`_scan_blocks` of a file's (or a workbook sheet's) ``lines``."""
    if fmt.blocks is None:
        return [], [(None, _scan(lines, fmt))]
    starts = [i for i, line in enumerate(lines) if fmt.blocks.starts_at in line]
    if not starts:
        return [], [("1", _scan(lines, fmt))]  # one table, without a line starting it: block 1
    blocks = []
    for number, (start, end) in enumerate(zip(starts, starts[1:] + [len(lines)]), start=1):
        label = _capture(fmt.blocks.label, lines[start]) if fmt.blocks.label else None
        try:
            scan = _scan(lines[start + 1:end], fmt, offset=start + 1)
        except ValueError as exc:
            raise ValueError(f"block {number} (line {start + 1}): {exc}") from None
        scan.text["preamble"] = [lines[start], *scan.text.get("preamble", [])]
        blocks.append((label or str(number), scan))
    return lines[:starts[0]], blocks


def _scan(lines: List[str], fmt: FileFormat, offset: int = 0) -> _Scan:
    """One table in ``lines``; ``offset`` is the file line number of ``lines[0]`` (0-based)."""
    first = _header_index(lines, fmt)
    if not fmt.header_rows:
        # Without header lines the table starts at the first line of numbers; text above it is preamble.
        while first < len(lines) and not (lines[first].strip()
                                          and _is_number(_first_field(_split(lines[first], fmt)), fmt)):
            first += 1
        if first >= len(lines):
            raise ValueError("no line of numbers found")
    if first >= len(lines):
        raise ValueError("the file ends before the header")

    # Header lines in order; blank lines between them (e.g. only tabs) are skipped.
    header_lines: List[str] = []
    body_start = first
    while len(header_lines) < fmt.header_rows and body_start < len(lines):
        if lines[body_start].strip() or not header_lines:
            header_lines.append(lines[body_start])
        body_start += 1
    body = lines[body_start:]
    split = [None if not line.strip() or (fmt.comment and line.lstrip().startswith(fmt.comment))
             else _split(line, fmt) for line in body]
    numeric = [fields is not None and _is_number(_first_field(fields), fmt) for fields in split]
    last_numeric = max((i for i, flag in enumerate(numeric) if flag), default=-1)
    preamble = [line for line in lines[:first] if line.strip()]

    rows: List[List[str]] = []
    row_lines: List[int] = []
    comments: List[str] = []
    footer: List[str] = []
    labels: List[Optional[str]] = []
    label = preamble[-1].strip() if fmt.segment_lines and preamble else None
    for i, line in enumerate(body):
        fields = split[i]
        if fields is None:
            if line.strip():
                comments.append(line)
            continue
        if fmt.data_ends not in ("end_of_file", "first_non_numeric_row") and fmt.data_ends in line:
            footer = [text for text in body[i:] if text.strip()]
            break
        if not numeric[i] and fmt.segment_lines and i < last_numeric:
            label = line.strip()
            continue
        # The data ends at text after the numbers; rows before the first number (e.g. a
        # rheometer's "1  (invalid)" points, which still carry a time stamp) are data.
        if not numeric[i] and fmt.data_ends == "first_non_numeric_row" and rows and any(numeric[:i]):
            footer = [text for text in body[i:] if text.strip()]
            break
        rows.append(fields)
        row_lines.append(offset + body_start + i + 1)
        labels.append(label)

    if fmt.header_rows:
        data_width = Counter(len(r) for r in rows).most_common(1)[0][0] if rows else 0
        parts = [_split_header(line, fmt, data_width) for line in header_lines]
        if fmt.separator is None:
            parts = _aligned(parts, header_lines)
        width =max(max(len(p) for p in parts), max((len(r) for r in rows), default=0))
        named = [" ".join(p[i] for p in parts if i < len(p) and p[i]).strip() for i in range(width)]
        names = [name or f"column_{i + 1}" for i, name in enumerate(named)]
        unnamed = tuple(f"column_{i + 1}" for i, name in enumerate(named) if not name)
    elif fmt.names_from:
        listed = [m.group(1).strip() for line in lines[:first] if (m := patterns.search(fmt.names_from, line))]
        width = max(len(listed), max((len(r) for r in rows), default=0))
        names = [listed[i] if i < len(listed) and listed[i] else f"column_{i + 1}" for i in range(width)]
        unnamed = ()
    else:
        width = max((len(r) for r in rows), default=0)
        names = [f"column_{i + 1}" for i in range(width)]
        unnamed = ()

    text = {"preamble": preamble, "footer": footer, "comments": comments}
    return _Scan(_unique(names), rows, row_lines, {key: value for key, value in text.items() if value},
                 labels if fmt.segment_lines else None, unnamed, tuple(lines[:first]))


def read_file(path, fmt: FileFormat, from_header: Tuple[CapturedValue, ...] = (),
              tables: Tuple[TextTable, ...] = ()) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """The file's table with its own column names, and the text around it.

    Numeric columns become numbers. The text is ``{"preamble": [...], "footer": [...],
    "comments": [...]}`` (non-empty parts only). With ``segment_lines``, a
    ``segment`` column holds the text line each row falls under. A column with
    neither a name nor any value (e.g. from a leading tab) is not data and is left
    out. ``from_header`` values are taken from the lines before the table. Raises
    ``ValueError`` with a message for the user when the table is not where the
    format says.
    """
    if fmt.workbook:
        df, before, text = _read_workbook(path, fmt)
    else:
        df, before, text = _read_lines(*_scan_blocks(path, fmt), fmt)
    # Values are searched before the table, then in the text after it (and other sheets).
    around = [*before, *(line for key, lines in text.items() if key not in ("preamble", "sheets")
                         for line in lines)]
    for value in from_header:
        if SHEET_PLACEHOLDER in value.pattern and "sheet" in df.columns:
            # One value per test sheet, e.g. its row in a results sheet: {sheet} is the sheet's name.
            parts = []
            for name in df["sheet"].unique():
                pattern = value.pattern.replace(SHEET_PLACEHOLDER, _sheet_pattern(name))
                found = next((m for line in around if (m := _capture(pattern, line)) is not None), None)
                parts.append(_stored(value, found, fmt.decimal, df.index[df["sheet"] == name]))
            df[value.column] = pd.concat(parts).reindex(df.index)
            continue
        pattern = value.pattern.replace(SHEET_PLACEHOLDER, ".*")
        found = next((m for line in around if (m := _capture(pattern, line)) is not None), None)
        df[value.column] = _stored(value, found, fmt.decimal, df.index)
    found_tables = {table.name: rows for table in tables if (rows := text_table(around, table, fmt))}
    if found_tables:
        df.attrs[_TABLES_ATTR] = found_tables
    return df, text


def text_table(lines: List[str], table: TextTable, fmt: FileFormat) -> List[Dict[str, object]]:
    """The rows of ``table`` in ``lines``: after its ``starts_at`` line, up to its ``ends_at`` line.

    Only rows starting with a number are rows; numbers are stored as numbers.
    """
    start = next((i for i, line in enumerate(lines) if table.starts_at in line), None)
    if start is None:
        return []
    rows = []
    for line in lines[start + 1:]:
        if table.ends_at is not None and table.ends_at in line:
            break
        fields = _split(line, fmt) if line.strip() else []
        if not fields or not _is_number(fields[0], fmt):
            continue
        rows.append({(table.columns[i] if i < len(table.columns) else f"column_{i + 1}"): _number_or_text(f, fmt)
                     for i, f in enumerate(fields)})
    return rows


def _number_or_text(text: str, fmt: FileFormat):
    if not _is_number(text, fmt):
        return text
    return float(text.replace(",", ".") if fmt.decimal == "," else text)


SHEET_PLACEHOLDER = patterns.SHEET_PLACEHOLDER


def _sheet_pattern(name: str) -> str:
    """A sheet name in a pattern. Excel cuts long names ('LUBxxx_80C_DCMGel...'): the rest may follow."""
    if name.endswith("..."):
        return re.escape(name[:-3]) + r"\S*"
    return re.escape(name) + r"(?![^\t])"


def _read_workbook(path, fmt: FileFormat) -> Tuple[pd.DataFrame, List[str], Dict[str, List[str]]]:
    """Every table sheet of a workbook, one after the other, with a ``sheet`` column.

    A workbook often holds one test per sheet (named after the specimen); all are
    read. The other sheets (parameters, results, ...) are kept as text.
    """
    tables, others = workbook.table_sheets(path, fmt.sheet, _sheet_hint(fmt))
    frames, before, text = [], [], {"sheets": list(tables)}
    for name, lines in tables.items():
        try:
            df, sheet_before, sheet_text = _read_lines(*_scan_lines(lines, fmt), fmt)
        except ValueError as exc:
            raise ValueError(f"sheet {name!r}: {exc}") from None
        df["sheet"] = name
        frames.append(df)
        before += sheet_before
        for key, value in sheet_text.items():
            text[key if len(tables) == 1 else f"{key} ({name})"] = value
    text.update({f"sheet: {name}": lines for name, lines in others.items() if any(line.strip() for line in lines)})
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0], before, text


def _read_lines(before: List[str], blocks: List[Tuple[Optional[str], _Scan]], fmt: FileFormat
                ) -> Tuple[pd.DataFrame, List[str], Dict[str, List[str]]]:
    """The table of scanned ``blocks``, the lines before it and the text around it."""
    frames, segments, block_labels, unnamed = [], [], [], set()
    for label, scan in blocks:
        rows = [r + [""] * (len(scan.names) - len(r)) for r in scan.rows]
        frames.append(pd.DataFrame(rows, columns=scan.names, dtype="string"))
        segments += scan.labels or [None] * len(rows)
        block_labels += [label] * len(rows)
        unnamed.update(scan.unnamed)
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    empty = [c for c in sorted(unnamed) if c in df.columns and not (df[c].fillna("").str.strip() != "").any()]
    df = df.drop(columns=empty).apply(lambda column: _to_numbers(column, fmt))
    if fmt.segment_lines:
        df["segment"] = segments
    if fmt.blocks is not None:
        df[fmt.blocks.column] = _labels(block_labels)
    if fmt.blocks is None:
        before, text = list(blocks[0][1].before), blocks[0][1].text
    else:
        # The text of each block (its first line, text after its table, ...) in file order.
        block_text = [line for _, scan in blocks for part in ("preamble", "comments", "footer")
                      for line in scan.text.get(part, [])]
        text = {key: value for key, value in (("preamble", [line for line in before if line.strip()]),
                                              ("blocks", block_text)) if value}
    if fmt.duplicate_rows == "drop":
        repeated = df.duplicated()
        if repeated.any():
            df = df[~repeated].reset_index(drop=True)
            text = {**text, "notes": [*text.get("notes", []), f"{int(repeated.sum())} row(s) repeating an earlier "
                                      "row in every field left out"]}
    return df, before, text


def _labels(labels: List[str]) -> pd.Series:
    """Block labels, as whole numbers when they all are."""
    numbers = pd.to_numeric(pd.Series(labels, dtype=object), errors="coerce")
    if len(labels) and numbers.notna().all() and (numbers == numbers.round()).all():
        return numbers.astype("int64")
    return pd.Series(labels, dtype=object)


def _capture(pattern: str, text: str) -> Optional[str]:
    """The first group of ``pattern`` in ``text`` (the whole match without a group), or None."""
    match = patterns.search(pattern, text)
    if match is None:
        return None
    text = match.group(1) if match.groups() else match.group(0)
    return text.strip() if text is not None else None


def _stored(value: CapturedValue, text: Optional[str], decimal: str, index: pd.Index) -> pd.Series:
    """A captured text as ``value`` stores it: looked up in ``values``, then as its ``type``.

    Text that cannot be read as the type is stored as missing; the file text keeps it.
    """
    if text is not None:
        text = next((stored for stored, pattern in value.values if patterns.search(pattern, text, ignore_case=True)), text)
    if value.type == "number":
        number = None
        if text is not None:
            try:
                number = float(text.replace(",", ".") if decimal == "," else text)
            except ValueError:
                pass
        return pd.Series([number] * len(index), index=index, dtype="float64")
    if value.type == "datetime":
        moment = _datetime(text, value.timezone)
        return pd.Series([moment] * len(index), index=index, dtype="datetime64[ns, UTC]")
    return pd.Series([text] * len(index), index=index, dtype=object)


# Excel day numbers of 1950-2100 with a time of day, e.g. 46246.745150462964 (2026-08-12 17:53).
_EXCEL_DAY = re.compile(r"(?:18[2-9]|19\d|[2-6]\d\d|7[0-3]\d)\d\d\.\d+")


def _datetime(text: Optional[str], timezone: Optional[str]) -> pd.Timestamp:
    """``text`` as a UTC time; zone abbreviations and times without a zone are in ``timezone``."""
    from dateutil.parser import ParserError, parse
    from dateutil.tz import UTC, gettz, tzoffset

    if not text:
        return pd.NaT
    zone = gettz(timezone) if timezone else None

    def zones(name, offset):
        if offset is not None:
            return tzoffset(name, offset)
        if name in ("UTC", "GMT", "Z"):
            return UTC
        return zone or gettz(name)

    if _EXCEL_DAY.fullmatch(text.strip()):
        # An Excel date saved as a plain number: days since 1899-12-30 (fractions are the time of day).
        moment = (pd.Timestamp("1899-12-30") + pd.to_timedelta(float(text), unit="D")).round("ms").to_pydatetime()
    else:
        try:
            moment = parse(text, tzinfos=zones)
        except (ParserError, ValueError, OverflowError):
            return pd.NaT
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone or UTC)
    return pd.Timestamp(moment).tz_convert("UTC")


def text_in_numbers(path, fmt: FileFormat) -> Optional[Dict[str, object]]:
    """Rows holding text in columns that are otherwise numbers, or None.

    Such rows are usually not data: a footer, a results block or a second table
    read as part of the table. Returns ``{"rows": n, "columns": [...], "first_line": n,
    "first_text": "..."}``; the line number is the file's (1-based).
    """
    _, blocks = _scan_blocks(path, fmt)
    bad_lines: Dict[int, List[str]] = {}
    columns: List[str] = []
    names = list(dict.fromkeys(name for _, scan in blocks for name in scan.names))
    for name in names:
        filled = [(line, row[scan.names.index(name)]) for _, scan in blocks if name in scan.names
                  for line, row in zip(scan.row_lines, scan.rows)
                  if scan.names.index(name) < len(row) and row[scan.names.index(name)].strip()]
        if not filled:
            continue
        text = [(line, value) for line, value in filled if not _is_number(value, fmt)]
        if text and len(text) <= len(filled) / 2:
            columns.append(name)
            rows = {line: row for _, scan in blocks for line, row in zip(scan.row_lines, scan.rows)}
            bad_lines.update((line, rows[line]) for line, _ in text)
    if not bad_lines:
        return None
    first = min(bad_lines)
    row = bad_lines[first]
    return {"rows": len(bad_lines), "columns": columns, "first_line": first,
            "first_text": (fmt.separator or " ").join(row).strip()[:60]}


def read_table(path, fmt: FileFormat) -> pd.DataFrame:
    """The file's table only (see :func:`read_file`)."""
    return read_file(path, fmt)[0]


def _to_numbers(column: pd.Series, fmt: FileFormat) -> pd.Series:
    text = column.str.strip()
    filled = text.notna() & (text != "")
    values = text.str.replace(",", ".", regex=False) if fmt.decimal == "," else text
    numbers = pd.to_numeric(values.astype(object), errors="coerce")
    if filled.any() and numbers[filled].notna().all():
        return numbers.astype("float64")
    return column.astype(object).where(filled, None)  # empty cells are missing, not ""


def select_format(definition: InstrumentDefinition, path) -> int:
    """Index of the first format that reads ``path``: its extension, then its ``contains`` text."""
    extension = Path(path).suffix.casefold()
    candidates = [i for i, fmt in enumerate(definition.formats) if extension in fmt.file.extensions]
    if not candidates:
        raise ValueError(f"no format of {definition.name} reads {extension or 'files without an ending'}")
    for i in candidates:
        contains = definition.formats[i].file.contains
        if contains is None:
            return i
        try:
            if definition.formats[i].file.workbook:
                head = "\n".join(line for lines in workbook.sheets(path).values() for line in lines[:CONTAINS_LINES])
            else:
                encoding = definition.formats[i].file.encoding
                with open(path, encoding="cp1252" if encoding == AUTO_ENCODING else encoding,
                          errors="replace") as f:
                    head = "".join(line for _, line in zip(range(CONTAINS_LINES), f))
        except (OSError, ValueError):
            continue
        if contains in head:
            return i
    expected = "; ".join(
        f"{definition.formats[i].label or f'format {i + 1}'}: {definition.formats[i].file.contains!r}"
        for i in candidates
    )
    raise ValueError(f"the file matches none of the {definition.name} formats (looked for {expected})")


def _find_source(df: pd.DataFrame, sources: Tuple[str, ...]) -> Optional[str]:
    for source in sources:
        if source in df.columns:
            return source
    loose = {str(c).strip().casefold(): c for c in df.columns}
    for source in sources:
        if source.strip().casefold() in loose:
            return loose[source.strip().casefold()]
    return None


def map_columns(
    df: pd.DataFrame,
    columns: Tuple[ColumnMapping, ...],
    instrument_type: str,
    decimal: str = ".",
    not_numbers: Optional[Dict[str, List[str]]] = None,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Rename mapped columns to their stored names and convert units; keep every other column.

    Returns the new frame and ``{stored column: file column}``. A mapping whose
    file column is absent is skipped (the type's required columns are checked
    later). A file column that already has a stored name used by a mapping is
    kept as ``"<name> (file)"``.

    Text in a column mapped to a quantity cannot be stored as a number and becomes
    missing; with ``not_numbers``, each such file column gets the list of those texts.
    """
    mapped: Dict[str, pd.Series] = {}
    used: Dict[str, str] = {}
    for mapping in columns:
        source = _find_source(df, mapping.sources)
        if source is None:
            continue
        if mapping.column:
            mapped[mapping.column] = df[source]
            used[mapping.column] = source
            continue
        quantity = QUANTITIES[mapping.quantity]
        target, _ = quantity.target(instrument_type, mapping.unit)
        values = df[source]
        if decimal == "," and values.dtype == object:
            # A column with some text rows was left as text; its numbers still use a decimal comma.
            values = values.astype(str).str.replace(",", ".", regex=False)
        values = pd.to_numeric(values, errors="coerce")
        if values.isna().all() and df[source].notna().any():
            raise ValueError(f"column {source!r} ({quantity.label}) holds no numbers")
        if not_numbers is not None:
            original = df[source].astype(object)
            filled = original.notna() & (original.astype(str).str.strip() != "")
            lost = original[filled & values.isna()]
            if len(lost):
                not_numbers[source] = [str(v).strip() for v in lost]
        factor, offset = conversion(quantity, mapping.unit, instrument_type)
        mapped[target] = convert(values.astype("float64"), factor, offset)
        used[target] = source

    out = pd.DataFrame(mapped, index=df.index)
    sources = set(used.values())
    for column in df.columns:
        if column in sources:
            continue
        name = column if column not in out.columns or column in _BOOKKEEPING else f"{column} (file)"
        out[name] = df[column]
    return out, used


def apply_derived(df: pd.DataFrame, definition: InstrumentDefinition) -> Tuple[pd.DataFrame, List[str]]:
    """Add the definition's ``derived`` columns; existing columns are never changed.

    An operation on a column the data does not have is skipped. Returns the frame
    and warnings for operations that were skipped because their column exists.
    """
    warnings = []
    for step in definition.derived:
        if step.column not in df.columns:
            continue
        if step.into in df.columns:
            warnings.append(f"{step.op}: {step.into!r} already comes from the file; not computed")
            continue
        values = df[step.column]
        if step.op == "add_time":
            # A missing amount (e.g. a file name without milliseconds) adds nothing.
            amount = pd.to_numeric(df[step.amount], errors="coerce") if step.amount in df.columns else 0.0
            amount = (amount.fillna(0.0) if isinstance(amount, pd.Series) else amount) * TIME_UNITS[step.unit]
            df[step.into] = pd.to_datetime(values, errors="coerce", utc=True) + pd.to_timedelta(amount, unit="ms")
        elif step.op == "normalize_pct":
            low, high = values.min(), values.max()
            if high != low:
                df[step.into] = (values - low) / (high - low) * 100
        elif step.op == "pct_of_initial":
            # Percent of each curve's first value (TGA: 100 % = the initial mass).
            groups = df["name"] if "name" in df.columns else pd.Series(0, index=df.index)
            first = values.groupby(groups).transform(lambda v: v.dropna().iloc[0] if v.notna().any() else float("nan"))
            df[step.into] = (values / first.where(first != 0)) * 100
        elif step.op in ("multiply", "divide"):
            if step.by not in df.columns:
                continue  # e.g. no sample mass in this file
            other = pd.to_numeric(df[step.by], errors="coerce")
            df[step.into] = values * other if step.op == "multiply" else values / other.where(other != 0)
        elif step.op == "scale":
            df[step.into] = values * step.factor
        elif step.op == "offset":
            df[step.into] = values + step.value
    return df, warnings


def _not_numbers_notes(path, fmt: FileFormat, not_numbers: Dict[str, List[str]]) -> List[str]:
    """One note per file column whose text could not be stored as numbers, with where it starts."""
    try:
        info = text_in_numbers(path, fmt)  # read again only when something was lost
    except ValueError:
        info = None
    notes = []
    for column, texts in not_numbers.items():
        examples = ", ".join(repr(t) for t in list(dict.fromkeys(texts))[:3])
        where = f", from line {info['first_line']}" if info and column in info["columns"] else ""
        notes.append(f"{column}: {len(texts)} value(s) that are not numbers stored as missing ({examples}){where}")
    return notes


def _per_sheet(df: pd.DataFrame, value: CapturedValue):
    """A captured value for the metadata: one per file, or ``{sheet: value}`` with ``{sheet}`` in its pattern."""
    if SHEET_PLACEHOLDER in value.pattern and "sheet" in df.columns:
        first = df.groupby("sheet", sort=False)[value.column].first()
        return {str(sheet): _plain(v) for sheet, v in first.items()}
    return _plain(df[value.column].iloc[0])


def _plain(value):
    """A value as JSON can hold it (metadata): numbers, text, ISO date-times, or None."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


def _refuse_same_names(dict_paths, is_read) -> None:
    """Files are told apart by name (``source_file``, ``file_text``): two read files with one stem,
    e.g. ``run1/data.txt`` and ``run2/data.txt`` in a folder experiment, would be mixed up."""
    for paths in dict_paths.values():
        by_stem: Dict[str, List[str]] = {}
        for path in paths:
            if is_read(path):
                by_stem.setdefault(Path(path).stem.casefold(), []).append(str(path))
        clashes = [found for found in by_stem.values() if len(found) > 1]
        if clashes:
            listed = "; ".join(", ".join(found) for found in clashes)
            raise ParseError(f"Files with the same name in one experiment can't be told apart: {listed}. "
                             "Rename them, or move files that are not part of the experiment out of its folder.")


class TabularParser:
    """Parser for one instrument, configured by its definition instead of code."""

    # Raise when a change here can change the data read with an unchanged definition
    # (part of every definition-read dataset's reader_fingerprint, so Clean up offers Read again).
    version = 1

    def __init__(self, definition: InstrumentDefinition):
        self.definition = definition
        self.file_extension = definition.extensions[0]
        self.extra_extensions = definition.extensions[1:]

    def __repr__(self) -> str:
        return f"TabularParser({self.definition.name!r})"

    def parse_raw_data(self, path) -> pd.DataFrame:
        """One file's table, with its file column names and a ``name`` column."""
        definition = self.definition
        index = select_format(definition, path)
        fmt = definition.formats[index].file
        df, text = read_file(path, fmt, definition.from_header, definition.tables)
        if df.empty:
            return df
        df["name"] = Path(path).parent.name if definition.name_from == "folder" else Path(path).stem
        if definition.name_from == "sheet" and "sheet" in df.columns and df["sheet"].nunique() > 1:
            df["name"] = df["sheet"]  # one test per sheet, named after the specimen; a single test keeps the file name
        for value in definition.from_file_name:
            df[value.column] = _stored(value, _capture(value.pattern, Path(path).stem), fmt.decimal, df.index)
        df.attrs[_FORMAT_ATTR] = index
        df.attrs[_TEXT_ATTR] = text
        return df

    def parse(self, dict_paths, *, instrument_model: Optional[str] = None, measurement_profile=None, **context):
        definition = self.definition
        _refuse_same_names(dict_paths, lambda path: reads(self, path))
        renamed: Dict[str, str] = {}
        file_text: Dict[str, dict] = {}
        tables: Dict[str, Dict[str, list]] = {}
        stored_as_missing: List[str] = []

        def read(path) -> pd.DataFrame:
            df = self.parse_raw_data(path)
            if df.empty:
                return df
            fmt = definition.formats[df.attrs.get(_FORMAT_ATTR, 0)]
            text = df.attrs.get(_TEXT_ATTR) or {}
            for name, rows in (df.attrs.get(_TABLES_ATTR) or {}).items():
                tables.setdefault(name, {})[Path(path).name] = rows
            not_numbers: Dict[str, List[str]] = {}
            mapped, used = map_columns(df, fmt.columns, definition.type, fmt.file.decimal, not_numbers)
            renamed.update(used)
            if not_numbers:
                # Keep-all-data: what could not be stored is recorded with the file (the raw file is unchanged).
                notes = _not_numbers_notes(path, fmt.file, not_numbers)
                text = {**text, "notes": [*text.get("notes", []), *notes]}
                stored_as_missing.extend(f"{Path(path).name}: {note}" for note in notes)
            # Values taken from the file's text (a sample mass, a date), once per file.
            values = {v.column: _per_sheet(df, v) for v in definition.from_header if v.column in df.columns}
            if text or values or len(definition.formats) > 1:
                file_text[Path(path).name] = {**({"format": fmt.label} if fmt.label else {}), **text,
                                              **({"values": values} if values else {})}
            return mapped

        df = collect_dataframe_from_paths(
            dict_paths,
            file_extension=self.file_extension,
            parse_raw=read,
            logger=logger,
            parser_label=definition.name,
            should_parse_raw=lambda path: reads(self, path),
        )
        df, derived_warnings = apply_derived(df, definition)
        # The registry's measurement profile ("time sweep") as the type's schema names it, for its plot.
        metadata = dict(context.pop("metadata", None) or {})
        registry_profile = measurement_profile or metadata.get("registry_measurement_profile")
        if registry_profile:
            from mfethuls.registry_validator import infer_canonical_profile_from_registry_profile

            measurement_profile = infer_canonical_profile_from_registry_profile(
                definition.type, registry_profile, instrument_model or definition.model)
            metadata.update(registry_measurement_profile=registry_profile, measurement_profile=measurement_profile)
        df, schema_report = apply_dataframe_schema(
            df,
            instrument_type=definition.type,
            instrument_model=instrument_model or definition.model,
            measurement_profile=measurement_profile,
        )
        schema_report["renamed_columns"] = {**renamed, **schema_report.get("renamed_columns", {})}
        schema_report["warnings"] = [*schema_report.get("warnings", []), *derived_warnings, *stored_as_missing]
        extra = {
            "instrument_definition": definition.name,
            "reader_fingerprint": reader_fingerprint(self),
        }
        if file_text:
            extra["file_text"] = file_text
        if tables:
            extra["tables"] = tables
        return build_dataset(df, schema_report, instrument_model=instrument_model, extra=extra,
                             metadata=metadata or None, **context)


def register_definition(definition: InstrumentDefinition) -> TabularParser:
    """Make ``get_parser(type, model)`` return a parser for ``definition``."""
    from mfethuls.parsers.registry import _PARSER_REGISTRY

    current = _PARSER_REGISTRY.get((definition.type, definition.model))
    if isinstance(current, TabularParser) and current.definition == definition:
        return current
    parser = TabularParser(definition)
    _PARSER_REGISTRY[(definition.type, definition.model)] = parser
    return parser
