"""Guess an instrument definition from one of its files, without any AI.

:func:`detect` looks at a sample file and proposes the ``file`` settings
(encoding, delimiter, decimal mark, where the header and data are) and, for each
column, a quantity and unit. The guesses come from the shape of the file, the
column names the built-in instruments already know (``config/schemas``) and the
units written in the column names. The user checks and corrects them; nothing
is saved from here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import workbook
from .definition import FileFormat, parse_definition
from .units import QUANTITIES, conversion, normalize_unit

ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
# Lines looked at to find the table; files are often much longer.
SCAN_LINES = 2000

_UNIT_RE = re.compile(r"^(?P<base>.*?)\s*[\[(](?P<unit>[^\])]*)[\])]\s*$")

# Words in a column name that point at a quantity (checked in this order).
_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("sample_temperature", ("sample temperature", "sample temp", "ts")),
    ("temperature", ("temperature", "temp", "tr", "t_ref", "program temperature")),
    ("retention_time", ("retention time", "retention")),
    ("time", ("time", "t", "elapsed")),
    ("mass_loss_rate", ("dtg", "dw/dt", "derivative weight")),
    ("mass_loss", ("mass loss", "weight loss")),
    ("mass", ("mass", "weight", "m")),
    ("heat_flow", ("heat flow", "heatflow", "hf")),
    ("wavenumber", ("wavenumber", "wave number")),
    ("wavelength", ("wavelength", "lambda", "λ")),
    ("absorbance", ("absorbance", "abs", "abs.")),
    ("transmittance", ("transmittance", "transmission", "%t")),
    ("chemical_shift", ("chemical shift", "ppm", "δ")),
    ("mz", ("m/z", "mz", "mass/charge")),
    ("angular_frequency", ("angular frequency", "ω", "omega", "w")),
    ("frequency", ("frequency", "freq", "f")),
    ("strain", ("strain", "γ", "gamma")),
    ("storage_modulus", ("storage modulus", "g'", "e'")),
    ("loss_modulus", ("loss modulus", "g''", "e''")),
    ("tan_delta", ("tan delta", "tan δ", "tan d")),
    ("shear_rate", ("shear rate", "γ̇")),
    ("shear_stress", ("shear stress", "shearing stress", "τ")),
    ("displacement", ("displacement", "extension", "elongation", "deformation", "travel")),
    ("force", ("force", "load")),
    ("stress", ("stress", "tensile stress", "σ")),
    ("strain", ("elongation", "tensile strain")),
    ("viscosity", ("viscosity", "η", "eta")),
    ("q", ("q", "scattering vector")),
    ("intensity_error", ("intensity error", "di", "sigma", "error")),
    ("intensity", ("intensity", "i", "counts", "signal")),
    ("detector_response", ("detector response", "response")),
)

# A unit alone that points at one quantity.
_UNIT_QUANTITY = {
    "C": "temperature", "K": "temperature", "F": "temperature",
    "mg": "mass", "g": "mass", "ug": "mass",
    "mW": "heat_flow", "W": "heat_flow", "uW": "heat_flow",
    "W/g": "specific_heat_flow", "invWg": "specific_heat_flow", "mW/mg": "specific_heat_flow",
    "s": "time", "min": "time", "h": "time",
    "nm": "wavelength", "invcm": "wavenumber", "invnm": "q", "invÅ": "q",
    "Hz": "frequency", "rad/s": "angular_frequency", "ppm": "chemical_shift",
    "%/min": "mass_loss_rate", "Pas": "viscosity", "mPas": "viscosity", "invs": "shear_rate",
    "mm": "displacement", "N": "force", "kN": "force", "kPa": "stress", "MPa": "stress",
}


@dataclass
class ColumnGuess:
    source: str
    quantity: Optional[str] = None
    unit: Optional[str] = None
    how: str = ""  # "known name", "name and unit", "unit", or "" when nothing fits


@dataclass
class Detection:
    """What :func:`detect` found: definition parts, column guesses and notes for the user."""

    file: Dict[str, Any]
    columns: List[ColumnGuess]
    notes: List[str] = field(default_factory=list)
    type_guess: Optional[str] = None
    header_line: Optional[int] = None  # 0-based line of the (first) header line
    data_lines: Tuple[int, int] = (0, 0)  # first and last 0-based data line
    outline: List[str] = field(default_factory=list)  # the whole file's parts, see :func:`outline`
    name_from: Optional[str] = None  # "sheet" for workbooks with one test per sheet

    def column_mappings(self) -> List[Dict[str, Any]]:
        """``columns`` of a definition: only the columns with a guess."""
        out = []
        for guess in self.columns:
            if guess.quantity:
                item = {"source": guess.source, "quantity": guess.quantity}
                if guess.unit is not None:
                    item["unit"] = guess.unit
                out.append(item)
        return out

    def summary(self) -> str:
        """What was detected, as text for a chatbot (to start from facts, not guesses)."""
        lines = ["mfethuls' own reading of the file (check it; correct it where it is wrong):",
                 f"- file settings: {json.dumps(self.file, ensure_ascii=False)}"]
        lines += [f"- {note}" for note in self.notes]
        if self.outline:
            lines.append("- the whole file, part by part:")
            lines += [f"  {part}" for part in self.outline]
        for guess in self.columns:
            what = f"{guess.quantity} ({guess.unit or 'standard unit'})" if guess.quantity else "not recognised"
            lines.append(f"- column {guess.source!r}: {what}")
        if self.type_guess:
            lines.append(f"- looks like measurement type {self.type_guess!r}")
        return "\n".join(lines)

    def definition(self, **identity: Any) -> Dict[str, Any]:
        """A definition draft: ``identity`` (name, type, model, ...) plus what was detected."""
        draft = {"spec_version": 1, **identity, "file": dict(self.file), "columns": self.column_mappings()}
        if self.name_from and "name_from" not in identity:
            draft["name_from"] = self.name_from
        return draft


def _read_text(path) -> Tuple[str, str]:
    raw = Path(path).read_bytes()
    for encoding in ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        # utf-8-sig only when there is a byte order mark; otherwise call it utf-8.
        if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8"
        return text, encoding
    raise ValueError("unreadable")  # latin-1 decodes everything; never reached


def _detect_text(path) -> Tuple[str, str, Optional[str]]:
    """The text to detect a table in, its encoding, and for workbooks the sheet holding the table.

    A workbook's table is the one most of its numbers are in: sheets holding the same
    table (same width, same line above the numbers, e.g. one test per sheet) count
    together, so many short tests beat one summary table. Its first sheet is returned.
    """
    if workbook.is_workbook(path):
        groups: Dict[Tuple[int, str], List[str]] = {}
        sizes: Counter = Counter()
        for name, lines in workbook.sheets(path).items():
            try:
                _, _, start, end, width = _best_block(lines[:SCAN_LINES])
            except ValueError:
                continue
            key = (width, lines[start - 1].strip() if start else "")
            groups.setdefault(key, []).append(name)
            sizes[key] += (end - start) * width
        if not sizes:
            raise ValueError("no sheet of the workbook holds a table of numbers")
        best = groups[sizes.most_common(1)[0][0]][0]
        return "\n".join(workbook.sheets(path)[best]), "utf-8", best
    if workbook.is_binary(path):
        raise ValueError(f"{Path(path).name} is not a text file. mfethuls reads text exports (.txt, .csv, ...) "
                         "and Excel workbooks (.xlsx); export the data as one of those.")
    text, encoding = _read_text(path)
    return text, encoding, None


def _fields(line: str, delimiter: str, decimal: str) -> Tuple[int, int, int]:
    """(field count, numeric fields, first field numeric) of ``line``."""
    from mfethuls.parsers.tabular import _is_number, _split

    fmt = FileFormat(extensions=(".x",), delimiter=delimiter, decimal=decimal)
    fields = _split(line, fmt)
    numeric = [bool(f.strip()) and _is_number(f, fmt) for f in fields]
    return len(fields), sum(numeric), int(bool(numeric and numeric[0]))


def _best_block(lines: List[str]) -> Tuple[str, str, int, int, int]:
    """Delimiter, decimal mark and the longest block of numeric rows: (start, end, width).

    A row counts when it has two or more fields, at least 60 % of them numbers.
    Among readings that find equally long blocks, the one with more numeric cells
    wins (so ``1,5;2,5`` is semicolons with decimal commas, not commas).
    """
    best = None
    for delimiter in ("tab", "semicolon", "comma", "whitespace"):
        for decimal in (".", ","):
            if decimal == "," and delimiter == "comma":
                continue
            start = run = cells = numbers = 0
            width = None
            for i, line in enumerate(lines + [""]):
                count, numeric, _ = _fields(line, delimiter, decimal) if line.strip() else (0, 0, 0)
                is_data = count >= 2 and numeric >= max(2, 0.6 * count)
                if is_data and run and count == width:
                    run, cells, numbers = run + 1, cells + count, numbers + numeric
                    continue
                if run:
                    score = (run, round(numbers / cells, 2), width, decimal == ".")
                    if best is None or score > best[0]:
                        best = (score, delimiter, decimal, start, start + run - 1, width)
                run = 0
                if is_data:
                    start, width, run, cells, numbers = i, count, 1, count, numeric
    if best is None:
        raise ValueError("no table of numbers found: at least two rows of two or more numbers are needed")
    _, delimiter, decimal, start, end, width = best
    return delimiter, decimal, start, end, width


def outline(lines: List[str], delimiter: str, decimal: str, *, max_parts: int = 14) -> List[str]:
    """The file part by part: text lines and blocks of numbers, with line numbers.

    Describes the shape of the whole file without its data, so a footer, a results
    block or a second table further down is visible. Blank lines do not split parts;
    one-line text parts show their start (up to 40 characters).
    """
    from mfethuls.parsers.tabular import _is_number, _split

    fmt = FileFormat(extensions=(".x",), delimiter=delimiter, decimal=decimal)
    parts: List[List[Any]] = []  # [kind, width, first line, last line, count]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        fields = _split(line, fmt)
        numeric = sum(1 for f in fields if f.strip() and _is_number(f, fmt))
        if len(fields) >= 2 and numeric >= max(2, 0.6 * len(fields)) or (len(fields) == 1 and numeric == 1):
            kind, width = "numbers", len(fields)
        else:
            kind, width = "text", 0
        if parts and parts[-1][0] == kind and parts[-1][1] == width:
            parts[-1][3] = number
            parts[-1][4] += 1
        else:
            parts.append([kind, width, number, number, 1])

    def describe(part) -> str:
        kind, width, first, last, count = part
        where = f"line {first}" if first == last else f"lines {first}–{last}"
        if kind == "numbers":
            return f"{where}: numbers in {width} column{'s' if width != 1 else ''} ({count} rows)"
        if count == 1:
            return f"{where}: text, starting {lines[first - 1].strip()[:40]!r}"
        return f"{where}: text ({count} lines)"

    described = [describe(p) for p in parts]
    total = f"The file has {len(lines)} lines:"
    if len(described) > max_parts:
        head, tail = described[: max_parts // 2], described[-(max_parts // 2 - 1):]
        described = head + [f"… {len(parts) - len(head) - len(tail)} more parts …"] + tail
    return [total, *described]


@lru_cache(maxsize=1)
def _known_units() -> set:
    """Every unit a quantity accepts, spelling-tolerant (``mm``, ``MPa``, ``°C``)."""
    return {normalize_unit(u) for q in QUANTITIES.values() for u in q.unit_names() if u} | set(_UNIT_QUANTITY)


def _looks_like_units(fields: List[str]) -> bool:
    """A line of units: in brackets (``[mg]``) or bare known units (``mm``, ``MPa``)."""
    filled = [f.strip() for f in fields if f.strip()]
    units = sum(bool(re.fullmatch(r"[\[(].*[\])]", f)) or normalize_unit(f) in _known_units() for f in filled)
    return bool(filled) and units >= len(filled) / 2


def _header(lines: List[str], start: int, delimiter: str, decimal: str, width: int) -> Tuple[Optional[int], int]:
    """(first header line, header rows) just above the data block."""
    from mfethuls.parsers.tabular import _split

    fmt = FileFormat(extensions=(".x",), delimiter=delimiter, decimal=decimal)
    above = [i for i in range(start - 1, -1, -1) if lines[i].strip()][:2]
    if not above:
        return None, 0
    first = above[0]
    fields = _split(lines[first], fmt)
    count, numeric, _ = _fields(lines[first], delimiter, decimal)
    if numeric >= max(1, count // 2) or count < max(2, width // 2):
        return None, 0
    if _looks_like_units(fields) and len(above) > 1:
        second = above[1]
        names_count, names_numeric, _ = _fields(lines[second], delimiter, decimal)
        filled = len([f for f in fields if f.strip()])
        names_filled = len([f for f in _split(lines[second], fmt) if f.strip()])
        # Bare units ("mm", "MPa") need a name above each; a title line above names like "cm-1" is no header.
        bracketed = any(re.fullmatch(r"[\[(].*[\])]", f.strip()) for f in fields if f.strip())
        if names_numeric == 0 and names_count >= count // 2 and (bracketed or names_filled == filled):
            return second, 2
    return first, 1


@lru_cache(maxsize=1)
def _known_names() -> Dict[str, Counter]:
    """Column name (case-folded) -> Counter of (type, stored column) it is read as.

    The names the built-in definitions read (and the stored names themselves); placeholder
    names of files without a header (``column_1``) say nothing and are left out.
    """
    from mfethuls.instruments.definition import builtin_definitions

    names: Dict[str, Counter] = {}
    for definition in builtin_definitions():
        for fmt in definition.formats:
            for mapping in fmt.columns:
                stored = mapping.column or QUANTITIES[mapping.quantity].target(definition.type, mapping.unit)[0]
                for name in (stored, *mapping.sources):
                    if not re.fullmatch(r"column_\d+", name):
                        names.setdefault(name.strip().casefold(), Counter())[(definition.type, stored)] += 1
    return names


def _stored_to_quantity() -> Dict[str, str]:
    out = {}
    for quantity in QUANTITIES.values():
        for column in quantity.columns():
            out[column] = quantity.name
    return out


def _unit_fits(quantity: str, unit: Optional[str]) -> bool:
    try:
        conversion(QUANTITIES[quantity], unit)
    except ValueError:
        return False
    return True


def _split_unit(name: str) -> Tuple[str, Optional[str]]:
    match = _UNIT_RE.match(name.strip())
    if not match:
        # A unit line joined without brackets: "Strain mm", "Shearing stress MPa".
        base, _, last = name.strip().rpartition(" ")
        if base and normalize_unit(last) in _known_units():
            return base.strip(), last
        return name.strip(), None
    unit = match.group("unit").strip()
    return match.group("base").strip(), unit or None


def _canonical_unit(quantity: str, unit: Optional[str]) -> Optional[str]:
    """The unit as the quantity's table spells it (``degC`` -> ``°C``), or None."""
    if unit is None:
        return None
    wanted = normalize_unit(unit)
    for name in QUANTITIES[quantity].unit_names():
        if normalize_unit(name) == wanted:
            return name
    return None


