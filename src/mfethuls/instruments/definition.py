"""Instrument definitions: how to read one instrument's export files, as data.

A definition is a small JSON file (see :func:`mfethuls.instruments.spec.json_schema`).
It names the instrument, says how to find the table in its files and maps
columns to physical quantities and units (:mod:`mfethuls.instruments.units`).
:class:`mfethuls.parsers.tabular.TabularParser` reads files with it; no code is
involved.

One instrument can write files in several layouts (another software version, a
CSV export next to the text export). Each layout is a *format* with its own
``file`` settings and ``columns``; every file is read with the first format whose
extension (and ``contains`` text, when given) matches it.

Nothing in a file is dropped: columns without a mapping keep their own name and
the text around the table is kept in the dataset's metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from dateutil.tz import gettz

from ..naming import file_name_problem
from . import patterns
from .units import QUANTITIES, conversion

SPEC_VERSION = 1

DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t", "whitespace": None}
DATA_ENDS = ("end_of_file", "first_non_numeric_row")
DERIVED_OPS = ("normalize_pct", "pct_of_initial", "scale", "offset", "multiply", "divide", "add_time")
# Operations combining two stored columns (``column`` and ``by``).
COLUMN_OPS = ("multiply", "divide")
# Units of the amount an ``add_time`` step adds, in milliseconds.
TIME_UNITS = {"ms": 1.0, "s": 1000.0, "min": 60_000.0, "h": 3_600_000.0}
# What a value taken from the file name or the header is stored as.
VALUE_TYPES = ("text", "number", "datetime")
LAYOUTS = ("file", "folder")
# Excel workbooks: read sheet by sheet, each row as one line of tab-separated cells.
WORKBOOK_EXTENSIONS = (".xlsx", ".xlsm")

# Lines searched for a format's ``contains`` text.
CONTAINS_LINES = 50

_NAME_RE = re.compile(r"^[a-z0-9_\-]+$")
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A time zone name like Europe/Zurich or UTC (never a path: dateutil would open it as a file).
_TIMEZONE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*$")
# Characters a file or folder name may not hold (path separators, Windows' forbidden ones, control characters).
_NOT_IN_FILE_NAMES = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Definitions are small; a bigger file is not one (and could be deeply nested JSON).
MAX_DEFINITION_BYTES = 256_000
# Characterizers a definition can ask for: the instrument type each works on and the settings it takes.
CHARACTERIZERS = {"dsc_profiling": ("dsc", {"sensitivity"}), "tga": ("tga", set())}
_PLOT_KEYS = {"x", "y", "group_by"}

_TOP_KEYS = {
    "spec_version", "name", "type", "model", "folder_name", "data_layout", "description",
    "file", "columns", "formats", "derived", "characterizer", "plot", "check", "name_from", "from_file_name", "from_sheet_name",
    "from_header", "tables",
}
NAME_FROM = ("file", "folder", "sheet")
_FORMAT_KEYS = {"label", "file", "columns"}
_FILE_KEYS = {"extensions", "encoding", "delimiter", "decimal", "header", "data_ends", "comment", "contains",
              "not_contains",
              "segment_lines", "blocks", "sheet", "duplicate_rows"}
DUPLICATE_ROWS = ("keep", "drop")
_TABLE_KEYS = {"name", "starts_at", "ends_at", "columns", "sheet", "header"}
_BLOCK_KEYS = {"starts_at", "label", "column"}
# "auto": UTF-8, else Windows cp1252 (what most instrument software writes).
AUTO_ENCODING = "auto"
_HEADER_KEYS = {"starts_at", "skip_lines", "rows", "names_from"}
_VALUE_KEYS = {"column", "pattern", "type", "values", "timezone"}

# Keys that do not change how files are read (left out of the fingerprint): renaming an
# instrument or its folder does not ask for its data to be read again.
_NOT_READING = {"description", "check", "name", "folder_name", "data_layout"}


class DefinitionError(ValueError):
    """An instrument definition is invalid; the message lists every problem."""

    def __init__(self, problems: List[str], source: Optional[str] = None):
        self.problems = problems
        self.source = source
        where = f" in {source}" if source else ""
        super().__init__(f"Invalid instrument definition{where}:\n- " + "\n- ".join(problems))


@dataclass(frozen=True)
class Blocks:
    """A file holding several tables, each starting at a line containing ``starts_at``.

    The lines after that first line are read with the format's header settings; the rows get the block's
    label in ``column``: the first group of ``label`` on the block's first line, or
    the block's number.
    """

    starts_at: str
    column: str = "block"
    label: Optional[str] = None


@dataclass(frozen=True)
class FileFormat:
    extensions: Tuple[str, ...]
    encoding: str = "utf-8"
    delimiter: str = "comma"
    decimal: str = "."
    header_starts_at: Optional[str] = None
    skip_lines: int = 0
    header_rows: int = 1
    data_ends: str = "end_of_file"
    comment: Optional[str] = None
    contains: Optional[str] = None
    # Files with this text near the top are another layout's (e.g. an older export of the same instrument).
    not_contains: Optional[str] = None
    # Text lines inside the table label the rows below them (column "segment").
    segment_lines: bool = False
    # Column names listed one per line before the table: the first group of this pattern.
    names_from: Optional[str] = None
    blocks: Optional[Blocks] = None
    # Workbooks: the sheet holding the table (name, or number: 1 = first, -1 = last).
    # Default: the first sheet containing ``header_starts_at``, else the first sheet.
    sheet: Optional[Union[int, str]] = None
    # "drop": a row equal to an earlier row of the same file in every field is left out
    # (counted in the file's notes). Rows differing in any field are always kept.
    duplicate_rows: str = "keep"

    @property
    def workbook(self) -> bool:
        """The format reads Excel workbooks (every extension is one)."""
        return all(ext in WORKBOOK_EXTENSIONS for ext in self.extensions)

    @property
    def separator(self) -> Optional[str]:
        """The delimiter character, ``None`` for any run of whitespace."""
        return DELIMITERS.get(self.delimiter, self.delimiter)


@dataclass(frozen=True)
class ColumnMapping:
    sources: Tuple[str, ...]
    quantity: Optional[str] = None
    unit: Optional[str] = None
    column: Optional[str] = None  # stored name for columns that are not a quantity


@dataclass(frozen=True)
class Format:
    """One file layout of an instrument."""

    file: FileFormat
    columns: Tuple[ColumnMapping, ...]
    label: str = ""


@dataclass(frozen=True)
class CapturedValue:
    """A column filled from the file name or the header text.

    The value is the first group of ``pattern`` (the whole match without a group),
    looked up in ``values`` when given (stored value -> pattern the capture must
    match; a capture matching none is kept as it is), then stored as ``type``.
    ``timezone`` is the zone of local date-times (``Europe/Zurich``); they are
    stored in UTC.
    """

    column: str
    pattern: str
    type: str = "text"
    values: Tuple[Tuple[str, str], ...] = ()
    timezone: Optional[str] = None


@dataclass(frozen=True)
class TextTable:
    """A second table in the text around the data (a peak list, a results block), kept as metadata.

    Its rows are the lines after the line containing ``starts_at``, up to the line
    containing ``ends_at`` (or the end of that text), that start with a number. They
    are stored in the dataset's metadata ``tables[name][file]`` as records named by
    ``columns`` (further fields: ``column_3``, ...). The lines also stay in the file text.

    With ``header_rows``, the table has its own header lines (names, then units),
    starting at the ``starts_at`` line (or the first line), and every line below
    them is a row, whatever its first field: a workbook's results sheet with one row
    per specimen. Fields are named as the data's columns are (``"sM kPa"``);
    ``columns`` names those without a header, in order. ``sheet`` (workbooks) looks
    only in that sheet.
    """

    name: str
    starts_at: Optional[str] = None
    columns: Tuple[str, ...] = ()
    ends_at: Optional[str] = None
    sheet: Optional[str] = None
    header_rows: int = 0


@dataclass(frozen=True)
class Derived:
    op: str
    column: str
    into: str
    factor: float = 1.0
    value: float = 0.0
    amount: Optional[str] = None  # add_time: the column holding the amount added
    unit: str = "ms"  # add_time: unit of that amount
    by: Optional[str] = None  # multiply / divide: the other column


@dataclass(frozen=True)
class InstrumentDefinition:
    name: str
    type: str
    model: str
    folder_name: str
    data_layout: str
    formats: Tuple[Format, ...]
    derived: Tuple[Derived, ...] = ()
    characterizer: Optional[Dict[str, Any]] = None
    plot: Optional[Dict[str, str]] = None
    description: str = ""
    check: Optional[Dict[str, Any]] = None
    name_from: str = "file"  # each file's rows are named after the file, or its folder
    from_file_name: Tuple[CapturedValue, ...] = ()
    # Workbooks: columns filled from each test sheet's name (e.g. the sample: LUB640_1 -> LUB640).
    from_sheet_name: Tuple[CapturedValue, ...] = ()
    from_header: Tuple[CapturedValue, ...] = ()
    tables: Tuple[TextTable, ...] = ()
    spec_version: int = SPEC_VERSION
    raw: Dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    source: Optional[str] = field(default=None, compare=False)

    @property
    def extensions(self) -> Tuple[str, ...]:
        """File endings of all formats, in order, without repeats."""
        return tuple(dict.fromkeys(ext for fmt in self.formats for ext in fmt.file.extensions))

    @property
    def fingerprint(self) -> str:
        """Short hash of everything that decides how files are read.

        Changes when the definition is edited in a way that can change the data
        (not for its ``description``, ``check``, ``name``, ``folder_name`` or
        ``data_layout``).
        """
        reading = {k: v for k, v in self.raw.items() if k not in _NOT_READING}
        text = json.dumps(reading, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf8")).hexdigest()[:12]

    def instrument_entry(self) -> Dict[str, Any]:
        """The instrument's entry in the instrument list (as in ``instrument_params.json``)."""
        entry = {
            "type": self.type,
            "model": self.model,
            "name": self.name,
            "folder_name": self.folder_name,
            "data_layout": self.data_layout,
            "definition": self.source or "built-in",
        }
        if self.characterizer:
            entry["characterizer"] = dict(self.characterizer)
        return entry


