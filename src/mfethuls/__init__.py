from .comparison import ComparisonSet, load_experiments, load_samples
from .config.mode import use_test_env


def plot_experiments(*args, **kwargs):
	from .plotting.comparison import plot_experiments as _plot_experiments

	return _plot_experiments(*args, **kwargs)


def set_plot_backend(backend):
	"""Default plotting backend: "matplotlib" (publication, vector SVG) or "plotly" (interactive)."""
	from .plotting.backend import set_default_backend

	set_default_backend(backend)

__all__ = [
	"ComparisonSet",
	"load_experiments",
	"load_samples",
	"plot_experiments",
	"set_plot_backend",
	"use_test_env",
]