def guess_column(name: str, taken: set) -> ColumnGuess:
    """Quantity and unit for a column called ``name``; ``taken`` quantities are not reused."""
    base, unit = _split_unit(name)
    stored_quantity = _stored_to_quantity()

    # A name that is exactly a common word ("Time", "Tr", "q") means that quantity,
    # even where one instrument uses it for something narrower (SEC's "Time (min)").
    words = base.strip().casefold()
    for quantity, keywords in _KEYWORDS:
        if quantity not in taken and words in keywords and (unit is None or _unit_fits(quantity, unit)):
            return ColumnGuess(name, quantity, _canonical_unit(quantity, unit), "name and unit" if unit else "name")

    known = _known_names().get(name.strip().casefold(), Counter())
    quantities = Counter()
    for (_, column), n in known.items():
        if column in stored_quantity:
            quantities[stored_quantity[column]] += n
    for quantity, _ in quantities.most_common():
        if quantity not in taken and _unit_fits(quantity, unit):
            return ColumnGuess(name, quantity, _canonical_unit(quantity, unit), "known name")

    words = base.strip().casefold()
    for quantity, keywords in _KEYWORDS:
        if quantity in taken:
            continue
        if any(words == k or words.startswith(k + " ") or (len(k) > 3 and k in words) for k in keywords):
            if unit is not None and _unit_fits(quantity, unit):
                return ColumnGuess(name, quantity, _canonical_unit(quantity, unit), "name and unit")
            if unit is None and len(words) > 3:
                return ColumnGuess(name, quantity, None, "name")

    if unit is not None:
        quantity = _UNIT_QUANTITY.get(normalize_unit(unit))
        if quantity == "temperature" and "temperature" in taken:
            quantity = "sample_temperature"
        if quantity and quantity not in taken:
            return ColumnGuess(name, quantity, _canonical_unit(quantity, unit), "unit")
    return ColumnGuess(name)


