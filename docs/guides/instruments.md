# Adding an instrument

mfethuls reads an instrument's files through an **instrument definition**: a small JSON file that says how to find the table in the instrument's exports and what each column is. You don't write code. Most instruments that export text files (CSV, TXT, DAT, ...) or Excel workbooks (`.xlsx`) can be added from the app in a few minutes.

Nothing in your files is thrown away. Every column, every row and the text around the table (sample names, dates, method settings) is kept. A definition only gives the columns it recognises a standard name and unit, so data from different instruments can be compared.

---

## From the app

1. Put a few files the instrument exported in a folder of your data folder, e.g. `PATH_TO_DATA/Photometer/kin1.dat`, `kin2.dat`, … Several files help: runs and methods differ, and the definition must read them all.
2. Open **⚙ Settings → Instruments → Add instrument**. **Review & register** also offers it when it finds a folder with files no instrument reads.

   If mfethuls already knows the instrument and only the folder has another name (`DMA data` instead of `DMA`), don't add it: choose it for that folder in **Review & register**, or under **⚙ Settings → Instruments → Change an instrument's folder**. That also fixes an instrument saved with the wrong folder.
3. Choose the **folder**. mfethuls builds from its largest file of the type the folder holds most of (change it under **Build from**), and checks the definition against up to six other files of that type in the folder (the largest, the newest and others spread over the folder). Files of other types, such as a plot or a note next to the data, are left out.
4. **Ask a chatbot** (the default): copy the prompt into a chatbot (Gemini, Claude, ...), paste its answer back and press **Read the answer**. The prompt holds the rules of the format, the list of quantities and units, mfethuls' own reading of the file (including its outline: which lines are text and which are numbers, from start to end), the file's first 40 and last 15 lines (for a workbook: of every sheet, shown as tab-separated rows), and the outline of the other files (their shape only, not their data). A file that is neither text nor a workbook (e.g. a proprietary binary format) gets a message instead of a prompt: export it as text or `.xlsx` first. A definition a colleague sent you can be pasted the same way.

   > The prompt contains the start of your file. Only send it if your data may be shared with that service: think of unpublished results and your institution's rules.

   Or choose **Fill in myself**: mfethuls fills in its own guesses instead.
5. Either way you see the result first: the **Name**, how many rows and which columns were read, a plot, and whether the other files read cleanly. If it looks right, press **Save instrument**. When some of the other files cannot be read, the reasons are shown and saving needs one more tick (**Save anyway**): your call, e.g. when those files are not this instrument's data, or another layout will be added for them later. They would fail when ingested.
6. Everything else is under **Adjust details**, which opens by itself when something must be fixed. Its tabs:
   - **Instrument**: data folder, measurement type, model, whether one experiment is a file or a folder, notes. A known type (TGA, FTIR, UV-Vis, ...) gets mfethuls' plots and checks; for a new type you choose what to plot.
   - **Reading the file**: file endings, text encoding, separator, decimal mark, header lines, where the table starts and ends. For a workbook, the sheet replaces encoding, separator and decimal mark.
   - **Columns**: what each column measures and the unit *in the file*. Leave columns you don't know empty: they are kept under their own name.
   - **Values and plot**: values from the file name and header, computed columns (always into a new column) and, for new types, the plot.
   - **Stored data**: every column of the file with its stored name and unit change (e.g. `g → mg: × 1000`), and the parsed table.
   - **Definition (JSON)**: the file that is saved.

   Values outside the usual range for a quantity (a mass of 300 000 mg, a temperature of 5000 °C) are warned about: usually the unit is wrong. So are rows with text where numbers are expected, with the line they start on: usually a footer or results block read as part of the table, fixed with *The data ends at*. Another file that cannot be read must be fixed before saving. Each problem is shown in its tab, the top says which tabs, and **Copy the problems for the chatbot** gives a message to paste back to it.

The definition is saved in the data folder, in `.mfethuls/instruments/<name>.json`, together with a copy of the file you used (`<name>.sample.<ext>`). Everyone who uses that data folder (e.g. on OneDrive) gets the instrument; nothing needs installing. **Adjust details → Definition (JSON)** shows the file itself.

Then register and ingest its data as usual.

### Editing an instrument

