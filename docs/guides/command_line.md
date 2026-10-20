# The `mfethuls` command

Everything the app does, from a terminal or a script: set the folders, check the registry,
ingest, list what is stored, clean up, export and plot. It is installed with mfethuls
(`pip install mfethuls`; `plot` needs the `viz` extra).

```shell
mfethuls --help              # the commands
mfethuls ingest --help       # the options of one command
mfethuls --version
```

## Folders

The command uses the same folders as the app: those saved under **Settings** (in
`~/.mfethuls/settings.json`), else `PATH_TO_DATA` / `PATH_TO_REGISTRY` /
`PATH_TO_LOCAL_STORAGE` from the environment or `.env`. Without a registry, it is
`registry.xlsx` in the data folder.

```shell
mfethuls settings                                   # show the folders in use
mfethuls settings --data-folder D:\lab-data --registry D:\lab-data\experiments.xlsx   # save them (the app uses them too)
```

For one run only, put the folders before the command; nothing is saved:

```shell
mfethuls --data-folder ./data --registry ./experiments.csv ingest --all
```

## A typical session

```shell
mfethuls validate --check-files      # every registry row valid, and its raw data found?
mfethuls discover                    # raw data that no registry row describes yet
mfethuls ingest --all                # read and store everything (stored experiments are only registered)
mfethuls list                        # what is in the catalog
mfethuls plot LB_dsc_001 LB_dsc_002 -o dsc.svg
mfethuls export LB_dsc_001 -o LB_dsc_001.csv
mfethuls cleanup                     # after editing the registry: what is out of date
mfethuls cleanup --apply             # bring it in line
```

## Commands

| Command | What it does |
|---|---|
| `settings` | Show the folders in use; `--data-folder`, `--registry`, `--storage` save them. |
| `validate` | Check every registry row; `--check-files` also checks that each row's raw data is there. Exit code 1 if rows are skipped. |
| `ingest NAME ...` | Read and store these experiments. `--all` for every valid row, `--instrument NAME` for one instrument's rows, `--refresh` to read the raw data again even if it was stored. |
| `list` | The ingested datasets: experiment, instrument, sample, run, rows and the catalog table name (for SQL). `--instrument` filters. |
| `discover` | Raw data in the data folder without a registry row. Add rows for them to the registry (the app's **Register new data** drafts them). |
| `cleanup` | Compare what was ingested with the registry and show what would change; `--apply` does it, `--force` allows a large forget. See [Clean up](../reference/registry.md). |
| `export NAME -o FILE` | One experiment's data as `.csv` or `.parquet`. |
| `plot NAME ... -o FILE` | A figure of the experiments together: `.png`, `.svg`, `.pdf` (publication style) or `.html` (interactive). `--mode auto\|overlay\|stacked\|facet`, `--offset` for stacked. |
| `instruments` | The instruments mfethuls knows (built-in and the lab's definitions), and any definition it could not use, with the reason. |
| `app` | Start the app (same as `mfethuls-app`). |
| `tutorial` | Open the Python tutorial (same as `mfethuls-tutorial`). |

## In scripts

Exit codes: `0` done, `1` something failed (each failure is printed), `2` not run (a
missing folder, an unknown experiment, or a clean up blocked for safety). `-v` shows
informational messages.

```shell
mfethuls ingest --all || echo "some experiments failed"
```