def _sources(value: Any) -> Tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
        return tuple(value)
    return ()


def _unknown(container: Dict[str, Any], allowed: set, where: str, problems: List[str]) -> None:
    extra = sorted(set(container) - allowed)
    if extra:
        problems.append(f"{where}unknown {'key' if len(extra) == 1 else 'keys'} {', '.join(map(repr, extra))}")


def parse_definition(data: Dict[str, Any], source: Optional[str] = None) -> InstrumentDefinition:
    """Build a definition from its JSON content, checking everything at once.

    Raises :class:`DefinitionError` with one line per problem.
    """
    problems: List[str] = []
    if not isinstance(data, dict):
        raise DefinitionError(["the file must contain one JSON object { ... }"], source)
    _unknown(data, _TOP_KEYS, "", problems)

    def text(key: str, *, required: bool = True, default: str = "") -> str:
        value = data.get(key, default)
        if value is None or value == "":
            if required:
                problems.append(f"'{key}' is missing")
            return default
        if not isinstance(value, str):
            problems.append(f"'{key}' must be text")
            return default
        return value.strip()

    version = data.get("spec_version", SPEC_VERSION)
    if version != SPEC_VERSION:
        problems.append(f"'spec_version' {version!r} is not supported (this mfethuls reads version {SPEC_VERSION})")

    name = text("name").casefold()
    if name and not _NAME_RE.match(name):
        problems.append(f"'name' {name!r} may only contain a-z, 0-9, '_' and '-'")
    type_ = text("type").casefold()
    if type_ and not _NAME_RE.match(type_):
        problems.append(f"'type' {type_!r} may only contain a-z, 0-9, '_' and '-'")
    model = text("model")
    folder_name = text("folder_name")
    if folder_name and (issue := file_name_problem(folder_name)):
        problems.append(f"'folder_name' {folder_name!r} {issue}: it is the instrument's folder in the data folder")
    data_layout = text("data_layout", required=False, default="file")
    if data_layout not in LAYOUTS:
        problems.append(f"'data_layout' must be 'file' or 'folder', not {data_layout!r}")

    formats: List[Format] = []
    if "formats" in data:
        if "file" in data or "columns" in data:
            problems.append("give either 'file' and 'columns' (one layout) or 'formats' (several), not both")
        raw_formats = data["formats"]
        if not isinstance(raw_formats, list) or not raw_formats:
            problems.append("'formats' must list at least one format")
            raw_formats = []
        for i, item in enumerate(raw_formats, start=1):
            if not isinstance(item, dict):
                problems.append(f"format {i} must be an object with 'file' and 'columns'")
                continue
            _unknown(item, _FORMAT_KEYS, f"format {i}: ", problems)
            fmt = _parse_format(item, type_, f"format {i}: ", problems)
            formats.append(Format(fmt[0], fmt[1], str(item.get("label") or f"format {i}")))
    else:
        file_format, columns = _parse_format(data, type_, "", problems)
        formats.append(Format(file_format, columns))

    derived = [d for i, item in enumerate(data.get("derived") or [], start=1)
               if (d := _parse_derived(item, i, problems)) is not None]

    characterizer = data.get("characterizer")
    if characterizer is not None:
        if not (isinstance(characterizer, dict) and characterizer.get("type") in CHARACTERIZERS):
            problems.append(f"'characterizer' must be an object with a 'type' ({', '.join(CHARACTERIZERS)})")
        else:
            works_on, settings = CHARACTERIZERS[characterizer["type"]]
            if type_ and type_ != works_on:
                problems.append(f"'characterizer' {characterizer['type']!r} works on {works_on} data, not {type_}")
            _unknown(characterizer, {"type"} | settings, "characterizer: ", problems)
            sensitivity = characterizer.get("sensitivity", 0.1)
            if not (isinstance(sensitivity, (int, float)) and not isinstance(sensitivity, bool) and sensitivity > 0):
                problems.append("'characterizer.sensitivity' must be a number > 0")

    plot = data.get("plot")
    if plot is not None:
        if not (isinstance(plot, dict) and isinstance(plot.get("x"), str) and isinstance(plot.get("y"), str)
                and isinstance(plot.get("group_by", ""), str)):
            problems.append("'plot' must name an 'x' and a 'y' column")
        else:
            _unknown(plot, _PLOT_KEYS, "plot: ", problems)

    check = data.get("check")
    if check is not None:
        if not (isinstance(check, dict) and isinstance(check.get("sample"), str)):
            problems.append("'check' must name a 'sample' file")
        elif issue := file_name_problem(check["sample"]):
            problems.append(f"'check.sample' {check['sample']!r} {issue}: it is a file next to the definition")

    name_from = data.get("name_from", "file")
    if name_from not in NAME_FROM:
        problems.append(f"'name_from' must be 'file', 'folder' or 'sheet' (workbooks), not {name_from!r}")
        name_from = "file"

    from_file_name = _parse_values(data, "from_file_name", problems)
    from_sheet_name = _parse_values(data, "from_sheet_name", problems)
    if from_sheet_name and not any(f.file.workbook for f in formats):
        problems.append("'from_sheet_name' only goes with workbooks (.xlsx): their tests are on named sheets")
    from_header = _parse_values(data, "from_header", problems)
    captured = [v.column for v in (*from_file_name, *from_sheet_name, *from_header)]
    for column in sorted({c for c in captured if captured.count(c) > 1}):
        problems.append(f"the column {column!r} is filled twice by from_file_name / from_sheet_name / from_header")

    tables = _parse_tables(data.get("tables"), problems, workbooks=any(f.file.workbook for f in formats))

    if problems:
        raise DefinitionError(problems, source)

    return InstrumentDefinition(
        name=name,
        type=type_,
        model=model,
        folder_name=folder_name,
        data_layout=data_layout,
        formats=tuple(formats),
        derived=tuple(derived),
        characterizer=dict(characterizer) if characterizer else None,
        plot=dict(plot) if plot else None,
        description=str(data.get("description") or ""),
        check=dict(check) if check else None,
        name_from=name_from,
        from_file_name=tuple(from_file_name),
        from_sheet_name=tuple(from_sheet_name),
        from_header=tuple(from_header),
        tables=tables,
        raw=json.loads(json.dumps(data)),
        source=source,
    )