**⚙ Settings → Instruments** lists the lab's instruments, each with **Edit** and **Remove**. **Edit** opens the same form, filled in with the saved definition and with **Adjust details** open: change what was wrong (the header lines, a column's unit, the end of the table) and the result is checked again, against the file the instrument was made from and other files in its folder, before **Save changes**. Its name stays, since registry rows use it; to rename an instrument, add it again under the new name. Settings the form does not show (such as `tables`) are kept as they are.

Data already ingested keeps the earlier reading until it is read again: ingesting it again does that, and **⚙ Settings → Clean up** offers **Read again** for every experiment the instrument read before the change.

### Removing an instrument

**⚙ Settings → Instruments** lists the lab's instruments, each with **Edit** and **Remove**. It first says how many registry rows and ingested experiments use the instrument, then moves its files to `.mfethuls/instruments/removed/<date-time>/`. Nothing is deleted:

- ingested data stays where it is;
- registry rows that use the instrument can't be ingested again until an instrument reads them (Clean up never forgets their data because of that);
- if it replaced a built-in instrument, the built-in one reads the files again, and **Clean up** offers to read them again;
- to undo, move the two files back into `.mfethuls/instruments/`.

Built-in instruments can't be removed, only replaced.

---

## What a definition looks like

The TGA that ships with mfethuls (`src/mfethuls/config/instruments/tga.json`) reads files like this one:

```
         Index            Ts             t            HF        Weight            Tr
           [#]          [°C]           [s]          [mW]          [mg]          [°C]
             0   3.21864e+01   0.00000e+00   2.98255e+01   2.47986e+00   2.50000e+01
           ...
LUB457, 11.02.2026 10:03:11
```

A definition for it:

```json
{
  "spec_version": 1,
  "name": "tga",
  "type": "tga",
  "model": "tgaX",
  "folder_name": "TGA",
  "data_layout": "file",
  "file": {
    "extensions": [".txt"],
    "encoding": "cp1252",
    "delimiter": "whitespace",
    "header": { "starts_at": "Index", "rows": 2 },
    "data_ends": "first_non_numeric_row"
  },
  "columns": [
    { "source": "Tr [°C]",     "quantity": "temperature",        "unit": "°C" },
    { "source": "Ts [°C]",     "quantity": "sample_temperature", "unit": "°C" },
    { "source": "t [s]",       "quantity": "time",               "unit": "s"  },
    { "source": "Weight [mg]", "quantity": "mass",               "unit": "mg" },
    { "source": "HF [mW]",     "quantity": "heat_flow",          "unit": "mW" }
  ],
  "derived": [
    { "op": "pct_of_initial", "column": "mass_mg", "into": "mass_pct" }
  ],
  "characterizer": { "type": "tga" }
}
```

