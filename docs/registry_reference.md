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
| `uv_vis` | UV-Vis — Shimadzu | `UV_VIS/` | |
| `uv_insitu` | UV-Vis in-situ — Ocean Insight Flame | `UV_VIS/` | |
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

If you are unsure, run `POST /registry/preview` (service mode) or the Python preview helper (local mode) before submitting an ingest.

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

**Rules:**
- The filename stem must match `raw_data_filename` exactly (case-sensitive on Linux).
- If the same filename stem exists in more than one subfolder, ingest raises an error — rename one of the files to remove the ambiguity.
- If no matching file is found at ingest time, the row produces a **warning** (not an error) — the experiment can be ingested later once the file is present.

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

**Naming convention:** establish a lab-wide prefix (e.g. `CL_` for your group) and use the instrument type as part of the name. This makes the dataset list in Metabase and the Streamlit browser much easier to scan.

**One row per run:** if you repeat an experiment (`R001`, `R002`), create a separate row for each run. The `name` must be unique across all rows.

**When raw_data_filename differs from name:** if your instrument's export file has a name that doesn't match the registry entry (e.g. the instrument auto-generates filenames), set `raw_data_filename` to the file stem. Otherwise, leave it blank and keep the file named after the registry `name`.

**Don't delete old rows:** mfethuls skips re-ingesting experiments whose data has not changed. Deleting a row won't remove the dataset from the catalog unless you explicitly call `DELETE /dataset/{name}`. Leave old rows in place.

**Validate before you ingest:** use `POST /registry/preview` (service) or the Streamlit sidebar preview button (local) to catch formatting errors before starting a long ingest job.

**Custom columns are fine:** any column beyond the standard set is stored as experiment metadata and is queryable via Metabase. Use them freely for concentration, solvent, temperature, batch number, etc.