def _parse_values(data: Dict[str, Any], key: str, problems: List[str]) -> Tuple[CapturedValue, ...]:
    """``from_file_name`` or ``from_header``: columns filled from a pattern."""
    raw_values = data.get(key) or []
    if not isinstance(raw_values, list):
        problems.append(f"'{key}' must be a list of {{\"column\": ..., \"pattern\": ...}}")
        return ()
    out: List[CapturedValue] = []
    for i, item in enumerate(raw_values, start=1):
        where = f"{key} {i}"
        if not (isinstance(item, dict) and isinstance(item.get("column"), str) and _COLUMN_RE.match(item["column"])
                and isinstance(item.get("pattern"), str)):
            problems.append(f"{where}: needs a simple 'column' name and a 'pattern'")
            continue
        where = f"{key} {i} ({item['column']})"
        _unknown(item, _VALUE_KEYS, f"{where}: ", problems)
        if issue := patterns.problem(item["pattern"]):
            problems.append(f"{where}: 'pattern' {issue}")
            continue
        type_ = item.get("type", "text")
        if type_ not in VALUE_TYPES:
            problems.append(f"{where}: 'type' must be one of {', '.join(VALUE_TYPES)}")
            continue
        values = item.get("values") or {}
        if not (isinstance(values, dict) and all(isinstance(k, str) and k and isinstance(v, str) and v
                                                 for k, v in values.items())):
            problems.append(f"{where}: 'values' must map each stored value to a pattern, "
                            "e.g. {\"ri\": \"RID|RI\"}")
            continue
        bad = [f"the 'values' pattern of {k!r} {issue}" for k, v in values.items() if (issue := patterns.problem(v))]
        if bad:
            problems.extend(f"{where}: {issue}" for issue in bad)
            continue
        timezone = item.get("timezone")
        if timezone is not None:
            if type_ != "datetime":
                problems.append(f"{where}: 'timezone' only goes with type datetime")
                continue
            if not (isinstance(timezone, str) and _TIMEZONE_RE.match(timezone) and _known_zone(timezone)):
                problems.append(f"{where}: 'timezone' {timezone!r} is not a known time zone, e.g. Europe/Zurich")
                continue
        out.append(CapturedValue(item["column"], item["pattern"], type_, tuple(values.items()), timezone))
    return tuple(out)


