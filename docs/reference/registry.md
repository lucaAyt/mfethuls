# Experiment Registry Reference

The registry is a CSV or XLSX spreadsheet that serves as the primary interface between experimentalists and the mfethuls pipeline. Every experiment you want to ingest must have a row here. The file lives on a shared location (OneDrive, network share, S3) so the whole team works from the same source of truth.

---

## Column reference

| Column | Required | Format | Description |
|--------|----------|--------|-------------|
| `name` | **yes** | free text, unique | Human-friendly label used as the lookup key throughout the system (e.g. `CL_dsc_001`). This is the primary identifier — it appears in the Streamlit browser, API responses, and DuckDB view names. Should be short and stable. Names must also differ as table names, which ignore case and turn characters other than letters, digits and `_` into `_`: `PEG-1` and `PEG_1`, or `LUB446` and `lub446`, cannot both be used. |
| `instrument_name` | **yes** | see table below | Instrument name: a built-in instrument (table below) or one added by the lab ([adding an instrument](../guides/instruments.md)). Must match exactly. |
| `raw_data_filename` | no | filename stem (no extension) | The filename stem of the raw data export (e.g. `chitosan_jan15` for `chitosan_jan15.txt`). If absent, defaults to `name`. Used to locate the file anywhere under the instrument folder. |
| `sample_id` | no | `S` + 3–6 digits | Identifies the sample (e.g. `S001`). Included in the Parquet filename. |
| `run_id` | no | `R` + 3–6 digits | Run number within a sample (e.g. `R001`). Defaults to `R001` when absent. |
| `description` | no | free text | Free-text description. |
| any other column | no | any | Stored as metadata alongside the experiment. Useful for batch, operator, sample concentration, etc. |

---

## Identifier formats

`experiment_id` is auto-assigned by the system — you do not write it in the registry. The identifiers you provide are:

| Identifier | Pattern | Examples |
|------------|---------|---------|
| `sample_id` | `S` + 3–6 digits | `S001`, `S12`, `S1000` |
| `run_id` | `R` + 3–6 digits | `R001`, `R002` |

These are optional and validated on load. Rows with malformed identifiers are skipped with a warning.

---

## Supported instruments