# Columns almost every measurement has: they say nothing about which type a file is.
_GENERIC = {"time", "temperature", "sample_temperature"}


def _type_guess(names: List[str]) -> Optional[str]:
    generic = {column for quantity in _GENERIC for column in QUANTITIES[quantity].columns()}
    votes = Counter()
    for name in names:
        types = {type_ for type_, stored in _known_names().get(name.strip().casefold(), Counter())
                 if stored not in generic}
        for type_ in types:
            votes[type_] += 1 / len(types)
    if not votes:
        return None
    (best, score), *rest = votes.most_common() + [(None, 0)]
    return best if score >= 1 and score > rest[0][1] else None


# "Sig1<tab>Time (min)": a word, a number, a separator, a column name.
_LISTED = re.compile(r"^([A-Za-z]+)\d+(\t|:\s*|=\s*)(\S.*?)\s*$")
_LISTED_SEPARATORS = {"\t": r"\t", ":": r":\s*", "=": r"=\s*"}


def _listed_names(lines: List[str], width: int) -> Optional[str]:
    """A ``header.names_from`` pattern when as many numbered lines as columns name them, else None."""
    counts = Counter((m.group(1), m.group(2)[0]) for line in lines if (m := _LISTED.match(line)))
    for (word, separator), count in counts.most_common():
        if count == width:
            return f"^{re.escape(word)}\\d+{_LISTED_SEPARATORS[separator]}(.+)$"
    return None


