"""Display-only normalisation of each experiment's curves (plotting/normalise.py)."""

import numpy as np
import pandas as pd
import pytest

from mfethuls.dataset import Dataset
from mfethuls.plotting import PlotError, build_experiments_spec
from mfethuls.plotting.normalise import normalisation, normalise_traces
from mfethuls.plotting.spec import Trace


def _trace(y, x=None):
    y = np.asarray(y, dtype=float)
    return Trace(np.arange(len(y), dtype=float) if x is None else np.asarray(x, dtype=float), y)


def test_max_scales_the_largest_magnitude_to_one():
    traces = [_trace([0.0, -4.0, 2.0])]
    assert normalise_traces(traces, "max")
    assert list(traces[0].y) == [0.0, -1.0, 0.5]  # a negative peak becomes -1


def test_minmax_runs_from_zero_to_one():
    traces = [_trace([2.0, 4.0]), _trace([6.0, np.nan])]  # one experiment's curves together; NaN ignored
    assert normalise_traces(traces, "minmax")
    assert list(traces[0].y) == [0.0, 0.5] and traces[1].y[0] == 1.0 and np.isnan(traces[1].y[1])


def test_area_is_one_whatever_the_order_of_x():
    traces = [_trace([2.0, 2.0, 2.0], x=[2.0, 0.0, 1.0])]  # area 2 x 2 = 4
    assert normalise_traces(traces, "area")
    assert traces[0].y == pytest.approx([0.5, 0.5, 0.5])


@pytest.mark.parametrize("method, y", [("max", [0.0, 0.0]), ("minmax", [3.0, 3.0]), ("area", [0.0, 0.0]),
                                       ("max", [np.nan, np.nan])])
def test_curves_that_cannot_be_normalised_are_left_as_they_are(method, y):
    traces = [_trace(y)]
    assert not normalise_traces(traces, method)
    assert np.array_equal(traces[0].y, np.asarray(y, dtype=float), equal_nan=True)


def test_unknown_method_is_refused():
    with pytest.raises(ValueError):
        normalisation([[0.0]], [[1.0]], "median")


def _dsc(name, heat):
    return Dataset(data=pd.DataFrame({"temperature_C": [25.0, 50.0, 75.0], "heat_flow_mW": heat}),
                   metadata={"experiment_name": name, "instrument_type": "dsc"})


def test_experiments_are_normalised_then_offset():
    spec = build_experiments_spec([_dsc("A", [0.0, 5.0, 10.0]), _dsc("B", [0.0, 1.0, 2.0])],
                                  mode="stacked", normalise="minmax")
    lows = sorted(round(float(t.y.min()), 6) for t in spec.panel.traces)
    highs = sorted(round(float(t.y.max()), 6) for t in spec.panel.traces)
    assert lows == [0.0, 1.1] and highs == [1.0, 2.1]  # both 0..1, B shifted by 1.1 x 1
    assert spec.panel.ylabel.startswith("Heat flow (normalised)")
    assert spec.panel.ylabel.endswith("(offset)")


def test_an_experiment_that_cannot_be_normalised_is_noted():
    spec = build_experiments_spec([_dsc("A", [1.0, 2.0, 3.0]), _dsc("Flat", [2.0, 2.0, 2.0])],
                                  mode="facet", normalise="minmax")
    assert spec.notes == ["Flat is drawn as it is: it cannot be normalised (0 to 1)."]
    assert "(normalised)" in spec.panels[0].ylabel and "(normalised)" not in (spec.panels[1].ylabel or "")
    with pytest.raises(PlotError):
        build_experiments_spec([_dsc("A", [1.0, 2.0, 3.0])], normalise="median")


def test_normalised_curves_lose_their_unit():
    from mfethuls.plotting.normalise import normalised_label

    assert normalised_label("Heat flow (mW)") == "Heat flow (normalised)"
    assert normalised_label("Absorbance") == "Absorbance (normalised)"
    assert normalised_label(None) == "Normalised"


def test_zero_to_one_on_a_log_axis_is_noted():
    from mfethuls.plotting.normalise import LOG_MINMAX_NOTE

    def rheo(name, g):
        return Dataset(data=pd.DataFrame({"angular_frequency_rad_s": [0.1, 1.0, 10.0], "storage_modulus_pa": g,
                                          "loss_modulus_pa": g}),
                       metadata={"experiment_name": name, "instrument_type": "rheometer"})

    spec = build_experiments_spec([rheo("A", [1.0, 10.0, 100.0]), rheo("B", [2.0, 20.0, 200.0])],
                                  normalise="minmax")
    assert spec.panel.yscale == "log" and LOG_MINMAX_NOTE in spec.notes
    assert LOG_MINMAX_NOTE not in build_experiments_spec([rheo("A", [1.0, 10.0, 100.0])], normalise="max").notes


def test_area_is_the_net_area():
    traces = [_trace([1.0, 1.0, -1.0, -1.0], x=[0.0, 1.0, 1.0, 2.0])]  # +1 then -1 (a zero-width step between)
    assert normalisation([t.x for t in traces], [t.y for t in traces], "area") is None  # nets to 0


def test_a_window_on_x_sets_the_scale_for_the_whole_curve():
    traces = [_trace([1.0, 10.0, 2.0, 4.0], x=[0.0, 1.0, 2.0, 3.0])]
    assert normalise_traces(traces, "max", x_range=(2.0, None))  # only x >= 2: the peak there is 4
    assert list(traces[0].y) == [0.25, 2.5, 0.5, 1.0]  # every point scaled; outside the window may exceed 1
    assert normalisation([[0.0, 1.0]], [[1.0, 2.0]], "max", x_range=(5.0, 6.0)) is None  # nothing in the window


def test_experiments_are_normalised_over_the_window():
    spec = build_experiments_spec([_dsc("A", [0.0, 5.0, 10.0]), _dsc("B", [0.0, 1.0, 2.0])],
                                  normalise="max", normalise_x=(None, 50.0))
    peaks = sorted(round(float(t.y[1]), 6) for t in spec.panel.traces)  # the value at 50 °C
    assert peaks == [1.0, 1.0]
    empty = build_experiments_spec([_dsc("A", [0.0, 5.0, 10.0])], normalise="max", normalise_x=(200.0, 300.0))
    assert empty.notes == ["A is drawn as it is: it cannot be normalised (Max = 1) over x 200 to 300."]