An **instrument** is where data comes from: one folder of the data folder, and what `instrument_name` says.
Its files are read by the **readers** of its measurement type, one per export format; each experiment by the
reader that recognises its files (see [readers](#readers-export-formats) below). The registry never names a
reader.

| `instrument_name` | Measurement type | Folder in `PATH_TO_DATA` |
|-------------------|------------------|--------------------------|
| `dsc` | DSC | `DSC/` |
| `tga` | TGA | `TGA/` |
| `ftir` | FTIR | `FTIR/` |
| `uv_vis` | UV-Vis (`uv_vis`) | `UV_Vis/` |
| `fluorescence` | Fluorescence | `Fluorescence/` |
| `rheometer` | Rheology | `Rheology/` |
| `dma` | DMA | `DMA/` |
| `sec` | SEC | `SEC/` |
| `saxs` | SAXS | `SAXS/` |
| `ms` | MS | `MS/` |
| `nmr` | NMR | `NMR/` |
| `tensile_tester` | Tensile and lap shear (`tensile`) | `tensile_tester/` |

The lab's own instruments (**⚙ Settings → Instruments**, or `mfethuls instruments`) are listed there too: a
second DSC in another room, in-situ spectra kept apart from other UV-Vis data, or an instrument mfethuls did not
know ([adding an instrument](../guides/instruments.md)).

**One folder, one instrument.** Each folder of the data folder belongs to one instrument, and holds one type of
data. Below it, organise as you like (`DSC/2024/thesis/LUB055.txt`). A second machine of a kind, or data you
keep apart, is a second instrument with a folder of its own; both are plotted and queried together by their type.

### Readers (export formats)

| Type | Reader | Format | Notes |
|------|--------|--------|-------|
| DSC | `dsc_mettler_toledo_v1` | Mettler Toledo, current export | |
| DSC | `dsc_mettler_toledo_v0` | Mettler Toledo, older STARe export (`Curve Values:`) | heat flow as exported in `heat_flow_W_g` (W/g); the sample mass after the table gives `sample_mass_mg` and `heat_flow_mW` too |
| DSC | `dsc_perkin_elmer` | PerkinElmer Pyris text or CSV export | segment lines kept as a `segment` column; time read in minutes; `Sample Weight` gives `sample_mass_mg` and `heat_flow_W_g` |
| UV-Vis | `uv_vis` | Shimadzu UVProbe | `titrant` from the file name |
| UV-Vis | `uv_insitu` | Ocean Insight Flame series | one folder per experiment; `timestamp` from the header date plus the milliseconds in the file name |
| Fluorescence | `fluorescence_insitu` | Ocean Insight Flame series | same layout as `uv_insitu` |
| Rheology | `rheometer` | Anton Paar | one table per interval, numbered in the `interval` column |
| TGA | `tga` | `.txt` text export and `.csv` export | `mass_pct` is % of the initial mass |
| Tensile | `tensile_tester` | ZwickRoell testXpert, Excel `.xlsx` | lap shear (`strain_mm`, `shear_stress_mpa`) and tensile tests (`strain_pct`, `stress_mpa`); one curve per test sheet; `test_date` from the Results sheet. A workbook with several samples is one experiment (see below) |
| NMR | `nmr` | Bruker (code reader) | one dataset folder per experiment, as TopSpin writes it (`NMR/EXP014/1/pdata/1/1r`); `raw_data_filename` = the dataset folder. Every processed spectrum (`<expno>/pdata/<procno>`) is read once, named in `source_file` (`1/pdata/1`), with its `nucleus` and `solvent` on every row; parameters and title in `file_text` |
| FTIR | `ftir` | Bruker | |
| SEC | `sec` | Agilent | `detector_name` (ri, uv, ls, viscometer) from the file name |
| DMA | `dma` | TA Q800 | column names from the `SigN` lines; time read in minutes |
| SAXS | `saxs` | Anton Paar | |
| MS | `ms` | Bruker | rows written twice left out; the `MS Peak List` stored in metadata (`tables.peak_list`) |

When several readers of a type read a file's ending, the one that **recognises** the file reads it: by the text
its format looks for (`contains` / `not_contains`) and its header line (`header.starts_at`) near the top. A reader
that recognises a file this way wins over one that looks for nothing and takes any file of its ending. A file
none of them recognises, or more than one, is reported in Review & register and at ingest, never guessed. The
reader of each dataset is stored with it (catalog column `reader`); a reader added later never reads stored data
again by itself.

---

**Your folder has another name?** The folders above are where each built-in instrument looks. If yours is called
differently (`DSC data`, `Rheometer 2024`), the app lists it under **Ingest** as a folder no instrument reads yet:
open **Review & register** and choose the type of data it holds (mfethuls reads a few of its files to suggest it,
else goes by the folder's name). When the type's built-in instrument's folder is not in the data folder, that
instrument reads yours instead (`dsc` reads `DSC data`); otherwise a new instrument, named after your folder,
reads it. The choice is saved in the data folder (`.mfethuls/instruments/`), so everyone using it gets the same
folders; move an instrument later under **⚙ Settings → Instruments → Change an instrument's folder**.

**DMA and rheometer data need no extra column.** Their built-in plots read what each run swept from the data: the quantity that changes (temperature, frequency, strain, or shear rate for a flow curve) is the x-axis, and a run where only time changes is a time sweep. A `measurement_profile` column from older registries is kept as an ordinary column.

If you are unsure, check the registry before ingesting: rows that do not validate are listed with the reason in the app's **Register new data** dialog, and `Registry.load(path).problems` lists them in Python.

---

## Data folder layout

Raw data files can be placed **anywhere** inside the instrument folder — in a subfolder, nested further, or at the root. mfethuls walks the folder tree to find the file whose stem matches `raw_data_filename` (or `name` if `raw_data_filename` is absent).

```
PATH_TO_DATA/
  DSC/
    chitosan_jan15.txt          ← found by raw_data_filename = "chitosan_jan15"
    batch_2/
      another_sample.txt        ← found by raw_data_filename = "another_sample"
  TGA/
    tga_exp_001.csv             ← found by raw_data_filename = "tga_exp_001"
  Rheology/
    freq_sweep_S003_R001.txt
```

Several experiments can share one folder. Each experiment only gets the files whose stem matches its own `raw_data_filename`. Other files in the folder are ignored.

**Folder per experiment:** some instruments write many files per run (e.g. UV-Vis in-situ, fluorescence kinetics, NMR). Put those files in a folder named after the experiment and set `raw_data_filename` to the folder name. All files directly inside that folder are collected.

```
PATH_TO_DATA/
  Fluorescence/
    poly3/                      ← found by raw_data_filename = "poly3"
      t001.txt
      t002.txt
```

**Rules:**
- Name files and folders as you like: spaces, brackets and accents are fine (`poly 1 (repeat).txt`). Only the characters `/ \ : * ? " < > |` and spaces at the start or end are not allowed in `raw_data_filename`, since they can't be part of a file name everywhere.
- The filename stem must match `raw_data_filename`, ignoring case: `lub446` finds `LUB446.txt`. Every file with that stem is collected, e.g. both `poly1.txt` and `poly1.csv`. Two files whose names differ only in case (`LUB446.txt` and `lub446.txt`, possible on Linux) are an error: rename one.
- If the same filename stem exists in more than one subfolder, ingest raises an error — rename one of the files to remove the ambiguity.
- A name must match **either** a file **or** a folder, not both. If `poly1.txt` and a folder `poly1/` both exist in different places under the instrument folder, ingest raises an error — rename one of them. A file inside a folder of the same name (`LUB055/LUB055.txt`) is not a conflict: `LUB055` means the folder. To mean only that file (one run of a folder registered per file), give its file name with the extension: `LUB055.txt`.
- Only files the instrument reads are data (its file extension, e.g. `.txt` for DSC, plus `.csv` for some DSC and TGA models). Other files next to the data, such as a plot saved in the experiment folder, are skipped at ingest with a warning naming them. Notes are better kept in the registry `description`.
- An experiment may be renamed: change `name` in the registry and ingest again. The experiment keeps its internal ID, because the ID is tied to the instrument and `raw_data_filename`.
- A raw data file may be renamed too: rename it, update `raw_data_filename` and ingest (or run **Clean up**). mfethuls recognises the file by its contents and the experiment keeps its ID and stored data, as long as exactly one experiment that no row uses any more had those contents.
- The internal ID is derived from the instrument and `raw_data_filename`, so every computer gives an experiment the same ID.
- If no matching file is found at ingest time, the row produces a **warning** (not an error) — the experiment can be ingested later once the file is present.

A folder per experiment is collected with its subfolders (Bruker NMR keeps the spectrum in `<expno>/pdata/<procno>/`); hidden folders are left out. When an experiment has several files (a folder per experiment, or several files with the same stem), each data row gets a `source_file` column with the stem of the file it came from. A titration or time series therefore stays separable: the built-in plots draw one line per file.

**One raw file is one experiment.** A file holding several samples, such as an Excel workbook from a tensile tester with one sheet per specimen (`LUB640toLUB644.xlsx`), can't be split across registry rows, because `raw_data_filename` may appear only once per instrument. Register the workbook as **one** experiment: every test is kept as its own curve (named after its sheet, e.g. `LUB642_1`), and you filter curves by name to look at one sample. If each sample needs its own registry row (sample ID, description), export one file per sample from the instrument software. See [several samples in one workbook](../guides/instruments.md#several-samples-in-one-workbook-current-limits).

---

## Registering new data from the app

Instead of typing rows by hand, let the Streamlit app find raw data that is not in the registry yet. In the sidebar, the **Ingest** section shows "**N new data items found in the data folder**". Click **Review & register**.

**Narrowing the list:** the dialog starts with data **modified in the last 30 days** (or with everything, if nothing is that recent). Above the table you can change the period (7 days, 30 days, 3 months, All), pick **Instruments** to show only some instrument folders, and **Search** by file or folder name. Searching also looks at the files inside a subfolder, so a project folder is found by the name of a file in it. Changing a filter clears ticks and edits in the table.

**What is proposed:** the new data, laid out like the data folder (in path order), each subfolder followed by the files in it.
- **A file directly in an instrument folder** (`DSC/poly2.txt`) is one experiment; its `raw_data_filename` is the stem.
- **A subfolder holding a single file** (`DSC/LUB055/LUB055.txt`) is proposed as that file.
- **A subfolder of files of a single-file instrument** (`DSC/poly1/`: DSC, TGA, FTIR, …): ticking the **📁 folder** ticks all the files under it, each **one experiment**: a run of the same sample, numbered R001, R002, … in file-name order. Untick the files you don't want; unticking the folder unticks them all. Folders start closed (▸), with how many of their files are ticked; tick **Open** to see and edit the files (▾). A sample, instrument or description typed in the folder's row fills in its files, except those you gave a value of their own.
- **A subfolder of an instrument with a series reader** (`UV_Vis/titration_A/`, Flame UV-Vis/fluorescence, NMR) is marked **one experiment**: ticking it registers all its files together, e.g. a titration or a time series (`raw_data_filename` = the folder name). Where a single-file reader of the instrument also reads its files, they are listed under it too; ticking the folder and its files at once is flagged, so the data is not registered twice.
- **Pre-filled:** `raw_data_filename`, `run_id`, the instrument (the one whose folder the data is in; it is not changed here), and the `name` (the file or folder name, made unique). When a folder is split and one of its files is named like the folder, that row's `raw_data_filename` is the file name with its extension (`LUB055.txt`), since the bare name means the whole folder.
- **You choose** which rows to register by ticking **Register**; nothing is ticked at first.
- **You fill in:** `sample_id`, the instrument where several share a folder (e.g. the DSC models in `DSC/`), and any other columns your registry has.

**Validation** runs as you type, with the same checks as ingest. It also requires the raw data to be found exactly once, and to read as its instrument's data: the instrument is the one whose folder the data is in, and the first file is test-read with the reader that recognises it, so data of another type (say, a DSC export in the UV-Vis folder) is flagged before it is registered. Ingest makes the same check on every file and stops with an error instead of storing data it could not read properly. Rows with problems are marked ✗ with the reason. Data that cannot be registered as found (for example the same file name in two folders) is listed under **Not proposed**, with the reason. Files next to the data that no instrument reads, such as plots, are listed under **Files that will not be read**. They don't stop a row from being registered, and a folder holding only such files isn't proposed.

**Saving:**
- **Save to registry** appends the rows to your CSV or XLSX registry. Existing rows, formatting and other sheets are kept, and the previous version is saved next to it as `<name>.bak.csv` / `<name>.bak.xlsx`. **Save & ingest** also ingests the new experiments. If the registry is open in Excel, close it and save again.
- When the registry is kept elsewhere (for example on OneDrive for a team server), the app does not write it: download the rows (`.csv` or `.xlsx`) and add them to the registry there.

Which folder an instrument reads is set per instrument (`config/instruments.json`, or the lab's own in `PATH_TO_DATA/.mfethuls/instruments/`); whether an experiment is one file or a series is set per reader (`data_layout`: `config/readers/*.json`, `config/code_readers.json`, or the lab's own in `PATH_TO_DATA/.mfethuls/readers/`).

---

## Cleaning up after registry changes

The registry is the source of truth. Ingesting builds everything else from it: the manifest (each experiment's internal ID), the catalog the app lists and the stored Parquet files. When you remove, rename or correct rows, those can fall out of step. **Clean up** brings them back in line. Your raw data is never touched.

In the app, a note under **Datasets** says when ingested data no longer matches the registry; **Review** opens Clean up with its plan. Clean up is also under **⚙ Settings** (top of the sidebar) → **Clean up** → **Check**. It lists what it would do, and nothing changes until you press **Apply**:

| Action | When | What happens |
|---|---|---|
| **Forget** | A row was removed from the registry | Its catalog entry, stored files and manifest entry are deleted. Re-adding the row later ingests it as a new experiment. |
| **Refresh** | A row's `name`, `sample_id` or `run_id` changed, or it is missing from the catalog | It is ingested again: from the stored copy when the data is unchanged, otherwise from the raw file. It keeps its internal ID. |
| **Relink** | A raw file was renamed and the row's `raw_data_filename` updated | Recognised by identical file contents, so the experiment keeps its ID and stored data instead of being forgotten and ingested anew. Ingesting the row does the same, so the order (Clean up first or ingest first) does not matter. |
| **Read again** | The reader changed since the data was read (an instrument definition was edited, or mfethuls' own parser changed version) | The raw data is read again with the current reader. |
| **Remove files** | Stored files nothing uses (old versions after a sample or run change) | Deleted. |

Check also lists rows that were never ingested, and experiments whose raw data is identical.

**Safety:** rows that are in the registry but invalid (a typo in `sample_id`, say) still protect their data. A plan that would forget more than 10% of your experiments (at least 3) needs an extra confirmation, because a registry file that only partly synced from OneDrive looks just like deleted rows. **Apply** only does what **Check** showed: if anything changed in between, it asks you to check again.

From the command line: `mfethuls cleanup` shows the plan, and `mfethuls cleanup --apply` carries it out (`--force` for a large forget).

---

## Example registry

A realistic multi-instrument registry for one research batch:

```
name,instrument_name,sample_id,run_id,raw_data_filename,description,batch,operator
CL_dsc_001,dsc,S001,R001,,,PB-2024-01,Maria
CL_dsc_002,dsc,S002,R001,,,PB-2024-01,Maria
CL_dsc_002_repeat,dsc,S002,R002,dsc_s002_run2,,PB-2024-01,Maria
CL_tga_001,tga,S001,R001,,,PB-2024-01,Carlos
CL_rheometer_freq,rheometer,S003,R001,,frequency sweep,PB-2024-01,Priya
CL_rheometer_flow,rheometer,S003,R001,,viscometry at 25C,PB-2024-01,Priya
CL_dma_temp,dma,S004,R001,,Tg measurement,PB-2024-01,Carlos
CL_ftir_001,ftir,S001,R001,,,PB-2024-01,Maria
CL_sec_001,sec,S002,R001,,,PB-2024-01,Priya
CL_nmr_001,nmr,S001,R001,,,PB-2024-01,Maria
CL_uv_kinetics,uv_vis,S005,R001,,UV kinetics monitoring,PB-2024-01,Carlos
CL_saxs_001,saxs,S003,R001,,,PB-2024-01,Priya
CL_pending,,,,,Planned — not yet run,,
```

**Notes on the example above:**

- `CL_dsc_001` and `CL_dsc_002` leave `raw_data_filename` blank — the system looks for a file named `CL_dsc_001.*` and `CL_dsc_002.*` inside the `DSC/` folder.
- `CL_dsc_002_repeat` uses an explicit `raw_data_filename = dsc_s002_run2` because the raw file has a different name to the registry entry.
- `CL_pending` has no `instrument_name` — this row will be skipped at ingest with a warning. Keep it in the registry as a placeholder and fill it in before ingesting.
- `batch` and `operator` are custom columns; they are stored as metadata alongside each experiment.
- The rheometer and DMA rows need nothing extra: their plots see from the data that `CL_rheometer_flow` is a flow curve and `CL_dma_temp` a temperature sweep. The `description` is only for people.

---

## Tips for experimentalists

**Naming convention:** establish a lab-wide prefix (e.g. `CL_` for your group) and use the instrument type as part of the name. This makes the dataset list in the Streamlit dashboard much easier to scan.

**One row per run:** if you repeat an experiment (`R001`, `R002`), create a separate row for each run. The `name` must be unique across all rows.

**When raw_data_filename differs from name:** if your instrument's export file has a name that doesn't match the registry entry (e.g. the instrument auto-generates filenames), set `raw_data_filename` to the file stem. Otherwise, leave it blank and keep the file named after the registry `name`.

**Removing or renaming rows:** edit the registry, then run **Clean up** (see [Cleaning up after registry changes](#cleaning-up-after-registry-changes)) so the app's dataset list follows. Renaming keeps an experiment's internal ID; removing a row forgets its ingested data, never the raw files.

**Validate before you ingest:** `Registry.load(path).problems` lists rows that would be skipped and why, so you can catch formatting errors before starting a long ingest.

**Custom columns are fine:** any column beyond the standard set is stored as experiment metadata. Use them freely for concentration, solvent, temperature, batch number, etc.
