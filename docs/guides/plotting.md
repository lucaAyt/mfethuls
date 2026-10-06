# Plotting

mfethuls draws every built-in plot with two interchangeable backends:

| Backend | Returns | Use for |
|---|---|---|
| `"matplotlib"` (default) | `(fig, ax)`, or `(fig, axes)` for one panel per experiment | Publication figures, vector SVG/PDF, the CLI |
| `"plotly"` | `plotly.graph_objects.Figure` | Interactive exploration in notebooks and the Streamlit app |

Both draw the same plot: same columns, labels, colours, axis directions and limits. Plotly uses WebGL, so hundreds of thousands of points stay responsive without downsampling.

Install with the `viz` or `notebook` extra (`pip install "mfethuls[viz,notebook]"`).

---

## Quick start

```python
import mfethuls

cs = mfethuls.load_experiments(["LB_dsc_001", "LB_dsc_002"])

fig, ax = mfethuls.plot_experiments(cs)                    # Matplotlib
fig = mfethuls.plot_experiments(cs, backend="plotly")      # interactive

mfethuls.set_plot_backend("plotly")    # make Plotly the default, e.g. in a notebook
```

`plot_experiments` picks the plot for each instrument from its metadata and columns. Experiments that share an x-axis are overlaid; otherwise each gets its own panel.

### Comparison modes

```python
mfethuls.plot_experiments(cs, mode="auto")      # overlay if the x-axes match, else one panel each
mfethuls.plot_experiments(cs, mode="overlay")   # same axes (x-axes must match)
mfethuls.plot_experiments(cs, mode="stacked", stacked_offset=0.5)   # overlay, shifted vertically
mfethuls.plot_experiments(cs, mode="facet")     # one panel per experiment
```

Other options: `kind=` forces a plot family (`"dsc"`, `"ftir"`, …), `signal=` picks the y column where a family offers a choice (e.g. `"transmittance_pct"` for FTIR), `group_by=` splits one dataset into several lines, and `title=` sets the title.

### Single datasets

```python
from mfethuls.plotting import plot_dataset, plot_dsc, plot_ftir

fig, ax = plot_dataset(cs.datasets[0])     # family chosen automatically
fig, ax = plot_ftir(dataset, signal="transmittance_pct")
```

---

## Built-in plots

| Family | x-axis | y-axis | Notes |
|---|---|---|---|
| DSC | Temperature | Heat flow | One colour per segment (heating red, cooling blue, isothermal grey; later cycles darker). In overlays, line style marks the experiment. Cycle start/end points are not drawn. |
| TGA | Temperature | Mass (%) or dm/dt | |
| FTIR | Wavenumber, high to low | Absorbance or transmittance | |
| UV/Vis | Wavelength | Absorbance or transmittance | |
| Fluorescence | Wavelength | Emission intensity | Spectra series are coloured by time (see below) |
| DMA | Depends on the measurement profile | Storage and loss modulus E′, E″ | Log scales, except a linear time or temperature axis |
| Rheology | Depends on the measurement profile | G′, G″, or stress and viscosity | Log scales, except a linear time axis |
| SEC | Retention time | Detector response | One line per detector |
| MS | m/z | Intensity | |
| NMR | Chemical shift, high to low | Intensity | |
| SAXS | q | Intensity | Log–log |

### Several lines from one dataset

When a dataset holds several curves on the same x values (e.g. a series of spectra), mfethuls finds the column that separates them and draws one line per value, or you can name it with `group_by=`.

- Up to 10 lines: a normal legend.
- More than 10 lines of a **numeric** column (e.g. `time_s`): a continuous colour bar instead of a legend. Overlays of several such experiments share one colour bar and use line style to mark the experiment.

### Time-resolved data (`time_s`)

Instruments that only record a wall-clock `timestamp` per spectrum (e.g. Ocean Optics Flame series) get a `time_s` column automatically: seconds since the first timestamp of the dataset. It is added during ingest and when loading datasets stored earlier, so a 50-spectrum series plots with one *Time (s)* colour bar instead of 50 timestamps. An instrument's own `time_s` (DSC, TGA) is never replaced.

---

## Labels and units

Axis titles and legend entries use the quantity and unit of each canonical column, e.g. *Temperature (°C)*, *Wavenumber (cm⁻¹)* or *Storage modulus E′*. Several columns sharing a quantity and unit share one axis title (*Modulus (MPa)*).

