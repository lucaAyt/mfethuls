# Running mfethuls Locally

Guide for scientists who want to run the mfethuls app on their own machine without managing Python environments.

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
curl -LsSf https://astral.sh/uv/install.sh | sh
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
data folder/           ← the folder you choose in the app
  DSC/                 ← Mettler Toledo, PerkinElmer, other
  TGA/                 ← TGA files
  FTIR/                ← Bruker FTIR files
  NMR/                 ← Bruker NMR dataset folders, as TopSpin writes them (EXP014/1/pdata/1/...)
  SEC/                 ← Agilent SEC files
  Rheology/            ← Anton Paar rheometer files
  DMA/                 ← TA Q800 DMA files
  UV_Vis/              ← Shimadzu / Ocean Optics UV-Vis files
  Fluorescence/        ← Ocean Optics Flame fluorescence in-situ files
  SAXS/                ← Anton Paar SAXS files
  MS/                  ← Bruker MS files
```

Files can be placed **at any depth** inside the instrument folder — subfolders are fine. mfethuls walks the full folder tree to find your files.

> **No data yet?** Start the app (`mfethuls-app`) and press **Try the example** on the welcome page: example DSC, TGA, FTIR and fluorescence in-situ files are copied to `~/mfethuls-example`, and the getting-started checklist walks you through registering, ingesting and plotting them. From Python: `from mfethuls.examples import create_workspace; create_workspace()`. Your own folders are not changed; **Back to my data** switches back.

---

## Step 3 — First launch

**Windows:** double-click `launch.bat` in the project folder.

**macOS / Linux:** open a terminal in the project folder and run:
```bash
bash launch.sh
```

The app opens in your browser at `http://localhost:8501`. On the welcome page, press **Get started** and fill in:

| Field | Example | What it is |
|--------|---------|------------|
| Data folder | `C:\Lab\RawData` | Root folder with instrument sub-folders (`DSC/`, `TGA/`, etc.). Paste it from File Explorer: click the address bar and copy, or right-click the folder → **Copy as path**. |
| Registry *(optional, under **Use a different registry**)* | `C:\Lab\shared\experiments.xlsx` | Your experiment registry. Left empty, it is `registry.xlsx` in the data folder, made for you. |
| Storage folder | *(optional)* | Where processed data is written; by default a `_storage` folder inside the data folder |

The app checks them as you type (which instrument folders it recognises, whether a registry can be read) and shows how to organise the data folder. Press **Save**. The folders are saved in `~/.mfethuls/settings.json`, so notebooks use the same ones.

The repo includes `experiments_template.csv` — open it in Excel to see all supported instruments and columns. Replace the placeholder rows with your own experiments, or use it as a starting point for a new registry file.

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

**If you downloaded a zip:** download the new zip, unzip to a new folder, and launch it. Your folders are saved outside the project (`~/.mfethuls/settings.json`), so they carry over.

---

## Reconfiguring paths

In the app: **⚙ Settings** (top of the sidebar) → **Data folder and registry**, change the paths and press **Save**.

Settings saved in the app take precedence over `PATH_TO_DATA`, `PATH_TO_REGISTRY` and `PATH_TO_LOCAL_STORAGE` in `.env` or the environment, which are only used for what the app has not saved.

### A data folder shared through OneDrive (or another sync service)

Several people can work from one data folder synced to each computer. Then:

- **Keep the storage folder local on each computer.** Set the *Storage folder* (in **⚙ Settings → Data folder and registry**, or `PATH_TO_LOCAL_STORAGE`) to a folder that is not synced, e.g. `C:\Users\<you>\mfethuls-storage`. Without it, the catalog is stored in `_storage` inside the data folder, and a database file changed on two computers cannot be merged by the sync service. Each computer then keeps its own stored copy; ingesting rebuilds it from the shared raw data.
- **The manifest is shared**, and that is safe: an experiment gets the same internal ID on every computer. If two computers ingest at the same time and OneDrive keeps both versions (`.mfethuls_manifest-<COMPUTER>.json`), mfethuls merges them the next time it writes the manifest and renames the copy to `...json.merged`.
- **Lab instruments** (`.mfethuls/instruments/`) are shared with everyone using the folder, as intended.

---

## Troubleshooting

**"uv is not installed or not on PATH"**
Close and reopen your terminal after installing `uv`. If that doesn't help, re-run the install command.

**App opens but no datasets appear**
The Datasets list fills after an ingest. Open **Ingest** in the sidebar, select the experiments and press **Ingest**; the getting-started checklist shows what is left.

**"Use it from Python" says marimo is not installed**
The launcher installs it (`uv run --extra viz --extra notebook`). If you installed mfethuls yourself, add the notebook extra: `pip install "mfethuls[viz,notebook]"`.

**Windows: script blocked by security policy**
Right-click `launch.bat`, choose **Properties**, and click **Unblock** at the bottom of the General tab.