def _parse_tables(raw: Any, problems: List[str], workbooks: bool = False) -> Tuple[TextTable, ...]:
    """``tables``: second tables in the text around the data, kept as metadata."""
    if raw is None:
        return ()
    example = '{"name": "peak_list", "starts_at": "MS Peak List", "ends_at": "End", "columns": ["mz", "intensity"]}'
    if not isinstance(raw, list):
        problems.append(f"'tables' must be a list like [{example}]")
        return ()
    out: List[TextTable] = []
    for i, item in enumerate(raw, start=1):
        where = f"tables {i}"
        if not (isinstance(item, dict) and isinstance(item.get("name"), str) and _COLUMN_RE.match(item["name"])):
            problems.append(f"{where}: needs a simple 'name' (letters, digits, _), e.g. {example}")
            continue
        where = f"tables {i} ({item['name']})"
        _unknown(item, _TABLE_KEYS, f"{where}: ", problems)
        starts_at, ends_at, columns = item.get("starts_at"), item.get("ends_at"), item.get("columns", [])
        sheet, header = item.get("sheet"), item.get("header")
        header_rows = 0
        if header is not None:
            if not (isinstance(header, dict) and set(header) <= {"rows"} and header.get("rows") in (1, 2, 3)):
                problems.append(f"{where}: 'header' must be {{\"rows\": 1}} (names) or {{\"rows\": 2}} (names, then units)")
                continue
            header_rows = header["rows"]
        if sheet is not None:
            if not (isinstance(sheet, str) and sheet.strip()):
                problems.append(f"{where}: 'sheet' must be the sheet's name, e.g. \"Results\"")
                continue
            if not workbooks:
                problems.append(f"{where}: 'sheet' only goes with workbooks (.xlsx)")
                continue
        if starts_at is None and not (sheet and header_rows):
            problems.append(f"{where}: 'starts_at' must be text on the line before the table's rows "
                            "(or on its header line); a table with a 'sheet' and a 'header' needs none")
            continue
        if starts_at is not None and not (isinstance(starts_at, str) and starts_at.strip()):
            problems.append(f"{where}: 'starts_at' must be text on the line before the table's rows")
            continue
        if ends_at is not None and not (isinstance(ends_at, str) and ends_at.strip()):
            problems.append(f"{where}: 'ends_at' must be text on the line after the table's rows")
            continue
        if not (isinstance(columns, list) and all(isinstance(c, str) and _COLUMN_RE.match(c) for c in columns)):
            problems.append(f"{where}: 'columns' must list simple names for the fields, e.g. [\"mz\", \"intensity\"]")
            continue
        if any(t.name == item["name"] for t in out):
            problems.append(f"{where}: another table has this name")
            continue
        out.append(TextTable(item["name"], starts_at, tuple(columns), ends_at, sheet, header_rows))
    return tuple(out)


