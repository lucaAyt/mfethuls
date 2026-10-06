import marimo

__generated_with = "0.25.1"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # mfethuls — local tutorial

    **mfethuls** turns raw instrument exports (DSC, TGA, FTIR, fluorescence, …) into clean,
    comparable datasets. You describe your experiments once in a spreadsheet, the **registry**,
    and mfethuls finds the raw files, parses them, stores the results and lets you load,
    compare and plot them by name.

    This notebook walks through the full workflow on the example data that ships with the repo:

    1. **Setup**: point mfethuls at the example data
    2. **Registry**: see which experiments exist
    3. **Load experiments**: parse raw files and load them by name
    4. **Load by sample**: get everything measured on one sample
    5. **Plot**: built-in plots and your own
    6. **Time-resolved data**: follow a fluorescence measurement over time

    | Experiment | Instrument | Sample | Raw file |
    |---|---|---|---|
    | `LB_dsc_001`, `LB_dsc_002` | DSC | S001, S002 | `DSC/poly1.txt`, `DSC/poly2.txt` |
    | `LB_tga_001`, `LB_tga_002` | TGA | S001, S002 | `TGA/poly1.txt`, `TGA/poly2.txt` |
    | `LB_ftir_001`, `LB_ftir_002` | FTIR | S001, S002 | `FTIR/poly1.csv`, `FTIR/poly2.csv` |
    | `LB_fluorescence_001` | Fluorescence | S003 | `Fluorescence/poly3/` (50 spectra) |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Setup

    mfethuls reads three paths from your `.env` file:

    | Variable | What it points to |
    |---|---|
    | `PATH_TO_DATA` | the folder with one subfolder per instrument (`DSC/`, `TGA/`, …) |
    | `PATH_TO_REGISTRY` | the registry spreadsheet (CSV or Excel) |
    | `PATH_TO_LOCAL_STORAGE` | where parsed data is stored |

    `use_test_env()` switches these to the `MFETHULS_TEST_*` paths in `.env`, so the tutorial
    runs on the example data and your own data stays untouched.

    > **Using your own data?** Delete the `use_test_env()` line. The switch only lasts while
    > this notebook's kernel is running, so restart the kernel after removing it.
    """)
    return


@app.cell
def _():
    from mfethuls import load_experiments, load_samples, plot_experiments, use_test_env
    from mfethuls.experiments import load_experiment_registry

    # Point mfethuls at the example data. Remove this line to use your own data.
    use_test_env()
    return (
        load_experiment_registry,
        load_experiments,
        load_samples,
        plot_experiments,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. The experiment registry

    The registry is a spreadsheet with **one row per experiment**. It is the only thing you
    maintain by hand. The important columns:

    | Column | Meaning |
    |---|---|
    | `name` | unique experiment name; this is what you load experiments by |
    | `instrument_name` | which instrument produced the data (configured in mfethuls) |
    | `sample_id`, `run_id` | which sample was measured (`S001`) and which repeat (`R001`) |
    | `raw_data_filename` | file name of the raw export without extension (`poly1` finds `poly1.txt`) |

    mfethuls searches the instrument folder for the raw file, so you don't need to give full paths.
    """)
    return


@app.cell
def _(load_experiment_registry):
    # Read the registry from PATH_TO_REGISTRY and register every valid row.
    # Invalid rows are skipped with a warning that says what is wrong.
    df_registry = load_experiment_registry()
    df_registry
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Load experiments by name

    `load_experiments` takes a list of experiment names and returns a **ComparisonSet**: a
    group of datasets you can compare, turn into a table or plot.

    - **The first time**, mfethuls finds the raw files, parses them and stores the result.
    - **After that**, it loads the stored data, which is much faster.
    - Pass `refresh=True` to re-parse from the raw files, e.g. after re-exporting a file.
    """)
    return


@app.cell
def _(load_experiments):
    # Load the two DSC runs. Parses on the first run, then reads from storage.
    dsc_experiments = load_experiments(['LB_dsc_001', 'LB_dsc_002'], use_storage=True, refresh=False)
    dsc_experiments
    return (dsc_experiments,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### As a table

    `to_dataframe()` stacks all experiments into one **long-format** table with one row per
    data point. Useful columns:

    - `comparison_label`: the experiment name (`LB_dsc_001`), handy for colouring plots
    - `name`: the raw file the row came from (`poly1`)
    - measurement columns with standard names and units, e.g. `temperature_C`, `heat_flow_mW`
    - `profile` (DSC only): the segment of the temperature program, e.g. `Heating_0` for the
      first heating ramp or `Cooling_0` for the first cooling ramp
    """)
    return


