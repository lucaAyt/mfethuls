from __future__ import annotations

from typing import Optional


def apply_axes_style(ax, *, title: Optional[str] = None, xlabel: Optional[str] = None, ylabel: Optional[str] = None) -> None:
    """Apply a consistent lightweight style to a Matplotlib axis."""

    ax.grid(True, alpha=0.25, linewidth=0.8)
    ax.set_facecolor("#fcfcfc")
    if title:
        ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
