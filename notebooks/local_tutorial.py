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
    > Only needs to be done once off or if there are updates.<br>
    > Once the data is in storage (ingestion complete) it can be queried by spawning DuckDBQueryBackend().
    """)
    return


@app.cell
def _(load_experiment_registry):
    # Load the experimental registry, the interface for the experimentalist
    df_registry = load_experiment_registry()
    df_registry
    return


@app.cell
def _(load_experiments):
    # If you would like to ingest data that has been added to registry or refresh
    ingest_data = True
    if ingest_data:
        # Ingest the data and load experiment into dataset
        ds_experiments = load_experiments(['EXP002'], use_storage=True, refresh=False)
        ds_experiments
    return


@app.cell
def _(list_datasets):
    # Check datasets to see if your experiment has been ingested 
    list_datasets()
    return


@app.cell
def _(get_dataset):
    # You can get the metadata for an experiment
    get_dataset('QEP')
    return


@app.cell
def _(load_experiments):
    # If your experiment has been ingested you can load it with the experiment name.
    # Load a comparison set including dataset and metadata
    load_experiments(['QEP'])
    return


@app.cell
def _(load_samples):
    # Or load all experiments associated with a particular sample ID
    cs = load_samples(['S001'])
    cs
    return (cs,)


@app.cell
def _(cs):
    # Convert dataset to a dataframe
    df = cs.to_dataframe()
    df
    return (df,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Plot data
    > Use the built in plotting module<br>
    > Use you're favourite python package to plot from dataframe
    """)
    return


@app.cell
def _(cs, plot_experiments):
    plot_experiments(cs)
    return


@app.cell
def _():
    import seaborn as sns

    return (sns,)


@app.cell
def _(df, sns):
    mask = (df.name=='EXP002') & (df.profile.isin(['Heating_1', 'Cooling_0']))
    sns.lineplot(df[mask], x='temperature_C', y='heat_flow_mW', hue='profile', palette='flare')
    return


if __name__ == "__main__":
    app.run()