@app.cell
def _(dsc_experiments):
    # One long table with both DSC runs
    df_dsc = dsc_experiments.to_dataframe()
    df_dsc
    return (df_dsc,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Load everything for a sample

    Often you want every measurement made on one sample. `load_samples` looks up all registry
    rows with that `sample_id`. For `S001` that is one DSC, one TGA and one FTIR experiment.
    """)
    return


@app.cell
def _(load_samples):
    # All experiments measured on sample S001 (DSC, TGA and FTIR)
    cs_s001 = load_samples(['S001'])
    cs_s001
    return (cs_s001,)


@app.cell
def _(cs_s001):
    # Rows from different instruments share one table; `instrument_type` tells them apart.
    # Columns that don't apply to an instrument are empty (NaN) in its rows.
    df_s001 = cs_s001.to_dataframe()
    df_s001
    return (df_s001,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Plot

    ### Built-in plots

    `plot_experiments` picks a suitable plot for each instrument, e.g. heat flow against
    temperature for DSC or a spectrum for FTIR. Experiments are labelled by name, so you can
    compare them straight away.
    """)
    return


@app.cell
def _(dsc_experiments, plot_experiments):
    # The two DSC runs on the same axes
    plot_experiments(dsc_experiments)
    return


@app.cell
def _(cs_s001, plot_experiments):
    # Everything measured on sample S001: one panel per instrument (DSC, TGA, FTIR)
    plot_experiments(cs_s001)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Your own plots

    The table from `to_dataframe()` works with any plotting library. Here we use
    [seaborn](https://seaborn.pydata.org/): filter the rows you want, then choose the columns
    for the axes.
    """)
    return


@app.cell
def _():
    import seaborn as sns

    return (sns,)


@app.cell
def _(df_dsc, sns):
    # DSC: keep only the first heating ramp and compare the two runs
    df_dsc_heating_0 = df_dsc[df_dsc.profile.str.contains('Heating_0')]
    sns.lineplot(df_dsc_heating_0, x='temperature_C', y='heat_flow_mW', hue='name', palette='flare')
    return


@app.cell
def _(df_s001, sns):
    # FTIR: pick the FTIR rows out of the mixed sample table
    df_ftir_s001 = df_s001[df_s001.instrument_type == 'ftir']
    sns.lineplot(df_ftir_s001, x='wavenumber_cm_inv', y='transmittance_pct', hue='name', palette='flare')
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Time-resolved data: fluorescence

    Some instruments record a series of spectra over time. The fluorescence example
    `LB_fluorescence_001` is a folder of 50 emission spectra taken about one second apart.
    Because the experiment is a **folder**, its `raw_data_filename` is the folder name
    (`poly3`) and mfethuls loads every file inside it as one experiment.

    Each spectrum keeps the time it was recorded in the `timestamp` column, and the signal
    is stored as `emission_counts` (raw detector counts).
    """)
    return


@app.cell
def _(load_experiments):
    # One experiment, 50 spectra
    fl_experiments = load_experiments(['LB_fluorescence_001'])
    fl_experiments
    return (fl_experiments,)


@app.cell
def _(fl_experiments):
    df_fl = fl_experiments.to_dataframe()

    # Seconds since the first spectrum. A number gives a smooth colour scale and a short legend,
    # where the raw timestamps would give 50 separate legend entries.
    df_fl['time_s'] = (df_fl.timestamp - df_fl.timestamp.min()).dt.total_seconds()
    df_fl
    return (df_fl,)


@app.cell
def _(df_fl, sns):
    # Each spectrum coloured by when it was recorded: dark = early, yellow = late
    sns.lineplot(df_fl.loc[df_fl['wavelength_nm'].between(500, 800), :], x='wavelength_nm', y='emission_counts', hue='time_s', palette='viridis')
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Next steps

    - **Use your own data:** set `PATH_TO_DATA`, `PATH_TO_REGISTRY` and `PATH_TO_LOCAL_STORAGE`
      in `.env`, delete the `use_test_env()` line and restart the kernel.
    - **Add experiments:** add a row to your registry. `experiments_template.csv` in the repo
      root has an example row for every supported instrument.
    - **Learn more** in the `docs/` folder:
        - `guides/workflow.md`: the day-to-day workflow
        - `guides/data_analysis.md`: queries and analysis in notebooks
        - `reference/registry.md`: every registry column and how raw files are found
    """)
    return


if __name__ == "__main__":
    app.run()