def _known_zone(name: str) -> bool:
    try:
        return gettz(name) is not None
    except (ValueError, OSError):
        return False


def _parse_format(data: Dict[str, Any], type_: str, where: str,
                  problems: List[str]) -> Tuple[FileFormat, Tuple[ColumnMapping, ...]]:
    file_data = data.get("file")
    if not isinstance(file_data, dict):
        problems.append(f"{where}'file' is missing: it says how to read the table out of the files")
        file_data = {}
    file_format = _parse_file(file_data, where, problems)

    columns: List[ColumnMapping] = []
    raw_columns = data.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        problems.append(f"{where}'columns' must list at least one column")
        raw_columns = []
    stored: Dict[str, int] = {}
    for i, item in enumerate(raw_columns, start=1):
        mapping = _parse_column(item, i, type_, where, problems)
        if mapping is None:
            continue
        columns.append(mapping)
        target = mapping.column or QUANTITIES[mapping.quantity].target(type_, mapping.unit)[0]
        if target in stored:
            problems.append(f"{where}columns {stored[target]} and {i} are both stored as {target!r}")
        stored.setdefault(target, i)
    return file_format, tuple(columns)


def _parse_file(data: Dict[str, Any], where: str, problems: List[str]) -> FileFormat:
    _unknown(data, _FILE_KEYS, f"{where}file: ", problems)
    extensions = data.get("extensions")
    if isinstance(extensions, str):
        extensions = [extensions]
    if not (isinstance(extensions, list) and extensions and all(isinstance(e, str) and e for e in extensions)):
        problems.append(f"{where}'file.extensions' must list the file endings, e.g. [\".csv\"]")
        extensions = [".txt"]
    extensions = tuple(e if e.startswith(".") else f".{e}" for e in (x.strip().casefold() for x in extensions))

    encoding = data.get("encoding", "utf-8")
    if encoding != AUTO_ENCODING:
        try:
            "".encode(encoding)
        except (LookupError, TypeError):
            problems.append(f"{where}'file.encoding' {encoding!r} is not a known text encoding "
                            "(try auto, utf-8 or cp1252)")
            encoding = "utf-8"

    segment_lines = data.get("segment_lines", False)
    if not isinstance(segment_lines, bool):
        problems.append(f"{where}'file.segment_lines' must be true or false")
        segment_lines = False

    delimiter = data.get("delimiter", "comma")
    if not (isinstance(delimiter, str) and (delimiter in DELIMITERS or len(delimiter) == 1)):
        problems.append(
            f"{where}'file.delimiter' must be one of {', '.join(DELIMITERS)} or a single character, "
            f"not {delimiter!r}"
        )
        delimiter = "comma"

    decimal = data.get("decimal", ".")
    if decimal not in (".", ","):
        problems.append(f"{where}'file.decimal' must be \".\" or \",\"")
        decimal = "."
    if decimal == "," and delimiter in ("comma", ","):
        problems.append(f"{where}'file.decimal' \",\" needs a 'file.delimiter' other than comma")

    header = data.get("header", {})
    if not isinstance(header, dict):
        problems.append(f"{where}'file.header' must be an object like {{\"starts_at\": \"Index\", \"rows\": 2}}")
        header = {}
    _unknown(header, _HEADER_KEYS, f"{where}file.header: ", problems)
    starts_at = header.get("starts_at")
    if starts_at is not None and not (isinstance(starts_at, str) and starts_at.strip()):
        problems.append(f"{where}'file.header.starts_at' must be text found in the header line")
        starts_at = None
    skip_lines = header.get("skip_lines", 0)
    if not (isinstance(skip_lines, int) and not isinstance(skip_lines, bool) and skip_lines >= 0):
        problems.append(f"{where}'file.header.skip_lines' must be a whole number ≥ 0")
        skip_lines = 0
    rows = header.get("rows", 1)
    if rows not in (0, 1, 2):
        problems.append(f"{where}'file.header.rows' must be 0 (no header), 1 or 2 (names, then units)")
        rows = 1
    names_from = header.get("names_from")
    if names_from is not None:
        if issue := patterns.problem(names_from, groups=1):
            problems.append(f"{where}'file.header.names_from' must be a regular expression with one group, "
                            f"e.g. \"^Sig\\\\d+\\\\t(.+)$\"; this one {issue}")
            names_from = None
        elif rows != 0:
            problems.append(f"{where}'file.header.names_from' lists the column names before the table; "
                            "set 'file.header.rows' to 0")

    data_ends = data.get("data_ends", "end_of_file")
    if not (isinstance(data_ends, str) and data_ends.strip()):
        problems.append(f"{where}'file.data_ends' must be {' or '.join(DATA_ENDS)} or text that marks the end")
        data_ends = "end_of_file"

    comment = data.get("comment")
    if comment is not None and not (isinstance(comment, str) and comment):
        problems.append(f"{where}'file.comment' must be the text that starts a comment line, e.g. \"#\"")
        comment = None

    contains = data.get("contains")
    if contains is not None and not (isinstance(contains, str) and contains.strip()):
        problems.append(f"{where}'file.contains' must be text found near the top of this layout's files")
        contains = None
    not_contains = data.get("not_contains")
    if not_contains is not None and not (isinstance(not_contains, str) and not_contains.strip()):
        problems.append(f"{where}'file.not_contains' must be text found near the top of other layouts' files only")
        not_contains = None

    blocks = data.get("blocks")
    if blocks is not None:
        blocks = _parse_blocks(blocks, where, problems)

    sheet = data.get("sheet")
    workbook = all(ext in WORKBOOK_EXTENSIONS for ext in extensions)
    if workbook:
        # A workbook's rows are read as lines of tab-separated cells; numbers are already numbers.
        if "delimiter" in data and delimiter not in ("tab", "\t"):
            problems.append(f"{where}workbooks (.xlsx) are read as tab-separated cells: leave out "
                            "'file.delimiter' or set it to tab")
        if "decimal" in data and decimal != ".":
            problems.append(f"{where}workbooks (.xlsx) hold numbers, not text: leave out 'file.decimal'")
        delimiter, decimal = "tab", "."
    elif any(ext in WORKBOOK_EXTENSIONS for ext in extensions):
        problems.append(f"{where}'file.extensions' mixes workbooks (.xlsx) with text files; "
                        "use one format for each (see 'formats')")
    if sheet is not None:
        if not workbook:
            problems.append(f"{where}'file.sheet' only goes with workbooks (.xlsx)")
            sheet = None
        elif not ((isinstance(sheet, str) and sheet.strip())
                  or (isinstance(sheet, int) and not isinstance(sheet, bool) and sheet != 0)):
            problems.append(f"{where}'file.sheet' must be the sheet's name or its number (1 = first, -1 = last)")
            sheet = None

    duplicate_rows = data.get("duplicate_rows", "keep")
    if duplicate_rows not in DUPLICATE_ROWS:
        problems.append(f"{where}'file.duplicate_rows' must be keep or drop (rows repeating an earlier row "
                        "in every field)")
        duplicate_rows = "keep"

    return FileFormat(
        extensions=extensions,
        encoding=encoding,
        delimiter=delimiter,
        decimal=decimal,
        header_starts_at=starts_at,
        skip_lines=skip_lines,
        header_rows=rows,
        data_ends=data_ends,
        comment=comment,
        contains=contains,
        not_contains=not_contains,
        segment_lines=segment_lines,
        names_from=names_from,
        blocks=blocks,
        sheet=sheet,
        duplicate_rows=duplicate_rows,
    )


