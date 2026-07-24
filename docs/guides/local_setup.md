# Running mfethuls Locally

Guide for scientists who want to run the Streamlit explorer on their own machine without managing Python environments.

---

## Prerequisites

- Windows, macOS, or Linux
- `uv` (a Python package manager — installed once, in 30 seconds)
- Access to the mfethuls repository (zip or git)

You do **not** need Python pre-installed. `uv` handles that.

---

## Step 1 — Install uv (one-time)

`uv` is a single binary that installs Python and manages dependencies. You only ever install it once.

**Windows** (run in PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux** (run in a terminal):
```bash
curl -LsSf https://astral.sh/uv | sh
```

Close and reopen your terminal, then verify:
```shell
uv --version
```

---

## Step 2 — Get the repository

### Option A — Download a zip (easiest, no git required)

1. Go to the GitHub repository page
2. Click **Code → Download ZIP**
3. Unzip to a folder on your machine (e.g. `C:\Lab\mfethuls`)

### Option B — Clone with git (easier to update later)

```shell
git clone https://github.com/lucaAyt/mfethuls.git
cd mfethuls
```

To update later, run `git pull` from the project folder.

---

## Data folder structure

Before you launch for the first time, organise your raw instrument data like this:

```
PATH_TO_DATA/          ← the path you give the setup wizard
  DSC/                 ← Mettler Toledo, PerkinElmer, other
  TGA/                 ← TGA files
  FTIR/                ← Bruker FTIR files
  NMR/                 ← Bruker NMR folders
  SEC/                 ← Agilent SEC files
  Rheology/            ← Anton Paar rheometer files
  DMA/                 ← TA Q800 DMA files
  UV_VIS/              ← Shimadzu / Ocean Optics
  SAXS/                ← Anton Paar SAXS files
  MS/                  ← Bruker MS files
```

Files can be placed **at any depth** inside the instrument folder — subfolders are fine. mfethuls walks the full folder tree to find your files.

---

## Step 3 — First launch

**Windows:** double-click `launch.bat` in the project folder.

**macOS / Linux:** open a terminal in the project folder and run:
```bash
bash launch.sh
```

On first launch, a setup wizard collects three paths:

| Prompt | Example | What it is |
|--------|---------|------------|
| Path to raw data folder | `C:\Lab\RawData` | Root folder with instrument sub-folders (`DSC/`, `TGA/`, etc.) |
| Path to registry CSV | `C:\Lab\registry.csv` | Your experiment registry spreadsheet |
| Path for processed storage | *(leave blank for default)* | Where Parquet files will be written |

These are saved to `.env` in the project folder. You will not be prompted again.

The repo includes `experiments_template.csv` — open it in Excel to see all supported instruments and columns. Replace the placeholder rows with your own experiments, or use it as a starting point for a new registry file.

After the wizard, Streamlit starts automatically and opens at `http://localhost:8501`.

---

## Step 4 — Ongoing use

Just double-click `launch.bat` (Windows) or run `bash launch.sh` (macOS/Linux). The app starts in a few seconds.

---

## Updating

**If you used git:**
```shell
git pull
```
Then launch as normal. `uv` detects changed dependencies and updates them automatically.

**If you downloaded a zip:** download the new zip, unzip to a new folder, then copy your `.env` file from the old folder into the new one (this preserves your path settings).

---

## Reconfiguring paths

Delete `.env` from the project root and launch again — the setup wizard will run.

Or edit `.env` directly in a text editor:
```
PATH_TO_DATA=C:\Lab\RawData
PATH_TO_REGISTRY=C:\Lab\registry.csv
PATH_TO_LOCAL_STORAGE=C:\Lab\mfethuls_storage
```

---

## Troubleshooting

**"uv is not installed or not on PATH"**
Close and reopen your terminal after installing `uv`. If that doesn't help, re-run the install command.

**Setup wizard appears every time**
The wizard runs when `.env` is missing. Make sure `.env` exists in the project root (the same folder as `launch.bat`), not inside a sub-folder.

**App opens but no datasets appear**
The Datasets tab is populated after an ingest. Use the sidebar in Streamlit to load your registry CSV and run an ingest first.

**`streamlit` command not found**
The launcher uses `uv run --extra viz`, which installs Streamlit automatically. If running Streamlit manually (outside the launcher), install it first: `uv pip install streamlit`.

**Windows: script blocked by security policy**
Right-click `launch.bat`, choose **Properties**, and click **Unblock** at the bottom of the General tab.