Labels live in `src/mfethuls/plotting/labels.py`, written in Matplotlib mathtext for superscripts and symbols:

```python
"wavenumber_cm_inv": ColumnLabel("Wavenumber", r"cm$^{-1}$"),
"storage_modulus_mpa": ColumnLabel("Storage modulus", "MPa", symbol=r"$E'$", group="Modulus"),
```

The Plotly backend converts mathtext into the HTML Plotly renders (`<sup>`, Greek letters, primes). **When you add a canonical column to a schema, add its label here as well.** `tests/test_plotting_labels.py` fails for any schema column without one. Columns that are not in the table keep their raw name.

---

## Publication figures (Matplotlib)

Matplotlib figures use a fixed publication style, whatever the global Matplotlib or notebook theme:

- seaborn's `paper` context at `font_scale=1.75`, lines 1.75 pt, written out as `PUBLICATION_RC` in `plotting/style.py` (seaborn itself is not needed)
- black text and axes on a white background, so figures stay readable when saved, even from marimo's dark theme
- no top or right spine; one minor tick between major ticks on linear x-axes
- long legends, and legends in multi-panel figures, sit outside the axes. The figure widens by their width so the plot area keeps its size.

Adjust and save the result like any Matplotlib figure:

```python
fig, ax = mfethuls.plot_experiments(cs, backend="matplotlib")
ax.set_xlim(50, 150)
fig.savefig("dsc_comparison.svg", bbox_inches="tight")
```

Pass `ax=` to draw into your own axes (overlay and single plots only). The figure then keeps your style and size.

---

## Interactive figures (Plotly)

- WebGL lines (`Scattergl`): every data point is drawn.
- Box-drag to zoom, double-click to reset, click a legend entry to hide a line (in DSC overlays, the experiment entries hide all of that experiment's segments).
- The camera button downloads an SVG, but Plotly embeds WebGL lines as a picture in it. For a true vector SVG, use the Matplotlib backend, or the SVG button in the Streamlit app, which uses Matplotlib.

---

## Streamlit dashboard

The **Plot** section of `apps/Home.py` offers two modes:

- **Line or scatter plots of any columns:** choose the x and y columns, colour column, log axes and axis direction.
- **Built-in instrument plot** (toggle): the plots described above, for the selected experiments.

The toolbar above the chart:

| Control | What it does |
|---|---|
| **Axis limits** | Min/max per axis. Empty fields stay automatic, and each shows the automatic value as a hint. Limits apply to the chart and the SVG. The button is highlighted while limits are set; **Reset to automatic** clears them. Not available for histograms, box plots or multi-panel figures. |
| **SVG** | Vector figure drawn with Matplotlib in the publication style, using the axis limits. Generated when clicked. |
| **HTML** | Standalone interactive Plotly page. Generated when clicked. |

**Colours:** categorical colour columns use a discrete palette. A numeric colour column with more than 10 values (e.g. `time_s` on a spectra series) switches to a **Colour scale** picker (viridis, plasma, cividis, coolwarm, …) with a **Reverse** toggle. A column with a different value on almost every row (more than 300 values, e.g. `time_s` in DSC data) is drawn without colour groups.

**Data size:** the **Query** sidebar loads all rows by default, so plots and exports use every data point. Turn off **Load all rows** to load a fixed number of rows per experiment instead. With 500,000 rows, the app takes about half a second per interaction; loaded data is cached for 10 minutes, and **Refresh** reloads it. The **Preview** table shows the first 1,000 rows.

---

## Building plots from code

Every plot is first described as a backend-neutral `PlotSpec` (`plotting/spec.py`), then drawn by `render_mpl` or `render_plotly`. To change a plot before drawing it, build the spec, edit it, then render:

```python
from mfethuls.plotting import build_experiments_spec
from mfethuls.plotting.backend import render

spec = build_experiments_spec(cs)
spec.panel.xlim = (50.0, 150.0)          # data units, also on log axes
spec.panel.title = "Polymer 1 vs 2"

fig, ax = render(spec, backend="matplotlib")
plotly_fig = render(spec, backend="plotly")
```

A new plot family needs a `build_<family>_spec` function in `plotting/`, registered in `build_dataset_spec` (`plotting/core.py`). Both backends then draw it.