def _parse_blocks(data: Any, where: str, problems: List[str]) -> Optional[Blocks]:
    if not isinstance(data, dict):
        problems.append(f"{where}'file.blocks' must be an object like "
                        "{\"starts_at\": \"Interval and data points:\", \"column\": \"interval\"}")
        return None
    _unknown(data, _BLOCK_KEYS, f"{where}file.blocks: ", problems)
    starts_at, column, label = data.get("starts_at"), data.get("column", "block"), data.get("label")
    if not (isinstance(starts_at, str) and starts_at.strip()):
        problems.append(f"{where}'file.blocks.starts_at' must be text found on the first line of every block")
        return None
    if not (isinstance(column, str) and _COLUMN_RE.match(column)):
        problems.append(f"{where}'file.blocks.column' must be a simple name like interval")
        return None
    if label is not None and (issue := patterns.problem(label, groups=1)):
        problems.append(f"{where}'file.blocks.label' must be a regular expression with one group, "
                        f"matched on the block's first line; this one {issue}")
        return None
    return Blocks(starts_at, column, label)


def _parse_column(item: Any, i: int, type_: str, prefix: str, problems: List[str]) -> Optional[ColumnMapping]:
    where = f"{prefix}column {i}"
    if not isinstance(item, dict):
        problems.append(
            f"{where} must be an object like {{\"source\": \"Weight [mg]\", \"quantity\": \"mass\", \"unit\": \"mg\"}}"
        )
        return None
    sources = _sources(item.get("source"))
    if not sources:
        problems.append(f"{where}: 'source' must be the column name in the file (or a list of names)")
        return None
    where = f"{prefix}column {i} ({sources[0]!r})"
    _unknown(item, {"source", "quantity", "unit", "column"}, f"{where}: ", problems)
    quantity, column, unit = item.get("quantity"), item.get("column"), item.get("unit")
    if (quantity is None) == (column is None):
        problems.append(f"{where}: give either a 'quantity' (with its 'unit') or a 'column' name, not both")
        return None
    if column is not None:
        if not (isinstance(column, str) and _COLUMN_RE.match(column)):
            problems.append(f"{where}: 'column' must be a simple name like detector_name")
            return None
        if unit is not None:
            problems.append(f"{where}: 'unit' only goes with a 'quantity'")
            return None
        return ColumnMapping(sources, column=column)
    if quantity not in QUANTITIES:
        problems.append(f"{where}: unknown quantity {quantity!r}; use one of {', '.join(sorted(QUANTITIES))}")
        return None
    if unit is not None and not isinstance(unit, str):
        problems.append(f"{where}: 'unit' must be text")
        return None
    try:
        conversion(QUANTITIES[quantity], unit, type_)
    except ValueError as exc:
        problems.append(f"{where}: {exc}")
        return None
    return ColumnMapping(sources, quantity=quantity, unit=unit)