| Part | What it says |
|---|---|
| `name`, `type`, `model` | The instrument's name in the registry, its measurement type and its make/model/software. Instruments are told apart by `name`, so two identical instruments with their own folders (two PerkinElmer DSCs in two rooms) can share type and model. For a second one that reads exactly like an existing instrument, a `same_as` file is enough (see [Another instrument of the same kind](#another-instrument-of-the-same-kind)). |
| `folder_name`, `data_layout` | Its folder under the data folder; whether one experiment is one `file` or one `folder` of files. |
| `file` | How to find the table. `encoding` (`auto` = UTF-8, else Windows cp1252; or `utf-8`, `cp1252`, ...); `delimiter` (`comma`, `semicolon`, `tab`, `whitespace` or one character); `decimal` (`.` or `,`); `header.starts_at` (text on the line with the column names) and/or `header.skip_lines`; `header.rows` (`0` none, `1` names, `2` names then units, joined as `Weight [mg]`); `data_ends` (`end_of_file`, `first_non_numeric_row`, or text on the first line after the data; `first_non_numeric_row` ends the table at the first row of text *after* a row of numbers, so rows before the first number, such as Anton Paar's `1  (invalid)` points, are kept as data); `comment` (lines starting with it are kept as comments); `segment_lines: true` when text lines inside the table label the rows below them (PerkinElmer's "2) DSC 8500 Temperature Scan"): they fill a `segment` column. Without header lines the table starts at the first line of numbers. Blank lines between header lines (also lines of only tabs) are skipped. With `whitespace`, a units line with fewer fields than the names (no unit under `Index`) is matched to the names by where its fields stand. `blocks` is for files holding several tables, each with its own header lines (Anton Paar RheoCompass writes one per interval): `{"starts_at": "Interval and data points:", "label": "^Interval and data points:\\s*(\\d+)", "column": "interval"}` reads every table with the same settings and puts its label (the group of `label` on its first line, or its number) in the `interval` column. `header.names_from` (with `rows: 0`) is for files that list their column names one per line above the table: a regular expression whose group is the name, e.g. `^Sig\\d+\\t(.+)$` for TA Instruments' `Sig1<tab>Time (min)`. For Excel workbooks, `sheet` picks the sheet (see [Excel workbooks](#excel-workbooks)). `duplicate_rows: "drop"` leaves out rows repeating an earlier row in every field (see [A second table, and rows written twice](#a-second-table-and-rows-written-twice)). |
| `columns` | Each `source` column (or a list of alternative names) is a `quantity` in the `unit` the file uses. mfethuls stores it under the standard name in the standard unit: `Weight [g]` with `"unit": "g"` is stored as `mass_mg`. A column that is no quantity can get a plain name instead: `{"source": "Detector", "column": "detector_name"}`. |
| `derived` | Extra columns from a fixed list: `normalize_pct` (0–100 %), `pct_of_initial` (% of each curve's first value: TGA mass, 100 % = initial mass), `scale` (`factor`), `offset` (`value`), `multiply` / `divide` (by another column `by`, e.g. heat flow ÷ sample mass), `add_time` (adds the time in column `amount`, in `unit` `ms`/`s`/`min`/`h`, to a date-time column). Each writes a new column `into`; existing data is never changed. An operation whose column a file lacks (no sample mass in this file) is skipped for that file. |
| `plot` | For a new measurement type: `{"x": "time_s", "y": "absorbance_a_u"}`. |
| `characterizer` | One of mfethuls' built-in feature extractors (DSC, TGA). |
| `name_from` | `file` (default), `folder`, or `sheet`: what each file's rows (its curve) are named after. `sheet` is for workbooks holding one test per sheet; a workbook with a single test keeps the file name. |
| `from_file_name` | Columns filled from the file name: `[{"column": "titrant", "pattern": "_0*([^_]+)$"}]` puts what follows the last underscore (without leading zeros) in `titrant`. Optional: `type` (`text`, `number`, `datetime`), `values` to turn codes into words (`{"ri": "^RID", "uv": "^(VWD\|DAD)"}`; a code matching none is stored as it is) and, for date-times, `timezone`. |
| `from_sheet_name` | Workbooks with one test per sheet: the same, from each test sheet's name, e.g. the sample (`LUB640_1` → `LUB640`). See [Excel workbooks](#excel-workbooks). |
| `from_header` | The same, from the text around the table (the first line that matches, searched above the table first, then below it and in the other sheets of a workbook): a sample weight, a date. A `datetime` in local time needs its `timezone` (`Europe/Zurich`); it is stored in UTC. Dates Excel saved as plain numbers (`46246.745`) are read too. In a workbook with one test per sheet, `{sheet}` in the pattern stands for each test's sheet name, so each test gets the value from its own row of a results sheet. Each value is a column and is also listed in the metadata (`file_text` → `values`). |
| `tables` | Second tables in the text around the data (a peak list), kept in the metadata `tables[name][file]`: `{"name", "starts_at", "ends_at", "columns"}`. See [A second table, and rows written twice](#a-second-table-and-rows-written-twice). A workbook's results sheet, with its own header lines: `{"name", "sheet", "header": {"rows": 2}, "columns"}` (see [Excel workbooks](#excel-workbooks)). |
| `check` | Written by mfethuls when saving: the sample file and what it read. |

The full list of quantities, their standard columns and accepted units: `python -c "from mfethuls.instruments.spec import quantity_table; print(quantity_table())"`. Units are case-sensitive (`MPa` is not `mPa`).

The same quantity can be stored differently depending on context, so values that can't be compared never share a column:

- **By unit.** Strain in `%` or as a fraction is stored as `strain_pct` (rheometer, DMA); strain written as a length (`mm`, a tensile tester's "Strain") as `strain_mm`. A length is never turned into a percentage.
- **By measurement type.** Moduli are stored in Pa for rheology but in MPa for `dma`; shear stress and stress in Pa, but in MPa for `tensile` (the convention in mechanical testing).

### Sample mass and heat flow per gram

A DSC file that states its sample mass gets both heat-flow columns. The PerkinElmer definition takes the mass from the header and divides:

```json
"from_header": [
  { "column": "sample_mass_mg", "pattern": "^Sample Weight:\\s*([0-9.]+)\\s*mg", "type": "number" }
],
"derived": [
  { "op": "divide", "column": "heat_flow_mW", "by": "sample_mass_mg", "into": "heat_flow_W_g" }
]
```

mW ÷ mg is W/g. A file that already has W/g (the older Mettler Toledo export, `dsc_mettler_toledo_v0`) multiplies instead, into `heat_flow_mW`. Files without a sample mass simply don't get the extra column.

### Values from the file name and the header

The Ocean Optics Flame definition (`uv_insitu.json`) shows how they combine. Each spectrum's header says `Date: Sun May 11 18:11:09 CEST 2025`, and the file name ends with the same time to the millisecond (`poly3__0__18-11-09-757.txt`). Both are kept, and together they give the `timestamp`:

```json
"from_header": [
  { "column": "header_time", "pattern": "^Date:\\s*(.+)$", "type": "datetime", "timezone": "Europe/Zurich" }
],
"from_file_name": [
  { "column": "file_time_ms", "pattern": "\\d{2}-\\d{2}-\\d{2}-(\\d{1,3})$", "type": "number" }
],
"derived": [
  { "op": "add_time", "column": "header_time", "amount": "file_time_ms", "unit": "ms", "into": "timestamp" }
]
```

mfethuls adds `time_s` (seconds since the first spectrum) to data with a `timestamp`.

### A second table, and rows written twice

Some files follow the data with another table: Bruker MS writes a peak list after the spectrum. End the data at its first line with `data_ends`, and keep the table with `tables`. Its rows (lines after `starts_at` up to `ends_at` that start with a number) are stored in the dataset's metadata under `tables`, per file, as records named by `columns`; the lines also stay in `file_text`. From the built-in `ms.json`:

```json
"file": { "extensions": [".bsc"], "delimiter": "comma", "header": { "rows": 0 },
          "data_ends": "Peak", "duplicate_rows": "drop" },
"tables": [
  { "name": "peak_list", "starts_at": "Peak", "ends_at": "End", "columns": ["mz", "intensity_a_u"] }
]
```

`dataset.metadata["tables"]["peak_list"]["LUB446.bsc"]` is then `[{"mz": 338.105, "intensity_a_u": 551339.0}, ...]`.

`duplicate_rows: "drop"` leaves out rows that repeat an earlier row of the same file in every field (the MS software writes its first and last points twice), so they don't reach the database. The count is noted in the file's `file_text` (`notes`). A row differing in any field, such as the same m/z with another intensity, is always kept. The default, `keep`, keeps every row.

### Several file layouts

When an instrument writes more than one layout (a newer software version, a CSV export next to the text export), list them under `formats`. Each file is read with the first format whose extension matches and, if given, whose `contains` text appears in its first 50 lines:

```json
{
  "name": "tga", "type": "tga", "model": "tgaX", "folder_name": "TGA",
  "formats": [
    { "label": "text export",
      "file": { "extensions": [".txt"], "contains": "Index", "delimiter": "whitespace", "header": { "rows": 2 } },
      "columns": [ { "source": "Weight [mg]", "quantity": "mass", "unit": "mg" } ] },
    { "label": "CSV export",
      "file": { "extensions": [".csv"] },
      "columns": [ { "source": "Mass [mg]", "quantity": "mass", "unit": "mg" } ] }
  ]
}
```

`not_contains` does the opposite: files with that text in their first 50 lines are *not* this layout. Use it when two
layouts (or two instruments sharing a folder) differ by something only one of them has. The built-in Mettler DSC
definitions do this: the older STARe report has a `Curve Values:` line, so `dsc_mettler_toledo_v0` has
`"contains": "Curve Values:"` and `dsc_mettler_toledo_v1` has `"not_contains": "Curve Values:"`. Each file is then
read by one of them only, and choosing the wrong one gives a clear message instead of other columns.

### Excel workbooks

A workbook (`.xlsx`) is read sheet by sheet, each row as tab-separated cells, so the same `header` settings apply. Give `"extensions": [".xlsx"]` and leave out `encoding`, `delimiter` and `decimal`: cells already hold numbers. Cells hold what Excel saved (the results of formulas, not the formulas). The old binary `.xls` format is not read; save it as `.xlsx`.

- **Which sheet.** `file.sheet` picks one by name or number (`1` = first, `-1` = last). Without it, **every sheet containing `header.starts_at`** is read, and each row gets a `sheet` column. Instrument software often writes one test per sheet, named after the specimen, and none of them is skipped. Sheet names that follow the sample change from file to file, so rely on `header.starts_at` or a number, never a sheet name.
- **Nothing is dropped.** The other sheets (parameters, results, statistics) are kept as text in the metadata, under `file_text` → `sheet: <name>`.
- **One curve per test.** With `"name_from": "sheet"`, each test sheet is its own curve, named after its sheet.
- **The sample of each curve.** `from_sheet_name` fills columns from each test sheet's name, like `from_file_name` does from the file name. Sheets named after the sample and a replicate (`LUB640`, `LUB640_1`, `LUB640_2`) get their sample with `[{"column": "sample", "pattern": "^(.+?)(?:_\d+)?$"}]`, so one workbook holding several samples can be plotted, coloured and filtered by sample. Excel cuts sheet names at 31 characters, so a long one gives a shortened sample.
- **A results sheet as numbers.** A sheet with one row per specimen under its own header lines (strength, modulus, dimensions) can also be kept as a table of numbers with `tables`: `{"name": "results", "sheet": "Results", "header": {"rows": 2}, "columns": ["specimen"]}`. Each row becomes a record whose fields are named like data columns, name and unit joined (`"sM kPa"`, `"eB %"`); `columns` names the fields without a header, here the specimen name in the first column. Empty cells are left out. The records are in the metadata under `tables` → `results` → the file's name, and the sheet's text stays in `file_text`.

The built-in tensile tester (`tensile_tester.json`, ZwickRoell testXpert exports) shows all of it. It has two layouts in one definition: lap-shear tests (Strain in mm, Shearing stress in MPa) and tensile tests (Elongation in %, and "Standard force" in kPa, which is a stress). Each test takes its date from its own row of the Results sheet, its sample from its sheet name (`sample`), and the whole Results sheet is kept as the `results` table:

```json
"name_from": "sheet",
"formats": [
  { "label": "lap shear", "file": { "extensions": [".xlsx"], "contains": "Shearing stress",
                                     "header": { "starts_at": "Strain", "rows": 2 } },
    "columns": [ { "source": "Strain mm", "quantity": "strain", "unit": "mm" },
                 { "source": "Shearing stress MPa", "quantity": "shear_stress", "unit": "MPa" } ] },
  { "label": "tensile", "file": { "extensions": [".xlsx"], "contains": "Elongation",
                                   "header": { "starts_at": "Elongation", "rows": 2 } },
    "columns": [ { "source": "Elongation %", "quantity": "strain", "unit": "%" },
                 { "source": "Standard force kPa", "quantity": "stress", "unit": "kPa" } ] }
],
"from_header": [
  { "column": "test_date", "pattern": "^{sheet}\\t([0-9]+\\.[0-9]+)\\t", "type": "datetime", "timezone": "Europe/Zurich" }
],
"tables": [
  { "name": "results", "sheet": "Results", "header": { "rows": 2 }, "columns": ["specimen"] }
]
```

`dataset.metadata["tables"]["results"]["LUB645.xlsx"]` is then one record per specimen:

```python
[{"specimen": "LUB645", "Date/Clock time": 46246.7499, "L0 mm": 13.48, "Et kPa": 129.66,
  "sM kPa": 11.57, "eM %": 353.30, "sB MPa": 0.00088, "eB %": 596.47, "h mm": 0.4, "b mm": 3.73, "A0 mm²": 1.492},
 ...]
```

#### Several samples in one workbook: current limits

**One file is one experiment.** A registry row points at one raw file, and a file name can be used only once per instrument. A workbook holding several samples, such as `LUB640toLUB644.xlsx` with samples LUB640 to LUB644 and their replicates, is therefore **one experiment**, with one curve per test sheet (`LUB640`, `LUB640_1`, …, `LUB644_2`). What that means in practice:

- Every test is read and kept, and each curve carries its sheet name (and its own `test_date`).
- To look at one sample, filter the experiment's curves by name (e.g. names starting with `LUB642`).
- A single sample (LUB642) is not an experiment of its own. It can't be loaded by name, compared with other experiments as one, or given its own registry row (sample ID, description).
- Runs that are not samples (a calibration or trial run such as `check2`) are read like the others. Name the sheets so the curves say what they are.

If samples must be separate experiments, export one workbook per sample (`LUB642.xlsx`) from the instrument software. Splitting a workbook *inside* mfethuls is planned in stages. The first is done: every curve has a `sample` column taken from its sheet name, so the curves group, colour and filter by sample (in the app, **Filter** and **Colour by** offer `sample`). Next would be selecting curves by sample when loading. Only if those turn out not to be enough would registry rows point into a workbook, which needs a change to how experiments are identified.

---

## Another instrument of the same kind

A second instrument that writes the same files as one mfethuls already reads (a second Bruker NMR, an
identical DSC in another room) needs no definition of its own. Save a small file in the data folder's
`.mfethuls/instruments/`, e.g. `nmr600.json`:

```json
{ "name": "nmr600", "same_as": "nmr", "folder_name": "NMR600" }
```

- `name`: the new instrument, as the registry's `instrument_name` will say it.
- `same_as`: the instrument whose reader it uses: a built-in one (`nmr`, `dsc_mettler_toledo_v1`, ...; see
  **⚙ Settings → Instruments** or `mfethuls instruments`) or one of the lab's definitions.
- `folder_name`: its own folder in the data folder. One kind of measurement per folder: a folder another type
  of instrument reads is refused.
- `description` is optional; nothing else is accepted.

It then appears in **⚙ Settings → Instruments** (*read by: same as nmr*); its folder can be changed there like
any other's, and **Remove** takes it away again. Its data is read exactly like the instrument it names, and when
that instrument's reader changes, **Clean up** offers to read both again.

## Safety nets

- **The sample file is re-read** whenever mfethuls loads the definitions. If an update of mfethuls (or an edit) changes what it reads, **⚙ Settings → Instruments** says so.
- **Edits are tracked.** Each ingested dataset records which reader read it: the version of its definition, or of mfethuls' own parser for code-read instruments. After a definition changes, or after an update of mfethuls improves a parser, **⚙ Settings → Clean up** lists those experiments as *Read again* and re-reads their raw data.
- **Lab definitions override built-in ones** with the same name, for that data folder only. A definition that is invalid is not used, and Settings shows why.
- **Definitions are data, not code.** Treat one from a chatbot or a colleague like any file you did not write, but it can only describe how to read a table: nothing in it is run. mfethuls also checks:
  - **Patterns** (`pattern`, `values`, `names_from`, `blocks.label`) may be at most 300 characters. A pattern that repeats a part that itself repeats, such as `(\w+\s?)+`, is refused: on some lines it can take hours. Write `[\w\s]+` instead. Every search also has a time limit (0.5 s per line). A pattern that hits it fails that file with a message naming the pattern, instead of freezing ingest.
  - **Names stay inside the data folder.** `folder_name` and `check.sample` must be plain names, without `/`, `\` or `..`. A `timezone` must be a zone name such as `Europe/Zurich`.
  - **Size.** A definition file may be at most 256 kB. A broken lab file only switches off that one instrument.

## When a definition is not enough

Definitions read text files and Excel workbooks: one table, the same table repeated in blocks (one per interval) or on several sheets (one per test), with the text around it. Instruments that write binary files (Bruker NMR) or need calculations beyond the `derived` operations are read by code parsers in mfethuls (`src/mfethuls/parsers/`). Today this is NMR only; every other built-in instrument is a definition. They keep everything too: every row and column, and the text around the table in the dataset's metadata (`file_text`). Ask for one in an issue, with an example file.
