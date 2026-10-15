# Experiment Registry Reference

The registry is a CSV or XLSX spreadsheet that serves as the primary interface between experimentalists and the mfethuls pipeline. Every experiment you want to ingest must have a row here. The file lives on a shared location (OneDrive, network share, S3) so the whole team works from the same source of truth.

---

## Column reference

| Column | Required | Format | Description |
|--------|----------|--------|-------------|
| `name` | **yes** | free text, unique | Human-friendly label used as the lookup key throughout the system (e.g. `CL_dsc_001`). This is the primary identifier — it appears in the Streamlit browser, API responses, and DuckDB view names. Should be short and stable. |
| `instrument_name` | **yes** | see table below | Instrument configuration name from `instrument_params.json`. Must match exactly. |
| `raw_data_filename` | no | filename stem (no extension) | The filename stem of the raw data export (e.g. `chitosan_jan15` for `chitosan_jan15.txt`). If absent, defaults to `name`. Used to locate the file anywhere under the instrument folder. |
| `sample_id` | no | `S` + 3–6 digits | Identifies the sample (e.g. `S001`). Included in the Parquet filename. |
| `run_id` | no | `R` + 3–6 digits | Run number within a sample (e.g. `R001`). Defaults to `R001` when absent. |
| `measurement_profile` | conditional | see profiles table | Required for **rheometer** and **DMA** experiments (see below). Ignored for other instruments. |
| `description` | no | free text | Free-text description. If `measurement_profile` is missing, mfethuls will attempt to infer a profile from the description (e.g. "frequency sweep" → `oscillatory_frequency_sweep`). |
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

| `instrument_name` | Instrument type | Folder in `PATH_TO_DATA` | Notes |
|-------------------|----------------|--------------------------|-------|
| `dsc` | DSC — prior model | `DSC/` | |
| `dsc_perkin_elmer` | DSC — PerkinElmer | `DSC/` | Higher sensitivity |
| `dsc_mettler_toledo` | DSC — Mettler Toledo | `DSC/` | |
| `uv_vis` | UV-Vis — Shimadzu | `UV_Vis/` | |
| `uv_insitu` | UV-Vis in-situ — Ocean Insight Flame | `UV_Vis/` | |
| `fluorescence_insitu` | Fluorescence in-situ — Ocean Insight Flame | `Fluorescence/` | Same parser as `uv_insitu` |
| `rheometer` | Rheometer — Anton Paar | `Rheology/` | `measurement_profile` recommended |
| `tga` | TGA | `TGA/` | |
| `nmr` | NMR — Bruker | `NMR/` | |
| `ftir` | FTIR — Bruker | `FTIR/` | |
| `sec` | SEC — Agilent | `SEC/` | |
| `dma` | DMA — TA Q800 | `DMA/` | `measurement_profile` recommended |
| `saxs` | SAXS — Anton Paar | `SAXS/` | |
| `ms` | MS — Bruker | `MS/` | |

---

## Measurement profiles (rheometer and DMA)

Rheometer and DMA experiments can contain data from several different measurement types in the same folder. The `measurement_profile` column tells mfethuls which schema to apply. Without it, the parser will attempt inference but may choose the wrong profile.

### Rheometer profiles

| `measurement_profile` value | What it means |
|----------------------------|---------------|
| `oscillatory_frequency_sweep` | Frequency sweep — ω vs G′, G″ |
| `oscillatory_strain_sweep` | Amplitude sweep — strain % vs G′, G″ |
| `oscillatory_time_sweep` | Time sweep — time vs G′, G″ |
| `flow_curve` | Viscometry — shear rate vs stress, viscosity |

### DMA profiles

| `measurement_profile` value | What it means |
|----------------------------|---------------|
| `oscillatory_temperature_sweep` | Temperature ramp — T vs E′, E″, tan δ |
| `oscillatory_frequency_sweep` | Frequency sweep — f vs E′, E″ |
| `oscillatory_strain_sweep` | Amplitude sweep — strain vs E′, E″ |
| `oscillatory_time_sweep` | Time sweep — time vs E′, E″ |

The profile value is flexible — mfethuls accepts common synonyms and normalises them:

```
"frequency sweep"         → oscillatory_frequency_sweep
"Frequency Sweep"         → oscillatory_frequency_sweep
"oscillatory_freq_sweep"  → oscillatory_frequency_sweep
"flow curve"              → flow_curve
"temperature"             → oscillatory_temperature_sweep
```

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
- The filename stem must match `raw_data_filename` exactly (case-sensitive on Linux). Every file with that stem is collected, e.g. both `poly1.txt` and `poly1.csv`.
- If the same filename stem exists in more than one subfolder, ingest raises an error — rename one of the files to remove the ambiguity.
- A name must match **either** a file **or** a folder, not both. If `poly1.txt` and a folder `poly1/` both exist in different places under the instrument folder, ingest raises an error — rename one of them. A file inside a folder of the same name (`LUB055/LUB055.txt`) is not a conflict: `LUB055` means the folder. To mean only that file (one run of a folder registered per file), give its file name with the extension: `LUB055.txt`.
- Only files the instrument reads are data (its file extension, e.g. `.txt` for DSC, plus `.csv` for some DSC and TGA models). Other files next to the data, such as a plot saved in the experiment folder, are skipped at ingest with a warning naming them. Notes are better kept in the registry `description`.
- An experiment may be renamed: change `name` in the registry and ingest again. The experiment keeps its internal ID, because the ID is tied to the instrument and `raw_data_filename`. Renaming the raw data file makes it a new experiment.
- If no matching file is found at ingest time, the row produces a **warning** (not an error) — the experiment can be ingested later once the file is present.

When an experiment has several files (a folder per experiment, or several files with the same stem), each data row gets a `source_file` column with the stem of the file it came from. A titration or time series therefore stays separable: the built-in plots draw one line per file.

---

## Registering new data from the app

Instead of typing rows by hand, let the Streamlit app find raw data that is not in the registry yet. In the sidebar, the **Ingest** section shows "**N new data items found in the data folder**". Click **Review & register**.

**Narrowing the list:** the dialog starts with data **modified in the last 30 days**, newest first (or with everything, if nothing is that recent). Above the table you can change the period (7 days, 30 days, 3 months, All), pick **Instruments** to show only some instrument folders, and **Search** by file or folder name. Searching also looks at the files inside a subfolder, so a project folder is found by the name of a file in it. Changing a filter clears ticks and edits in the table.

**What is proposed:**
- **A file directly in an instrument folder** (`DSC/poly2.txt`) is one experiment; its `raw_data_filename` is the stem.
- **A subfolder holding a single file** (`DSC/LUB055/LUB055.txt`) is proposed as that file.
- **A subfolder** (`UV_Vis/titration_A/`, `DSC/poly1/`) is proposed once, and you decide whether it is:
  - **one experiment**: the whole folder, e.g. a titration or a time series (`raw_data_filename` = the folder name), or
  - **one experiment per file**: each file is a run of the same sample, numbered R001, R002, … in file-name order.

  Pick the folders to split in **Folders to register as one experiment per file**. The default depends on the instrument: folders of series instruments (Flame UV-Vis/fluorescence, NMR) stay whole, folders of single-file instruments (DSC, TGA, FTIR, …) are split.
- **Pre-filled:** `raw_data_filename`, `run_id`, the instrument when only one fits the folder, and the `name` (the file or folder name, made unique). When a folder is split and one of its files is named like the folder, that row's `raw_data_filename` is the file name with its extension (`LUB055.txt`), since the bare name means the whole folder.
- **You choose** which rows to register by ticking **Register**; nothing is ticked at first.
- **You fill in:** `sample_id`, the instrument where several share a folder (e.g. the DSC models in `DSC/`), `measurement_profile` for DMA and rheometer data, and any other columns your registry has.

**Validation** runs as you type, with the same checks as ingest. It also requires the instrument to be chosen, the raw data to be found exactly once, and the data to read as the chosen instrument's: the first file is test-read with that instrument's parser, so files of another instrument (say, Shimadzu UV-Vis files offered as in-situ Flame data) are flagged before they are registered. Ingest makes the same check on every file and stops with an error instead of storing data it could not read properly. Rows with problems are marked ✗ with the reason. Data that cannot be registered as found (for example the same file name in two folders) is listed under **Not proposed**, with the reason. Files next to the data that no instrument reads, such as plots, are listed under **Files that will not be read**. They don't stop a row from being registered, and a folder holding only such files isn't proposed.

**Saving:**
- **Save to registry** appends the rows to your CSV or XLSX registry. Existing rows, formatting and other sheets are kept, and the previous version is saved next to it as `<name>.bak.csv` / `<name>.bak.xlsx`. **Save & ingest** also ingests the new experiments. If the registry is open in Excel, close it and save again.
- When the registry is kept elsewhere (for example on OneDrive for a team server), the app does not write it: download the rows (`.csv` or `.xlsx`) and add them to the registry there.

Which instruments share a folder, and whether they record series, is set per instrument in `config/instrument_params.json` (`folder_name`, `data_layout`).

---

## Cleaning up after registry changes

