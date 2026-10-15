# Quickstart

mfethuls runs on your own computer: a Python framework that reads, cleans and organises your instrument data, and an app (`mfethuls-app`) that is the quickest way to use it.

---

## 1. Install

**Non-technical users (Windows, macOS, Linux):** follow [local setup](local_setup.md). You install [`uv`](https://docs.astral.sh/uv/), download the repository and double-click `launch.bat` (or run `bash launch.sh`); everything else is installed for you.

**Python users:**

```shell
pip install "mfethuls[viz,notebook] @ git+https://github.com/lucaAyt/mfethuls.git"
```

(`uv pip install …` works the same way. A release on PyPI is planned, which will make this `pip install "mfethuls[viz,notebook]"`.)

---

## 2. Start the app

```shell
mfethuls-app
```

It opens at `http://localhost:8501` with a welcome page:

- **Get started** asks for your **data folder** (one subfolder per instrument: `DSC/`, `TGA/`, …) and your **registry** (a CSV or Excel sheet with one row per experiment; the app can create an empty one, and the setup form offers an example to download). Both are checked as you type, and the page shows how to organise the data folder. They are saved in `~/.mfethuls/settings.json`, so notebooks use the same folders; change them later under **⚙ Settings**.
- **Try the example** switches the app to a copy of the example DSC, TGA, FTIR and fluorescence data (in `~/mfethuls-example`). Your own folders are not touched; **Back to my data** switches back.
- **Use it from Python** opens the tutorial notebook (see below).

---

## 3. Work through the checklist

Once set up, a getting-started checklist shows what to do next; a compact version stays at the top of the sidebar (**Guide** shows the full list):

1. **Register new data**: **Ingest** → **Review & register** proposes registry rows for raw files that are not in the registry yet. Rows are checked as you edit them, including a test read of the files with the chosen instrument.
2. **Ingest**: tick experiments (or **Select all**) and press **Ingest**.
3. **Select** experiments under **Datasets**, then **plot** them: the built-in plot per instrument, or a line/scatter plot with **Colour by** and **Style by**; set **Axis limits**; export a vector **SVG** or interactive **HTML**.
4. **Keep it tidy**: after renaming or removing registry rows, **⚙ Settings** → **Clean up**.

The 🏠 button at the top of the sidebar goes back to the welcome page.

---

## 4. Use it from Python

The tutorial walks through loading, comparing and plotting on its own copy of the example data:

```shell
mfethuls-tutorial
```

Or directly, with the folders chosen in the app:

```python
import mfethuls

cs = mfethuls.load_experiments(["LB_dsc_001", "LB_dsc_002"])
df = cs.to_dataframe()            # tidy long-format DataFrame
fig, ax = mfethuls.plot_experiments(cs)
```

---

## Next steps

| If you want to… | Read |
|---|---|
| See the full workflow with a concrete example | [workflow.md](workflow.md) |
| Understand the registry format (columns, instruments, profiles) | [registry reference](../reference/registry.md) |
| Query data in notebooks (Python API, DuckDB SQL, model building) | [data_analysis.md](data_analysis.md) |
| Plot styles, exports and the plot API | [plotting.md](plotting.md) |