def _parse_derived(item: Any, i: int, problems: List[str]) -> Optional[Derived]:
    where = f"derived {i}"
    if not isinstance(item, dict) or item.get("op") not in DERIVED_OPS:
        problems.append(f"{where}: 'op' must be one of {', '.join(DERIVED_OPS)}")
        return None
    _unknown(item, {"op", "column", "into", "factor", "value", "amount", "unit", "by"}, f"{where}: ", problems)
    op, column, into = item["op"], item.get("column"), item.get("into")
    if not (isinstance(column, str) and column):
        problems.append(f"{where}: 'column' must name the stored column it works on, e.g. mass_mg")
        return None
    if not (isinstance(into, str) and _COLUMN_RE.match(into)):
        problems.append(f"{where}: 'into' must name the new column (the original data is never changed)")
        return None
    if into == column:
        problems.append(f"{where}: 'into' must differ from 'column' (the original data is never changed)")
        return None
    amount, unit = item.get("amount"), item.get("unit", "ms")
    if op == "add_time":
        if not (isinstance(amount, str) and amount):
            problems.append(f"{where}: add_time needs 'amount', the column holding the time to add")
            return None
        if unit not in TIME_UNITS:
            problems.append(f"{where}: 'unit' of the amount must be one of {', '.join(TIME_UNITS)}")
            return None
    elif amount is not None or "unit" in item:
        problems.append(f"{where}: 'amount' and 'unit' only go with add_time")
        return None
    by = item.get("by")
    if op in COLUMN_OPS:
        if not (isinstance(by, str) and by):
            problems.append(f"{where}: {op} needs 'by', the stored column to {op} by, e.g. sample_mass_mg")
            return None
    elif by is not None:
        problems.append(f"{where}: 'by' only goes with {' and '.join(COLUMN_OPS)}")
        return None
    number_key = {"scale": "factor", "offset": "value"}.get(op)
    number = item.get(number_key) if number_key else None
    if number_key and not (isinstance(number, (int, float)) and not isinstance(number, bool)):
        problems.append(f"{where}: {op} needs a number '{number_key}'")
        return None
    return Derived(
        op=op,
        column=column,
        into=into,
        factor=float(number) if op == "scale" else 1.0,
        value=float(number) if op == "offset" else 0.0,
        amount=amount if op == "add_time" else None,
        unit=unit if op == "add_time" else "ms",
        by=by if op in COLUMN_OPS else None,
    )