def detect(path) -> Detection:
    """Guess how to read ``path``; raises ``ValueError`` when no table is found."""
    from mfethuls.parsers.tabular import read_table

    text, encoding, sheet = _detect_text(path)
    name_from: Optional[str] = None
    lines = text.splitlines()[:SCAN_LINES]
    delimiter, decimal, start, end, width = _best_block(lines)
    header_line, header_rows = _header(lines, start, delimiter, decimal, width)
    if sheet is not None:
        notes = [f"Excel workbook: the table is on sheet {sheet!r}."]
    else:
        notes = [f"Text encoding {encoding}; columns separated by {delimiter}"
                 + ("; decimal comma" if decimal == "," else "") + "."]

    header: Dict[str, Any] = {"rows": header_rows}
    first_table_line = header_line if header_line is not None else start
    if first_table_line:
        from mfethuls.parsers.tabular import _split

        fmt = FileFormat(extensions=(".x",), delimiter=delimiter, decimal=decimal)
        if header_line is not None:
            marker_line = header_line
            marker = next((f for f in _split(lines[header_line], fmt) if len(f.strip()) >= 3), None)
        else:
            # No column names: anchor on the last text line before the numbers, if it is distinctive.
            marker_line = max((i for i in range(start) if lines[i].strip()), default=None)
            marker = lines[marker_line].strip() if marker_line is not None else None
        unique = bool(marker) and not any(marker in line for line in lines[:marker_line])
        if unique and header_line is not None:
            header["starts_at"] = marker
            notes.append(f"Column names start on the line containing {marker!r} (line {header_line + 1}).")
        elif unique:
            header.update(starts_at=marker, skip_lines=start - marker_line)
            notes.append(f"The numbers start after the line {marker[:40]!r} (line {marker_line + 1}).")
        else:
            header["skip_lines"] = first_table_line
            notes.append(f"The first {first_table_line} line(s) are text before the table; they are kept.")
    if header_line is not None:
        # A file of several tables, each with its own header lines (a rheometer's intervals): the
        # guesses describe one table; say so instead of quietly reading only that one.
        repeats = sum(1 for line in lines if line.strip() and line.strip() == lines[header_line].strip())
        if repeats > 1:
            notes.append(f"The line of column names appears {repeats} times: the file seems to hold {repeats} "
                         "tables, and these guesses describe one. Fill in *Several tables, each starting at a "
                         "line containing* (text on the line that starts each table), or let a chatbot draft "
                         "the definition.")
    if header_rows == 2:
        notes.append("Column names are followed by a line of units; the two are joined.")
    elif header_rows == 0 and (names_from := _listed_names(lines[:start], width)):
        header["names_from"] = names_from
        notes.append(f"Column names are listed one per line before the table (lines matching {names_from}).")
    elif header_rows == 0:
        notes.append("No line of column names found: columns are called column_1, column_2, ...")

    file_settings: Dict[str, Any] = {
        "extensions": [Path(path).suffix.casefold() or ".txt"],
        "encoding": "utf-8" if encoding == "utf-8-sig" else encoding,
        "delimiter": delimiter,
        "decimal": decimal,
        "header": header,
    }
    if sheet is not None:
        # Workbook cells are read as tab-separated numbers; the sheet goes by number, since
        # sheet names often follow the sample. Without header text to find it, say which.
        file_settings = {"extensions": file_settings["extensions"], "header": header}
        names = list(workbook.sheets(path))
        try:
            tables = list(workbook.table_sheets(path, None, header.get("starts_at"))[0])
        except ValueError:
            tables = []
        if sheet not in tables or not header.get("starts_at"):
            number = names.index(sheet) + 1
            file_settings["sheet"] = -1 if number == len(names) and number > 1 else number
        elif len(tables) > 1:
            name_from = "sheet"
            notes.append(f"{len(tables)} sheets hold this table (one test each: {', '.join(map(repr, tables[:5]))}"
                         + (", …" if len(tables) > 5 else "") + "); all are read, each curve named after its sheet.")
        read = tables if sheet in tables and "sheet" not in file_settings else [sheet]
        others = [n for n in names if n not in read]
        if others:
            notes.append(f"The other sheets ({', '.join(map(repr, others))}) are kept as text.")
    all_lines = text.splitlines()
    after = next((line for line in all_lines[start:]
                  if line.strip() and not _fields(line, delimiter, decimal)[2]), None)
    if after is not None:
        file_settings["data_ends"] = "first_non_numeric_row"
        notes.append(f"The table ends before {after.strip()[:40]!r}; the text after it is kept.")

    file_format = parse_definition({"name": "x", "type": "x", "model": "x",
                                    "file": file_settings, "columns": [{"source": "x", "column": "x"}]}
                                   ).formats[0].file
    table = read_table(path, file_format)
    if sheet is not None:
        table = table.drop(columns=["sheet"], errors="ignore")  # added by mfethuls, not a file column
    taken: set = set()
    guesses = []
    for column in table.columns:
        guess = guess_column(str(column), taken)
        if guess.quantity:
            taken.add(guess.quantity)
        guesses.append(guess)
    found = sum(1 for g in guesses if g.quantity)
    notes.append(f"{len(table)} rows; {found} of {len(guesses)} columns recognised.")
    return Detection(
        file=file_settings,
        columns=guesses,
        notes=notes,
        type_guess=_type_guess([str(c) for c in table.columns]),
        header_line=header_line,
        data_lines=(start, end),
        outline=outline(all_lines, delimiter, decimal),
        name_from=name_from,
    )


def file_outline(path) -> List[str]:
    """:func:`outline` of the file at ``path``, with its separator detected."""
    if workbook.is_workbook(path):
        return outline(workbook.as_text(path), "tab", ".")
    text, _ = _read_text(path)
    lines = text.splitlines()
    delimiter, decimal, *_ = _best_block(lines[:SCAN_LINES])
    return outline(lines, delimiter, decimal)
