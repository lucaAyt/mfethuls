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

    from mfethuls import load_experiments, load_samples, plot_experiments, use_test_env
    from mfethuls.experiments import load_experiment_registry

    use_test_env()  # use the test data from .env; remove this line to use your own data
    return (
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
    dsc_experiments = load_experiments(['LB_dsc_001', 'LB_dsc_002'], use_storage=True, refresh=False)
    dsc_experiments
    return (dsc_experiments,)


@app.cell
def _(dsc_experiments):
    # Convert to a tidy long-format DataFrame
    df_dsc = dsc_experiments.to_dataframe()
    df_dsc
    return (df_dsc,)


@app.cell
def _(load_samples):
    # Or load all experiments for a sample ID
    cs_s001 = load_samples(['S001'])
    cs_s001
    return (cs_s001,)


@app.cell
def _(cs_s001):
    # Convert to a tidy long-format DataFrame
    df_s001 = cs_s001.to_dataframe()
    df_s001
    return (df_s001,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Plot data
    > Use the built-in plotting module, or any Python plotting library from the DataFrame.
    """)
    return


@app.cell
def _(dsc_experiments, plot_experiments):
    # Compare two DSC experiments on the same axes
    plot_experiments(dsc_experiments)
    return


@app.cell
def _(cs_s001, plot_experiments):
    plot_experiments(cs_s001)
    return


@app.cell
def _():
    import seaborn as sns

    return (sns,)


@app.cell
def _(df_dsc, sns):
    # Plot from dsc experiments dataframe
    df_dsc_heating_0 = df_dsc[df_dsc.profile.str.contains('Heating_0')]
    sns.lineplot(df_dsc_heating_0, x='temperature_C', y='heat_flow_mW', hue='name',palette='flare')
    return


@app.cell
def _(df_s001, sns):
    # Plot from sample (s001) dataframe
    df_ftir_s001 = df_s001[df_s001.instrument_type == 'ftir']
    sns.lineplot(df_ftir_s001, x='wavenumber_cm_inv', y='transmittance_pct', hue='name', palette='flare')
    return


if __name__ == "__main__":
    app.run()
