"""Excel workbooks (.xlsx) as text: every sheet's rows as lines of tab-separated cells.

The table reader, the detection and the chatbot prompt all work on lines of text.
A workbook is turned into such lines sheet by sheet, so a definition reads it like
a tab-separated export: ``file.sheet`` picks the sheet holding the table, and the
other sheets are kept as text in the dataset's metadata.

Cells hold the values Excel saved (the results of formulas, not the formulas).
Numbers are written in full precision; tabs and line breaks inside a text cell
become spaces.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .definition import WORKBOOK_EXTENSIONS

# A workbook is a zip archive.
_ZIP_MAGIC = b"PK\x03\x04"


def is_workbook(path) -> bool:
    return Path(path).suffix.casefold() in WORKBOOK_EXTENSIONS


def is_binary(path) -> bool:
    """The file is not text (and not a workbook mfethuls can read as text)."""
    with open(path, "rb") as f:
        head = f.read(8192)
    return b"\x00" in head or head.startswith(_ZIP_MAGIC)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)  # shortest text that reads back as the same number
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return " ".join(str(value).replace("\t", " ").splitlines())


@lru_cache(maxsize=8)
def _sheets(path: str, modified: float, size: int, rows: Optional[int] = None) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    from openpyxl import load_workbook

    try:
        book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many kinds; the user needs one message
        raise ValueError(f"cannot open the workbook: {exc}") from None
    try:
        return tuple(
            (sheet.title, tuple("\t".join(_cell(v) for v in row).rstrip("\t") for row in sheet.iter_rows(max_row=rows, values_only=True)))
            for sheet in book.worksheets
        )
    finally:
        book.close()


def sheets(path) -> Dict[str, List[str]]:
    """Every sheet's lines, in workbook order."""
    path = Path(path)
    stat = path.stat()
    return {name: list(lines) for name, lines in _sheets(str(path.resolve()), stat.st_mtime, stat.st_size)}


def sheet_heads(path, rows: int) -> Dict[str, List[str]]:
    """The first ``rows`` lines of every sheet: quicker than :func:`sheets` for a large workbook."""
    path = Path(path)
    stat = path.stat()
    return {name: list(lines) for name, lines in _sheets(str(path.resolve()), stat.st_mtime, stat.st_size, rows)}


def pick_sheet(all_sheets: Dict[str, List[str]], sheet: Optional[Union[int, str]] = None,
               starts_at: Optional[str] = None) -> str:
    """Name of the sheet holding the table.

    ``sheet`` is a name or a number (1 = first, -1 = last). Without it: the first
    sheet with a line containing ``starts_at``, else the first sheet.
    """
    names = list(all_sheets)
    if not names:
        raise ValueError("the workbook has no sheets")
    if isinstance(sheet, int):
        index = sheet - 1 if sheet > 0 else sheet
        if not -len(names) <= index < len(names):
            raise ValueError(f"the workbook has {len(names)} sheets; there is no sheet {sheet}")
        return names[index]
    if isinstance(sheet, str):
        if sheet not in all_sheets:
            raise ValueError(f"the workbook has no sheet {sheet!r} (it has {', '.join(map(repr, names))})")
        return sheet
    if starts_at:
        found = next((name for name, lines in all_sheets.items() if any(starts_at in line for line in lines)), None)
        if found is not None:
            return found
    return names[0]


def table_sheets(path, sheet: Optional[Union[int, str]] = None, starts_at: Optional[str] = None
                 ) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """The sheets holding tables and the other sheets, each ``{name: lines}``.

    With ``sheet``: that sheet. Without it: every sheet with a line containing
    ``starts_at`` (a workbook often holds one test per sheet), else the first sheet.
    """
    all_sheets = sheets(path)
    if sheet is not None or not starts_at:
        names = [pick_sheet(all_sheets, sheet, starts_at)]
    else:
        names = [name for name, lines in all_sheets.items() if any(starts_at in line for line in lines)]
        if not names:
            raise ValueError(f"no sheet has a line containing the header text {starts_at!r}")
    tables = {name: all_sheets[name] for name in names}
    return tables, {name: lines for name, lines in all_sheets.items() if name not in tables}


def sheet_lines(path, sheet: Optional[Union[int, str]] = None,
                starts_at: Optional[str] = None) -> Tuple[str, List[str], Dict[str, List[str]]]:
    """``(name, lines)`` of the table's sheet, and the other sheets' lines."""
    all_sheets = sheets(path)
    name = pick_sheet(all_sheets, sheet, starts_at)
    others = {other: lines for other, lines in all_sheets.items() if other != name}
    return name, all_sheets[name], others


def as_text(path) -> List[str]:
    """The whole workbook as lines, each sheet after a ``=== sheet 'name' ===`` line (for people and chatbots)."""
    out: List[str] = []
    for name, lines in sheets(path).items():
        out += [f"=== sheet {name!r} ({len(lines)} rows) ===", *lines]
    return out