def definition_json(text: str, source: Optional[str] = None) -> Any:
    """The JSON content of a definition's text (a file, or an answer pasted into the app)."""
    if len(text.encode("utf8")) > MAX_DEFINITION_BYTES:
        raise DefinitionError([_TOO_BIG], source)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise DefinitionError([f"not valid JSON: {exc}"], source) from None
    except RecursionError:
        raise DefinitionError(["not valid JSON: it is nested too deeply"], source) from None


_TOO_BIG = f"it is larger than {MAX_DEFINITION_BYTES // 1000} kB; definitions are much smaller"


def load_definition(path: Union[str, Path]) -> InstrumentDefinition:
    """Read and check one definition file."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_DEFINITION_BYTES:
            raise DefinitionError([_TOO_BIG], str(path))
        text = path.read_text(encoding="utf8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DefinitionError([f"cannot be read: {exc}"], str(path)) from None
    return parse_definition(definition_json(text, str(path)), source=str(path))


BUILTIN_DIR = Path(__file__).resolve().parent.parent / "config" / "instruments"


def builtin_definitions() -> List[InstrumentDefinition]:
    """Definitions shipped with mfethuls (``config/instruments/*.json``)."""
    return [load_definition(path) for path in sorted(BUILTIN_DIR.glob("*.json"))]
