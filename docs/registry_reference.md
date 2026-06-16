# Experiment Registry Reference

The registry is a CSV or XLSX spreadsheet that serves as the primary interface between experimentalists and the mfethuls pipeline. Every experiment you want to ingest must have a row here. The file lives on a shared location (OneDrive, network share, S3) so the whole team works from the same source of truth.

---

## Column reference

| Column | Required | Format | Description |
|--------|----------|--------|-------------|
| `name` | **yes** | free text, unique | Human-friendly label used as the lookup key throughout the system (e.g. `CL_dsc_001`). Should be short and stable — changing it later creates a new dataset entry. |
| `experiment_id` | **yes** | `EXP` + 3–6 digits | Strict identifier that maps to a data folder under `PATH_TO_DATA` (e.g. `EXP001`). |
| `instrument_name` | **yes** | see table below | Instrument configuration name from `instrument_params.json`. Must match exactly. |
| `sample_id` | no | `S` + 3–6 digits | Identifies the sample (e.g. `S001`). Used in the Parquet filename. |
| `run_id` | no | `R` + 3–6 digits | Run number within a sample (e.g. `R001`). Defaults to `R001` when absent. |
| `measurement_profile` | conditional | see profiles table | Required for **rheometer** and **DMA** experiments (see below). Ignored for other instruments. |
| `description` | no | free text | Free-text description. If `measurement_profile` is missing, mfethuls will attempt to infer a profile from the description (e.g. "frequency sweep" → `oscillatory_frequency_sweep`). |
| any other column | no | any | Stored as metadata alongside the experiment. Useful for batch, operator, sample concentration, etc. |

---

## Identifier formats

| Identifier | Pattern | Examples |
|------------|---------|---------|
| `experiment_id` | `EXP` + 3–6 digits | `EXP001`, `EXP042`, `EXP100010` |
| `sample_id` | `S` + 3–6 digits | `S001`, `S12`, `S1000` |
| `run_id` | `R` + 3–6 digits | `R001`, `R002` |

These are validated on load. Rows with malformed identifiers are skipped with a warning.

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

The worker resolves raw data using:

```
PATH_TO_DATA / <instrument folder> / <experiment_id> / <files>
```

For example, an experiment with `instrument_name = dsc_mettler_toledo` and `experiment_id = EXP042` expects files at:

```
PATH_TO_DATA/
  DSC/
    EXP042/
      EXP042_S001_R001.txt   ← or whatever your instrument exports
      EXP042_S001_R002.txt
```

If the folder does not exist, the row produces a **warning** (not an error) and the ingest still proceeds for other experiments.

---

## Example registry

This is a realistic multi-instrument registry spanning one research batch. Copy this as a starting point for your own registry.

```
name,experiment_id,instrument_name,sample_id,run_id,measurement_profile,description,batch,operator
CL_dsc_001,EXP001,dsc_mettler_toledo,S001,R001,,,PB-2024-01,Maria
CL_dsc_002,EXP002,dsc_mettler_toledo,S002,R001,,,PB-2024-01,Maria
CL_dsc_002_repeat,EXP002,dsc_mettler_toledo,S002,R002,,,PB-2024-01,Maria
CL_tga_001,EXP003,tga,S001,R001,,,PB-2024-01,Carlos
CL_rheometer_freq,EXP004,rheometer,S003,R001,oscillatory_frequency_sweep,,PB-2024-01,Priya
CL_rheometer_flow,EXP005,rheometer,S003,R001,flow_curve,viscometry at 25C,PB-2024-01,Priya
CL_dma_temp,EXP006,dma,S004,R001,oscillatory_temperature_sweep,Tg measurement,PB-2024-01,Carlos
CL_ftir_001,EXP007,ftir,S001,R001,,,PB-2024-01,Maria
CL_sec_001,EXP008,sec,S002,R001,,,PB-2024-01,Priya
CL_nmr_001,EXP009,nmr,S001,R001,,,PB-2024-01,Maria
CL_uv_kinetics,EXP010,uv_insitu,S005,R001,,UV kinetics monitoring,PB-2024-01,Carlos
CL_saxs_001,EXP011,saxs,S003,R001,,,PB-2024-01,Priya
CL_pending,,dsc,,,,Planned — not yet run,,
```

**Notes on the example above:**

- `CL_dsc_002` and `CL_dsc_002_repeat` share the same `experiment_id` (`EXP002`) and `sample_id` (`S002`) but have different `run_id` values (`R001`, `R002`). This is how you log repeat measurements on the same sample.
- `CL_pending` has a blank `experiment_id` and `instrument_name` — this row will produce a validation error. Keep it in the registry as a placeholder and fill it in before ingesting.
- `batch` and `operator` are custom columns; they will be stored as metadata alongside each experiment.
- The rheometer row for `CL_rheometer_flow` uses a free-text `description` instead of `measurement_profile`. mfethuls infers `flow_curve` from the word "viscometry". Explicit `measurement_profile` is preferred where possible.

---

## Tips for experimentalists

**Naming convention:** establish a lab-wide prefix (e.g. `CL_` for your group) and use the instrument type as part of the name. This makes the dataset list in Metabase much easier to scan.

**One row per run:** if you repeat an experiment (`R001`, `R002`), create a separate row for each run. The `name` must be unique; the `experiment_id` + `sample_id` can be the same.

**Don't delete old rows:** mfethuls skips re-ingesting experiments whose data has not changed. Deleting a row won't remove the dataset from the catalog unless you explicitly call `DELETE /dataset/{name}`. Leave old rows in place.

**Validate before you ingest:** use `POST /registry/preview` (service) or the Streamlit sidebar preview button (local) to catch formatting errors before starting a long ingest job.

**Custom columns are fine:** any column beyond the standard set is stored as experiment metadata and is queryable via Metabase. Use them freely for concentration, solvent, temperature, batch number, etc.
