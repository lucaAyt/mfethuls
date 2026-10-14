from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import matplotlib.pyplot as plt


# seaborn's plotting_context("paper", font_scale=1.75) with thicker lines,
# written out as rcParams so seaborn is not needed.
PUBLICATION_RC = {
    "font.size": 16.8,
    "axes.labelsize": 16.8,
    "axes.titlesize": 16.8,
    "legend.fontsize": 15.4,
    "legend.title_fontsize": 16.8,
    "xtick.labelsize": 15.4,
    "ytick.labelsize": 15.4,
    "axes.linewidth": 1.0,
    "grid.linewidth": 0.8,
    "lines.linewidth": 1.75,
    "lines.markersize": 6.5,
    "patch.linewidth": 1.35,
    "xtick.major.size": 4.8,
    "ytick.major.size": 4.8,
    "xtick.minor.size": 3.2,
    "ytick.minor.size": 3.2,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,
    "xtick.minor.width": 0.8,
    "ytick.minor.width": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
}


@contextmanager
def publication_style() -> Iterator[None]:
    """Black text and axes on a white background, sized for papers (``PUBLICATION_RC``).

    Starts from Matplotlib's defaults because notebook themes change the global style
    (marimo's dark theme applies ``dark_background``, which gives white text). Artists
    keep the colours they were created with, so figures created inside this context
    stay readable when saved.
    """

    with plt.style.context(["default", PUBLICATION_RC]):
        yield


def new_figure(*args, **kwargs):
    """Create a figure and axes like ``plt.subplots``, in the publication style."""

    with publication_style():
        return plt.subplots(*args, **kwargs)


def apply_axes_style(ax, *, title: Optional[str] = None, xlabel: Optional[str] = None, ylabel: Optional[str] = None) -> None:
    """Apply a consistent lightweight style to a Matplotlib axis."""

    ax.grid(True, alpha=0.25, linewidth=0.8)
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
