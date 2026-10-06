from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt


def new_figure(*args, **kwargs):
    """Create a figure and axes like ``plt.subplots``, with a transparent background."""

    fig, axes = plt.subplots(*args, **kwargs)
    fig.patch.set_alpha(0.0)
    return fig, axes


def apply_axes_style(ax, *, title: Optional[str] = None, xlabel: Optional[str] = None, ylabel: Optional[str] = None) -> None:
    """Apply a consistent lightweight style to a Matplotlib axis."""

    ax.grid(True, alpha=0.25, linewidth=0.8)
    ax.set_facecolor("none")
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