The registry is the source of truth. Ingesting builds everything else from it: the manifest (each experiment's internal ID), the catalog the app lists and the stored Parquet files. When you remove, rename or correct rows, those can fall out of step. **Clean up** brings them back in line. Your raw data is never touched.

In the app, open **⚙ Settings** (top of the sidebar) → **Clean up** and press **Check**. It lists what it would do, and nothing changes until you press **Apply**:

| Action | When | What happens |
|---|---|---|
| **Forget** | A row was removed from the registry | Its catalog entry, stored files and manifest entry are deleted. Re-adding the row later ingests it as a new experiment. |
| **Refresh** | A row's `name`, `sample_id` or `run_id` changed, or it is missing from the catalog | It is ingested again: from the stored copy when the data is unchanged, otherwise from the raw file. It keeps its internal ID. |
| **Relink** | A raw file was renamed and the row's `raw_data_filename` updated | Recognised by identical file contents, so the experiment keeps its ID and stored data instead of being forgotten and ingested anew. |
| **Remove files** | Stored files nothing uses (old versions after a sample or run change) | Deleted. |

Check also lists rows that were never ingested, and experiments whose raw data is identical.

**Safety:** rows that are in the registry but invalid (a typo in `sample_id`, say) still protect their data. A plan that would forget more than 10% of your experiments (at least 3) needs an extra confirmation, because a registry file that only partly synced from OneDrive looks just like deleted rows. **Apply** only does what **Check** showed: if anything changed in between, it asks you to check again.

From the command line: `python -m mfethuls.reconcile` shows the plan, and `python -m mfethuls.reconcile --apply` carries it out (`--force` for a large forget).

---

## Example registry

A realistic multi-instrument registry for one research batch:

```
name,instrument_name,sample_id,run_id,raw_data_filename,measurement_profile,description,batch,operator
CL_dsc_001,dsc_mettler_toledo,S001,R001,,,PB-2024-01,Maria
CL_dsc_002,dsc_mettler_toledo,S002,R001,,,PB-2024-01,Maria
CL_dsc_002_repeat,dsc_mettler_toledo,S002,R002,dsc_s002_run2,,PB-2024-01,Maria
CL_tga_001,tga,S001,R001,,,PB-2024-01,Carlos
CL_rheometer_freq,rheometer,S003,R001,,oscillatory_frequency_sweep,,PB-2024-01,Priya
CL_rheometer_flow,rheometer,S003,R001,,flow_curve,viscometry at 25C,PB-2024-01,Priya
CL_dma_temp,dma,S004,R001,,oscillatory_temperature_sweep,Tg measurement,PB-2024-01,Carlos
CL_ftir_001,ftir,S001,R001,,,PB-2024-01,Maria
CL_sec_001,sec,S002,R001,,,PB-2024-01,Priya
CL_nmr_001,nmr,S001,R001,,,PB-2024-01,Maria
CL_uv_kinetics,uv_insitu,S005,R001,,UV kinetics monitoring,PB-2024-01,Carlos
CL_saxs_001,saxs,S003,R001,,,PB-2024-01,Priya
CL_pending,,,,,Planned — not yet run,,
```

**Notes on the example above:**

- `CL_dsc_001` and `CL_dsc_002` leave `raw_data_filename` blank — the system looks for a file named `CL_dsc_001.*` and `CL_dsc_002.*` inside the `DSC/` folder.
- `CL_dsc_002_repeat` uses an explicit `raw_data_filename = dsc_s002_run2` because the raw file has a different name to the registry entry.
- `CL_pending` has no `instrument_name` — this row will be skipped at ingest with a warning. Keep it in the registry as a placeholder and fill it in before ingesting.
- `batch` and `operator` are custom columns; they are stored as metadata alongside each experiment.
- `CL_rheometer_flow` uses a free-text `description` instead of `measurement_profile`. mfethuls infers `flow_curve` from the word "viscometry". Explicit `measurement_profile` is preferred where possible.

---

## Tips for experimentalists

**Naming convention:** establish a lab-wide prefix (e.g. `CL_` for your group) and use the instrument type as part of the name. This makes the dataset list in the Streamlit dashboard much easier to scan.

**One row per run:** if you repeat an experiment (`R001`, `R002`), create a separate row for each run. The `name` must be unique across all rows.

**When raw_data_filename differs from name:** if your instrument's export file has a name that doesn't match the registry entry (e.g. the instrument auto-generates filenames), set `raw_data_filename` to the file stem. Otherwise, leave it blank and keep the file named after the registry `name`.

**Removing or renaming rows:** edit the registry, then run **Clean up** (see [Cleaning up after registry changes](#cleaning-up-after-registry-changes)) so the app's dataset list follows. Renaming keeps an experiment's internal ID; removing a row forgets its ingested data, never the raw files.

**Validate before you ingest:** `Registry.load(path).problems` lists rows that would be skipped and why, so you can catch formatting errors before starting a long ingest.

**Custom columns are fine:** any column beyond the standard set is stored as experiment metadata. Use them freely for concentration, solvent, temperature, batch number, etc.
