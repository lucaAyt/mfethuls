from .comparison import ComparisonSet, load_experiments, load_samples


def plot_experiments(*args, **kwargs):
	from .plotting.comparison import plot_experiments as _plot_experiments

	return _plot_experiments(*args, **kwargs)

__all__ = [
	"ComparisonSet",
	"load_experiments",
	"load_samples",
	"plot_experiments",
]