"""Choose between the Matplotlib and Plotly renderers."""

from __future__ import annotations

from typing import Literal, Optional

from .spec import PlotError, PlotSpec


Backend = Literal["matplotlib", "plotly"]

_BACKENDS = ("matplotlib", "plotly")
_default_backend: Backend = "matplotlib"


def _validate(backend: str) -> Backend:
    if backend not in _BACKENDS:
        raise PlotError(f"Unknown plotting backend {backend!r}; choose one of {list(_BACKENDS)}.")
    return backend  # type: ignore[return-value]


def set_default_backend(backend: Backend) -> None:
    """Set the backend used when a plot function is called without ``backend=``.

    ``"matplotlib"`` (the default) returns ``(fig, ax)`` and is best for publication
    figures and vector export. ``"plotly"`` returns an interactive WebGL
    ``plotly.graph_objects.Figure`` for notebooks and Streamlit.
    """

    global _default_backend
    _default_backend = _validate(backend)


def get_default_backend() -> Backend:
    return _default_backend


def render(spec: PlotSpec, *, backend: Optional[Backend] = None, ax=None):
    """Render ``spec`` with the chosen (or default) backend."""

    resolved = _validate(backend or _default_backend)
    if resolved == "plotly":
        if ax is not None:
            raise PlotError("ax= is only supported with the matplotlib backend.")
        from .render_plotly import render as render_plotly

        return render_plotly(spec)

    from .render_mpl import render as render_mpl

    return render_mpl(spec, ax=ax)
