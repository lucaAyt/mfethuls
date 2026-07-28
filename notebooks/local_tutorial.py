import marimo

__generated_with = "0.23.14"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    import os
    import pandas as pd

    from mfethuls import load_experiments, load_samples, plot_experiments
    from mfethuls.experiments import load_experiment_registry
    from mfethuls.storage import list_datasets, get_dataset

    return (
        get_dataset,
        list_datasets,
        load_experiment_registry,
        load_experiments,
        load_samples,
        plot_experiments,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Ingest data
    > Only needs to be done once, or when new experiments are added to the registry.<br>
    > Once ingested, data can be queried directly from storage without re-parsing.
    """)
    return


@app.cell
def _(load_experiment_registry):
    # Load the experiment registry — the shared spreadsheet that describes each experiment
    df_registry = load_experiment_registry()
    df_registry
    return


@app.cell
def _(load_experiments):
    # Ingest experiments and load into a ComparisonSet
    # Set refresh=True to re-parse even if already cached
    ds_experiments = load_experiments(['LB_dsc_001', 'LB_dsc_002'], use_storage=True, refresh=False)
    ds_experiments
    return


@app.cell
def _(list_datasets):
    # Check which experiments have been ingested
    list_datasets()
    return


@app.cell
def _(get_dataset):
    # Inspect metadata for a single experiment
    get_dataset('LB_dsc_001')
    return


@app.cell
def _(load_experiments):
    # Load a single experiment by name
    load_experiments(['LB_dsc_001'])
    return


@app.cell
def _(load_samples):
    # Or load all experiments for a sample ID
    cs = load_samples(['S001'])
    cs
    return (cs,)


@app.cell
def _(cs):
    # Convert to a tidy long-format DataFrame
    df = cs.to_dataframe()
    df
    return (df,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Plot data
    > Use the built-in plotting module, or any Python plotting library from the DataFrame.
    """)
    return


@app.cell
def _(load_experiments, plot_experiments):
    # Compare two DSC experiments on the same axes
    cs_dsc = load_experiments(['LB_dsc_001', 'LB_dsc_002'])
    plot_experiments(cs_dsc, x='temperature_C', y='heat_flow_mW')
    return


@app.cell
def _():
    import seaborn as sns

    return (sns,)


@app.cell
def _(df, sns):
    sns.lineplot(df, x='temperature_C', y='heat_flow_mW', hue='experiment_name', palette='flare')
    return


if __name__ == "__main__":
    app.run()
