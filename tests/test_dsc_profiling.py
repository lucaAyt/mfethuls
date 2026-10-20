import itertools

import numpy as np
import pandas as pd

from mfethuls.characterizers.dsc import DSCProfiling


def _program(*steps):
    """Temperatures for a program of (start, end, points) steps; a flat step has start == end."""
    return np.concatenate([np.linspace(start, end, points) for start, end, points in steps])


def _runs(profile):
    return [(label, len(list(group))) for label, group in itertools.groupby(profile)]


def test_segments_are_numbered_from_one_without_start_or_end_labels():
    temperature = _program((25, 25, 5), (26, 35, 10), (35, 35, 5), (34, 25, 10), (25, 25, 5), (26, 35, 10))
    out = DSCProfiling(sensitivity=0.5).characterize(pd.DataFrame({"temperature_C": temperature}))

    # The first flat point after each ramp is the ramp's end, so it joins the ramp.
    assert _runs(out["profile"]) == [
        ("Isothermal_1", 5), ("Heating_1", 11), ("Isothermal_2", 4),
        ("Cooling_1", 11), ("Isothermal_3", 4), ("Heating_2", 10),
    ]
    assert list(out.columns) == ["temperature_C", "profile"]


def test_heating_straight_into_cooling_starts_a_new_cooling_segment():
    temperature = _program((25, 34, 10), (35, 26, 10), (25, 34, 10), (35, 26, 10))
    out = DSCProfiling(sensitivity=0.5).characterize(pd.DataFrame({"temperature_C": temperature}))

    labels = [label for label, _ in _runs(out["profile"])]
    assert labels == ["Isothermal_1", "Heating_1", "Cooling_1", "Heating_2", "Cooling_2"]


def test_labels_are_not_cut_short_after_many_segments():
    steps = [(25, 25, 3), (26, 35, 10), (35, 35, 3), (34, 25, 10)] * 12
    out = DSCProfiling(sensitivity=0.5).characterize(pd.DataFrame({"temperature_C": _program(*steps)}))

    assert "Isothermal_24" in set(out["profile"]) and "Heating_12" in set(out["profile"])


def test_each_file_is_numbered_on_its_own():
    temperature = _program((25, 25, 3), (26, 35, 10))
    df = pd.DataFrame({"temperature_C": np.concatenate([temperature, temperature]),
                       "name": ["a"] * len(temperature) + ["b"] * len(temperature)})
    out = DSCProfiling(sensitivity=0.5).characterize(df)

    for _, group in out.groupby("name"):
        assert [label for label, _ in _runs(group["profile"])] == ["Isothermal_1", "Heating_1"]
