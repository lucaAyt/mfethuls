"""Describe the instrument definition format: a JSON Schema and a prompt for a chatbot.

Both are generated from :mod:`~mfethuls.instruments.definition` and
:mod:`~mfethuls.instruments.units`, so they always match what mfethuls accepts.
A chatbot's answer is checked like any other definition
(:func:`~mfethuls.instruments.definition.parse_definition`) before it is used.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .definition import (
    CONTAINS_LINES,
    DATA_ENDS,
    DELIMITERS,
    DERIVED_OPS,
    DUPLICATE_ROWS,
    LAYOUTS,
    NAME_FROM,
    SPEC_VERSION,
    TIME_UNITS,
    VALUE_TYPES,
)
from . import workbook
from .units import QUANTITIES


def json_schema() -> Dict[str, Any]:
    """JSON Schema (draft 2020-12) of an instrument definition."""
    sources = {
        "oneOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}, "minItems": 1},
        ],
        "description": "Column name as written in the file (header lines joined by a space), "
                       "or several alternative names.",
    }
    simple_name = {"type": "string", "pattern": "^[a-z0-9_\\-]+$"}
    file_format = {
        "type": "object",
        "required": ["extensions"],
        "properties": {
            "extensions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "encoding": {"type": "string", "default": "utf-8",
                         "description": "auto (UTF-8, else Windows cp1252; a safe choice), utf-8, cp1252, latin-1, ..."},
            "delimiter": {"anyOf": [{"enum": list(DELIMITERS)}, {"type": "string", "maxLength": 1}],
                          "default": "comma"},
            "decimal": {"enum": [".", ","], "default": "."},
            "header": {
                "type": "object",
                "properties": {
                    "starts_at": {"type": "string", "description": "Text found in the (first) header line."},
                    "skip_lines": {"type": "integer", "minimum": 0, "default": 0,
                                   "description": "Lines to skip (after the starts_at line, if given)."},
                    "rows": {"enum": [0, 1, 2], "default": 1,
                             "description": "0: no header; 2: a line of names and a line of units."},
                    "names_from": {"type": "string",
                                   "description": "With rows 0: a regular expression whose first group is a "
                                                  "column name, matched on the lines before the table (one "
                                                  "name per line, in column order)."},
                },
                "additionalProperties": False,
            },
            "data_ends": {"type": "string", "default": "end_of_file",
                          "description": f"{' or '.join(DATA_ENDS)}, or text marking the line after the data."},
            "comment": {"type": "string", "description": "Lines starting with this are comments (kept as text)."},
            "contains": {"type": "string",
                         "description": f"Text in the first {CONTAINS_LINES} lines that tells this layout apart "
                                        "from others with the same file ending."},
            "blocks": {
                "type": "object",
                "required": ["starts_at"],
                "description": "Several tables in one file (e.g. one per interval), each starting at a line "
                               "containing 'starts_at' and read with the same header settings. Each row gets "
                               "its block's label in 'column'.",
                "properties": {
                    "starts_at": {"type": "string", "description": "Text on the first line of every block."},
                    "label": {"type": "string",
                              "description": "Regular expression with one group, matched on that line; the "
                                             "label. Default: the block's number (1, 2, ...)."},
                    "column": {"type": "string", "default": "block", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
                },
                "additionalProperties": False,
            },
            "segment_lines": {"type": "boolean", "default": False,
                              "description": "Text lines inside the table (e.g. '2) Heating 10 K/min') label the "
                                             "rows below them, in a 'segment' column, instead of ending the table."},
            "sheet": {"oneOf": [{"type": "string"}, {"type": "integer"}],
                      "description": "Excel workbooks (.xlsx) only: the sheet holding the table, by name or number "
                                     "(1 = first, -1 = last). Default: the first sheet containing "
                                     "header.starts_at."},
            "duplicate_rows": {"enum": list(DUPLICATE_ROWS), "default": "keep",
                               "description": "drop: leave out rows that repeat an earlier row of the file in "
                                              "every field (the count is noted). Rows differing in any field "
                                              "are always kept."},
        },
        "additionalProperties": False,
    }
    columns = {
        "type": "array",
        "minItems": 1,
        "items": {
            "oneOf": [
                {
                    "type": "object",
                    "required": ["source", "quantity"],
                    "properties": {
                        "source": sources,
                        "quantity": {"enum": sorted(QUANTITIES)},
                        "unit": {"type": "string",
                                 "description": "Unit in the file; defaults to the quantity's standard unit."},
                    },
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "required": ["source", "column"],
                    "properties": {
                        "source": sources,
                        "column": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
                                   "description": "Stored name of a column that is not a quantity."},
                    },
                    "additionalProperties": False,
                },
            ]
        },
    }
    captured = {
        "type": "object",
        "required": ["column", "pattern"],
        "properties": {
            "column": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
            "pattern": {"type": "string"},
            "type": {"enum": list(VALUE_TYPES), "default": "text"},
            "values": {"type": "object", "additionalProperties": {"type": "string"},
                       "description": "Stored value -> regular expression the captured text must match "
                                      "(case ignored); a capture matching none is stored as it is."},
            "timezone": {"type": "string",
                         "description": "datetime only: zone of local times, e.g. Europe/Zurich; stored in UTC."},
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "mfethuls instrument definition",
        "type": "object",
        "required": ["name", "type", "model", "folder_name"],
        "oneOf": [{"required": ["file", "columns"]}, {"required": ["formats"]}],
        "properties": {
            "spec_version": {"const": SPEC_VERSION},
            "name": {**simple_name, "description": "Instrument name used in the registry."},
            "type": {**simple_name, "description": "Measurement type, e.g. tga, ftir, uv_vis, or a new one."},
            "model": {"type": "string"},
            "folder_name": {"type": "string", "description": "Folder under the data folder holding its files."},
            "data_layout": {"enum": list(LAYOUTS), "default": "file",
                            "description": "file: one file per experiment; folder: one folder per experiment."},
            "description": {"type": "string"},
            "file": file_format,
            "columns": columns,
            "formats": {
                "type": "array",
                "minItems": 1,
                "description": "Several file layouts (software versions, exports); each file is read with "
                               "the first one whose extension and 'contains' text match.",
                "items": {
                    "type": "object",
                    "required": ["file", "columns"],
                    "properties": {"label": {"type": "string"}, "file": file_format, "columns": columns},
                    "additionalProperties": False,
                },
            },
            "derived": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["op", "column", "into"],
                    "properties": {
                        "op": {"enum": list(DERIVED_OPS)},
                        "column": {"type": "string"},
                        "into": {"type": "string", "description": "New column; existing data is never changed."},
                        "factor": {"type": "number"},
                        "value": {"type": "number"},
                        "amount": {"type": "string", "description": "add_time: column holding the time added."},
                        "unit": {"enum": list(TIME_UNITS), "description": "add_time: unit of 'amount'."},
                        "by": {"type": "string", "description": "multiply / divide: the other stored column."},
                    },
                    "additionalProperties": False,
                },
            },
            "characterizer": {"type": "object", "required": ["type"]},
            "plot": {
                "type": "object",
                "required": ["x", "y"],
                "properties": {"x": {"type": "string"}, "y": {"type": "string"}, "group_by": {"type": "string"}},
            },
            "name_from": {"enum": list(NAME_FROM), "default": "file",
                          "description": "Name each file's rows (curves) after the file, its folder, or (workbooks with one test per sheet) the sheet."},
            "from_file_name": {
                "type": "array",
                "description": "Columns filled from the file name: the first group of a regular expression "
                               "found in the file name without its ending.",
                "items": captured,
            },
            "from_sheet_name": {
                "type": "array",
                "description": "Excel workbooks with one test per sheet: columns filled from each test sheet's "
                               "name, e.g. the sample (LUB640_1 -> LUB640): the first group of a regular "
                               "expression found in the sheet name.",
                "items": captured,
            },
            "from_header": {
                "type": "array",
                "description": "Columns filled from the text around the table (before it, then after it and "
                               "other workbook sheets): the first group of a regular expression, from the first "
                               "line it matches.",
                "items": captured,
            },
            "tables": {
                "type": "array",
                "description": "Second tables in the text around the data (a peak list, a results block), "
                               "kept in the dataset's metadata tables[name][file] as records. Their lines "
                               "stay in the file text too.",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
                        "starts_at": {"type": "string", "description": "Text on the line before its rows "
                                                                       "(with 'header': on its header line)."},
                        "ends_at": {"type": "string", "description": "Text on the line after its rows."},
                        "columns": {"type": "array", "items": {"type": "string",
                                                               "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
                                    "description": "Names of the fields, in order (with 'header': of the "
                                                   "fields without a header name)."},
                        "sheet": {"type": "string",
                                  "description": "Excel workbooks only: the sheet holding the table, e.g. Results."},
                        "header": {"type": "object", "required": ["rows"],
                                   "properties": {"rows": {"type": "integer", "minimum": 1, "maximum": 3}},
                                   "additionalProperties": False,
                                   "description": "The table's own header lines (1: names, 2: names then "
                                                  "units); every line below them is a row, e.g. one per "
                                                  "specimen."},
                    },
                    "additionalProperties": False,
                },
            },
            "check": {
                "type": "object",
                "required": ["sample"],
                "description": "Written by mfethuls: a sample file and what it must read as.",
            },
        },
        "additionalProperties": False,
    }


def quantity_table() -> str:
    """Markdown table of the quantities, their stored columns and accepted units."""
    lines = ["| quantity | stored as | units accepted (first is standard) |", "|---|---|---|"]
    for q in QUANTITIES.values():
        units = ", ".join(f"`{u}`" if u else "`` (none)" for u in q.unit_names())
        stored = (q.column + "".join(f" ({t}: {c})" for t, (c, _) in q.by_type.items())
                  + "".join(f" (in {u}: {c})" for c, u, _ in q.families))
        lines.append(f"| `{q.name}` | `{stored}` | {units} |")
    return "\n".join(lines)


_EXAMPLE = {
    "spec_version": SPEC_VERSION,
    "name": "tga_lab2",
    "type": "tga",
    "model": "tgaX",
    "folder_name": "TGA",
    "data_layout": "file",
    "file": {
        "extensions": [".txt"],
        "encoding": "cp1252",
        "delimiter": "whitespace",
        "header": {"starts_at": "Index", "rows": 2},
        "data_ends": "first_non_numeric_row",
    },
    "columns": [
        {"source": "Tr [°C]", "quantity": "temperature", "unit": "°C"},
        {"source": "Ts [°C]", "quantity": "sample_temperature", "unit": "°C"},
        {"source": "t [s]", "quantity": "time", "unit": "s"},
        {"source": "Weight [mg]", "quantity": "mass", "unit": "mg"},
        {"source": "HF [mW]", "quantity": "heat_flow", "unit": "mW"},
    ],
    "derived": [{"op": "pct_of_initial", "column": "mass_mg", "into": "mass_pct"}],
}

RULES = [
    "- `file` says where the table is: encoding, delimiter (comma, semicolon, tab, whitespace or one "
    "character), decimal (\".\" or \",\"), `header.starts_at` (text in the header line) and/or "
    "`header.skip_lines`, `header.rows` (0, 1, or 2 when a line of units follows the names; "
    "the two are joined with a space, e.g. `Weight [mg]`), `data_ends` (`end_of_file`, "
    "`first_non_numeric_row`, or text on the first line after the data).",
    "- `columns` maps file columns (`source`, exactly as named after joining header rows) to a "
    "`quantity` and the `unit` used in the file; mfethuls converts it to the standard unit. A column "
    "with no matching quantity can get a plain `column` name instead. Unmapped columns, every row and "
    "the text around the table are always kept, so only map what you can identify.",
    "- Text lines inside the table that label what follows (e.g. '2) DSC 8500 Temperature Scan') need "
    "`file.segment_lines: true`; they then fill a `segment` column. Use `encoding: \"auto\"` unless "
    "you are sure of the encoding.",
    "- When the column names are not on a header line but listed one per line before the table (e.g. "
    "`Sig1<tab>Time (min)`, `Sig2<tab>Temperature (°C)`), set `header.rows` to 0 and `header.names_from` "
    "to a regular expression whose group is the name, e.g. `^Sig\\d+\\t(.+)$`; `source` is then that name.",
    "- When the file holds several tables, each with its own header lines (e.g. one per measurement "
    "interval: `Interval and data points:<tab>2<tab>60`, then the column names and units again), use "
    "`file.blocks`: {\"starts_at\": text on each block's first line, \"label\": regular expression "
    "whose group labels the block (e.g. `^Interval and data points:\\\\s*(\\\\d+)`), \"column\": "
    "\"interval\"}. The `header` settings then apply inside each block, from the line after its first line; blank lines (also lines of only "
    "tabs) between header lines are skipped. Check the end of the file: if the first table is not the "
    "only one, you need `blocks`.",
    "- `name_from` (`file`, `folder`, or `sheet` for workbooks with one test per sheet) names each file's curve; `from_file_name` fills columns from "
    "the file name, e.g. {\"column\": \"titrant\", \"pattern\": \"_0*([^_]+)$\"}. Add `values` to "
    "turn codes into words, e.g. {\"column\": \"detector_name\", \"pattern\": \"_([^_.]+)$\", "
    "\"values\": {\"ri\": \"^RID\", \"uv\": \"^(VWD|DAD)\"}}.",
    "- Excel workbooks (.xlsx) are shown sheet by sheet, each row as tab-separated cells. Give "
    "`extensions: [\".xlsx\"]` and the `header`; leave out encoding, delimiter and decimal. Without "
    "`file.sheet`, EVERY sheet containing `header.starts_at` is read (a workbook often holds one test per "
    "sheet) and rows get a `sheet` column; then set `name_from: \"sheet\"` so each test is its own curve. "
    "When test sheets are named after the sample and a replicate number (LUB640, LUB640_1, LUB640_2), add "
    "`from_sheet_name`: [{\"column\": \"sample\", \"pattern\": \"^(.+?)(?:_\\\\d+)?$\"}] so each curve knows its "
    "sample. `file.sheet` (name or number, 1 = first, -1 = last) reads only that sheet. The other sheets are kept. When sheet names change from file to file "
    "(e.g. named after the sample), use a number or rely on `header.starts_at`, never the name. In a "
    "`from_header` pattern, `{sheet}` stands for each test's sheet name, to take a value from that test's "
    "row in a results sheet, e.g. `^{sheet}\\\\t([0-9.]+)`. Dates Excel saved as plain numbers "
    "(e.g. 46246.745) are read by `type: \"datetime\"`.",
    "- `from_header` fills columns from the text around the table (sample weight, a date, a rate), "
    "searched before the table first, then after it and in other workbook sheets: "
    "{\"column\": ..., \"pattern\": regular expression with one group, \"type\": "
    + " | ".join(f"\"{t}\"" for t in VALUE_TYPES)
    + "}. Give a datetime its `timezone` (e.g. `Europe/Zurich`) when it is local time; it is stored in UTC.",
    "- Keep regular expressions short (at most 300 characters) and never repeat a group that itself "
    "repeats or is optional, such as `(\\w+\\s?)+` or `(.*,)*`: mfethuls refuses them because they can take "
    "hours on some lines. Repeat one character class instead (`[\\w\\s]+`, `[^,]*`).",
    "- Keep every bit of time precision: if the file name holds a finer time than the header (e.g. "
    "`..._18-11-09-757` where the header says `18:11:09`), capture the milliseconds with `from_file_name` "
    "(`type: number`) and add them with `derived` `add_time` "
    "({\"op\": \"add_time\", \"column\": header date column, \"amount\": the milliseconds column, "
    "\"unit\": \"ms\", \"into\": \"timestamp\"}). A `timestamp` column gives each spectrum/row "
    "its time; mfethuls adds `time_s` from it.",
    "- If the instrument writes several layouts (software versions, a CSV and a text export), use "
    "`formats`: a list of {`label`, `file`, `columns`}; `file.contains` (text near the top of the file) "
    "tells layouts with the same file ending apart.",
    "- `derived` may only use these operations, each writing a new column `into`: "
    + ", ".join(f"`{op}`" for op in DERIVED_OPS)
    + ". `normalize_pct` scales a stored column to 0-100 %; `pct_of_initial` gives each value as % of the "
    "curve's first value (TGA mass: 100 % = initial mass); `scale` multiplies by `factor`; `offset` adds "
    "`value`; `multiply` / `divide` combine it with another stored column `by` (e.g. heat_flow_mW divided "
    "by a `sample_mass_mg` taken with `from_header` gives heat_flow_W_g); `add_time` adds the time in "
    "column `amount` (unit `unit`) to a date-time column.",
    "- A second table after the data (a peak list, a results block) ends the data: set `data_ends` to "
    "text on its first line, and add `tables`: [{\"name\": \"peak_list\", \"starts_at\": that text, "
    "\"ends_at\": text on the line after it, \"columns\": [field names]}] to keep it as metadata. Rows "
    "written twice (identical in every field) can be left out with `file.duplicate_rows: \"drop\"`; "
    "never use it when repeated rows are real measurements.",
    "- A workbook's results sheet (one row per specimen or test, under its own header lines of names and "
    "units: strength, modulus, dimensions) is kept as metadata with `tables`: [{\"name\": \"results\", "
    "\"sheet\": its name, \"header\": {\"rows\": 2}, \"columns\": [\"specimen\"]}] (`columns` names "
    "the fields without a header, such as the specimen name in the first column). Do not keep a sheet "
    "of statistics (mean, min, max) this way; it stays in the file text.",
    "- For a measurement type mfethuls does not know yet, add `plot`: "
    "{\"x\": stored column, \"y\": stored column}.",
]


def problems_prompt(problems: List[str], data: Optional[Dict[str, Any]] = None) -> str:
    """A message for the chatbot: what is wrong with its definition, and the definition."""
    parts = [
        "mfethuls checked your instrument definition against the file and found these problems:",
        *[f"- {problem}" for problem in problems],
        "",
        "Fix them and reply with the corrected JSON only.",
    ]
    if data is not None:
        parts += ["", "The definition was:", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```"]
    return "\n".join(parts)


def file_excerpt(lines: List[str], head: int = 40, tail: int = 15) -> List[str]:
    """The first ``head`` and last ``tail`` lines, with a marker for what is left out."""
    if len(lines) <= head + tail + 1:
        return list(lines)
    return [*lines[:head], f"… {len(lines) - head - tail} lines left out …", *lines[-tail:]]


def workbook_excerpt(path: Path, head: int = 40, tail: int = 15) -> List[str]:
    """Each sheet of a workbook as tab-separated rows: all of a short sheet, else its first and last rows."""
    out = [f"The Excel workbook `{path.name}`, sheet by sheet (cells separated by tabs; "
           f"long sheets show their first {head} and last {tail} rows):"]
    for number, (name, lines) in enumerate(workbook.sheets(path).items(), start=1):
        out += ["", f"Sheet {number}: {name!r} ({len(lines)} rows)", "```", *file_excerpt(lines, head, tail), "```"]
    return out


def spec_card(
    sample: Optional[Union[str, Path]] = None,
    *,
    max_lines: int = 40,
    tail_lines: int = 15,
    encoding: str = "utf-8",
    hints: str = "",
    other_files: Optional[Dict[str, List[str]]] = None,
) -> str:
    """A self-contained prompt asking a chatbot to write a definition.

    With ``sample`` (a file path or its text), its first ``max_lines`` and last
    ``tail_lines`` lines are included; nothing else from the file is. ``hints``
    adds what the user and mfethuls know (instrument, folder, mfethuls' reading of
    the whole file). ``other_files`` maps other files of the instrument to their
    outline (their shape, no data), so the definition fits them too.
    """
    parts = [
        "Write an mfethuls *instrument definition* (JSON) for the instrument whose export file is shown below.",
        "mfethuls reads the file with a generic table reader configured by this JSON; no code is involved.",
        "Reply with the JSON only, no explanations.",
        "",
        "Rules:",
        *RULES,
        "- Look at the end of the file too: text after the table (a footer, results, a second table) "
        "needs `data_ends`, or it is read as rows of the table.",
        "",
        "Quantities:",
        "",
        quantity_table(),
        "",
        "Example (for a different file):",
        "```json",
        json.dumps(_EXAMPLE, indent=2, ensure_ascii=False),
        "```",
        "",
        "JSON Schema:",
        "```json",
        json.dumps(json_schema(), indent=1, ensure_ascii=False),
        "```",
    ]
    if hints.strip():
        parts += ["", "What is known about the instrument and the file:", hints.strip()]
    for name, outline in (other_files or {}).items():
        parts += ["", f"Another file of this instrument, `{name}`, must be read by the same definition. "
                      "Its shape (no data):", *outline]
    if sample is not None:
        is_path = isinstance(sample, Path) or (isinstance(sample, str) and "\n" not in sample
                                               and Path(sample).is_file())
        if is_path and workbook.is_workbook(sample):
            parts += ["", *workbook_excerpt(Path(sample), max_lines, tail_lines)]
            return "\n".join(parts)
        if is_path and workbook.is_binary(sample):
            raise ValueError(f"{Path(sample).name} is not a text file. mfethuls reads text exports "
                             "(.txt, .csv, ...) and Excel workbooks (.xlsx); export the data as one of those.")
        if is_path:
            name = Path(sample).name
            with open(sample, encoding=encoding, errors="replace") as f:
                lines = [line.rstrip("\r\n") for line in f]
        else:
            name = "sample"
            lines = str(sample).splitlines()
        excerpt = file_excerpt(lines, max_lines, tail_lines)
        what = (f"All {len(lines)} lines" if len(excerpt) == len(lines)
                else f"The first {max_lines} and last {tail_lines} of its {len(lines)} lines")
        parts += ["", f"{what} of `{name}`:", "```", *excerpt, "```"]
    return "\n".join(parts)
