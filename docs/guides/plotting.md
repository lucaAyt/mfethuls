# Plotting

mfethuls draws every built-in plot with two interchangeable backends:

| Backend | Returns | Use for |
|---|---|---|
| `"matplotlib"` (default) | `(fig, ax)`, or `(fig, axes)` for one panel per experiment | Publication figures, vector SVG/PDF, the CLI |
| `"plotly"` | `plotly.graph_objects.Figure` | Interactive exploration in notebooks and the Streamlit app |

Both draw the same plot: same columns, labels, colours, axis directions and limits. Plotly uses WebGL, so hundreds of thousands of points stay responsive. In the app, a figure of more than 300,000 points is thinned for the screen (see [Large datasets](#large-datasets-in-the-app)); downloads and notebooks always get every point.

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
mfethuls.plot_experiments(cs, mode="stacked")   # overlay, each experiment shifted up (offset)
mfethuls.plot_experiments(cs, mode="facet")     # one panel per experiment
```

- **Offset** (`mode="stacked"`): each experiment is shifted up from the one before, so curves that lie on top of each other can be told apart. By default the shift is 1.1 times the tallest experiment's y range (`stacked_offset="auto"`); `spacing=2.0` doubles it, and `stacked_offset=0.5` sets it in y units instead. On a log y-axis the shift is in decades. Shifted values are not the data's, so the y-axis is labelled *(offset)* and shows no numbers.
- **Panels** (`mode="facet"`): one panel per experiment, named after it, one under the other. When the experiments have the same x quantity (all DSC against temperature, say), the panels share one x-axis: its values and name show under the last panel, and in Plotly zooming one panel zooms them all. Experiments with different x quantities get their own x-axes.
- **Normalise** (`normalise="max"`, `"minmax"` or `"area"`): scales each experiment's curves so they can be compared by shape: the largest absolute value becomes 1, the values run from 0 to 1, or the area under the curves becomes 1. Only the drawing changes, never the data. An experiment is normalised as a whole, so a DSC run's heating and cooling segments keep their sizes relative to each other; with `mode="stacked"` the curves are normalised first, then offset. The y-axis loses its unit (*Heat flow (normalised)*). An experiment that cannot be normalised (a flat curve, no area) is drawn as it is and listed in the spec's `notes`. `normalise_x=(low, high)` (either may be `None`) takes the scale from that x range only, e.g. one peak, and applies it to the whole curve. Area is the net area: parts below zero count against parts above.

Other options: `kind=` forces a plot family (`"dsc"`, `"ftir"`, …), `signal=` picks the y column where a family offers a choice (e.g. `"transmittance_pct"` for FTIR), `group_by=` splits one dataset into several lines, and `title=` sets the title of the Plotly figure (Matplotlib figures have none; see [Publication figures](#publication-figures-matplotlib)).

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
| DMA | What the run swept, read from the data: temperature, frequency, strain, else time | Storage and loss modulus | Log scales, except a linear time or temperature axis |
| Rheology | What the run swept: shear rate (a flow curve), frequency, strain, temperature, else time | G′, G″, or stress and viscosity for a flow curve | Log scales, except a linear time or temperature axis |
| SEC | Retention time | Detector response | One line per detector |
| MS | m/z | Intensity | |
| NMR | Chemical shift, high to low | Intensity | One panel per nucleus (¹H first, then ¹³C, …), its axis naming the nucleus; in comparisons each experiment keeps its colour in every panel |
| SAXS | q | Intensity | Log–log |

### Several lines from one dataset

When a dataset holds several curves on the same x values (e.g. a series of spectra), mfethuls finds the column that separates them and draws one line per value, or you can name it with `group_by=`.

- An experiment made of several files (a titration, a series) has a `source_file` column, so each file is its own line, labelled by file name.
- A workbook holding several tests (one per sheet) is one experiment whose curves carry their sheet's name in `name`. In the app's line plot, choose **Colour by → name** to draw each test as its own line.
- Overlays of several experiments give each experiment its own colour (families drawn in one colour, such as FTIR or NMR, would otherwise draw them alike).
- Up to 10 lines: a normal legend.
- More than 10 lines of a **numeric** column (e.g. `time_s`): a continuous colour bar instead of a legend. Overlays of several such experiments share one colour bar and use line style to mark the experiment.
- More than 50 lines of a numeric column (an in-situ run of hundreds of spectra): 100 of them, spread evenly from the first to the last, on the colour bar; a note says how many there are. The heatmap shows them all.

### Time-resolved data (`time_s`)

Instruments that only record a wall-clock `timestamp` per spectrum (e.g. Ocean Optics Flame series) get a `time_s` column automatically: seconds since the first timestamp of the dataset. It is added during ingest and when loading datasets stored earlier, so a 50-spectrum series plots with one *Time (s)* colour bar instead of 50 timestamps. An instrument's own `time_s` (DSC, TGA) is never replaced.

---

## Labels and units

Axis titles and legend entries use the name and unit of each canonical column, e.g. *Temperature (°C)*, *Wavenumber (cm⁻¹)* or *Stress (MPa)*. Symbols (σ, E′, η, …) are not shown: names read without knowing a field's conventions. Several columns sharing a quantity and unit share one axis title (*Modulus (MPa)*).

Labels live in `src/mfethuls/plotting/labels.py`, written in Matplotlib mathtext for superscripts. Each label also records the usual symbol, which is not drawn:

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
- no title: a publication figure's title belongs in its caption (`ax.set_title(...)` adds one)
- no top or right spine; one minor tick between major ticks on linear axes (x and y)
- legends sit right of the axes, so they never cover a curve. A legend taller than the figure is split into columns (e.g. a workbook of 18 tests), and the figure widens by the legend's width so the plot area keeps its size.

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

The **Plot** section of the app (`mfethuls-app`) offers two modes:

- **Line or scatter plots of any columns:** choose the x and y columns, **Colour by** and **Style by** columns, log axes and axis direction. Colouring by a numeric column with more than 100 values (spectra over time) draws 100 of them, spread evenly.
- **Heatmap** (plot type): a series as one image, e.g. **X axis** wavelength, **Y axis** the value (its colour), **Rows** time: every spectrum is a row. One heatmap per experiment, sharing the colour scale. More than 600 rows (or 1,200 x values) are combined into equal ranges and averaged, and a note says so. The SVG is drawn with Matplotlib.
- **Built-in instrument plot** (toggle): the plots described above, for the selected experiments. Experiments whose x-axes differ always get one panel each.
- **Normalise** (next to **Filter**): **Max = 1**, **0 to 1** or **Area = 1**, for each experiment, in line and scatter plots and the built-in plot; once chosen the button is coloured and says so (**Normalised: 0 to 1**). With x **Axis limits** set (Together or Offset), only the points inside them set the scale, so you can normalise to one peak; a note under the chart says *Normalised over … (the axis limits)*. Changing Normalise clears the y limits, which are in the old units; the x limits stay. The data and the CSV download stay as measured.
- **Layout** (in the toolbar above the chart, with several experiments in a line or scatter plot or the built-in plot): **Together** on one axis, **Offset** (each experiment shifted up by its tallest curve, so the curves don't overlap; the slider sets the **spacing**, and the y-axis shows no values since they are shifted) or **Panels** (one per experiment, one under the other, sharing the x-axis; zoom one and all follow). Axis limits apply to Together and Offset.
- **Waterfall** (in the same toolbar, for a line plot coloured by a numeric column such as **Time (s)**, even of one experiment): each line is shifted up by its colour value, the first at the bottom and the last three Offset steps above it, so a series of spectra reads like a 3D view and stays exact in 2D. A line at 10 s of a 40 s run sits a quarter of the way up. The **spacing** slider sets the height; the y-axis is labelled *(offset)* and shows no values. A long series shows its spread of 100 lines (above); the SVG is a clean vector figure for publication.

### Large datasets in the app

An in-situ run of 1,500 spectra is 1.5 million rows: more points than a screen can show, and too many to send to the browser on every click. The app:

- **draws at most about 300,000 points.** Above that, each line keeps its first and last point and the lowest and highest point of each short stretch, so peaks, dips and edges stay where they are; lines of up to 2,000 points are never thinned. A note under the toolbar says *Showing … of … points*. The SVG, HTML and CSV downloads have every point.
- **shows a spread of a long series' lines** (above), or all of them in the **heatmap**.
- **keeps the selected experiments loaded** while you change the plot, and redraws only the Plot and Preview when you change a plot option. Repeated text columns (file and experiment names) are held as categories, about a sixth of the memory.

`benchmarks/insitu_series.py` builds such a series from the example files and times ingest, loading and each plot.

The toolbar above the chart:

| Control | What it does |
|---|---|
| **Axis limits** | A toggle that opens a row of min/max fields for each axis *above* the chart, so it never covers the axes you are adjusting. Empty fields stay automatic, and each shows the automatic value as a hint. Limits apply to the chart and the SVG and stay applied when the row is closed (a note under the toolbar lists them); **Reset** clears them. Not available for histograms, box plots or multi-panel figures. |
| **Download ▾ → SVG figure** | Vector figure drawn with Matplotlib in the publication style, using the axis limits. Generated when clicked. |
| **Download ▾ → HTML figure** | Standalone interactive Plotly page. Generated when clicked. |
| **Download ▾ → CSV data** | The data of the selected experiments after the plot's **Filter**, every column, with an `experiment` column first, for plotting in other software. Generated when clicked. |

**Colours:** categorical colour columns use a discrete palette. A numeric colour column with more than 10 values (e.g. `time_s` on a spectra series) switches to a **Colour scale** picker (viridis, plasma, cividis, coolwarm, …) with a **Reverse** toggle. A column with a different value on almost every row (more than 300 values, e.g. `time_s` in DSC data) is drawn without colour groups.

**Style by:** a second column, told apart by line style (`-`, `--`, `:`, `-.`) in line plots or marker shape (circle, square, triangle, diamond, …) in scatter plots, e.g. colour by experiment and style by sample. **Signal** (the Y column) can be the style when several Y columns are plotted. The colour and style each get their own legend in the app; in the SVG they are two sections of one legend, which always fits in the figure. A style column with more values than there are styles (4 line styles, 8 markers) is ignored with a note.

**Data size:** all rows are loaded by default, so plots and exports use every data point. Under **⚙ Settings** → **Data loading**, turn off **Load all rows** to load a fixed number of rows per experiment instead. With 500,000 rows, the app takes about half a second per interaction; loaded data is cached for 10 minutes, and **Refresh** reloads it. The **Preview** table shows the first 1,000 rows.

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
