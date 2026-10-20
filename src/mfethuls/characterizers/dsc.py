import pandas as pd
import numpy as np


class DSCProfiling:
    """Label each DSC point with its temperature segment: ``Heating_1``, ``Isothermal_2``, ``Cooling_1``...

    Segments are numbered from 1 per type, in measurement order. The kinks where a ramp starts or
    ends (found with ``sensitivity`` on the second difference) are folded into the ramp, so
    there are no separate start or end labels.
    """

    def __init__(self, sensitivity=0.1):
        self.sensitivity = sensitivity

    def characterize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        if "temperature_C" not in df.columns:
            raise KeyError("DSCProfiling requires canonical column 'temperature_C'.")

        temperature_column = "temperature_C"

        def process_group(group: pd.DataFrame) -> pd.DataFrame:
            group = group.copy(deep=False)

            diff = group[temperature_column].diff()
            diff2 = diff.diff()

            # The first point of a ramp already steps up or down, so it is in the ramp.
            segment = np.full(len(group), 'Isothermal', dtype=object)
            segment[diff > 0] = 'Heating'
            segment[diff < 0] = 'Cooling'

            # The first flat point after a ramp is where the ramp ends: it belongs to the ramp too.
            flat = segment == 'Isothermal'
            segment[flat & (diff2 < -self.sensitivity)] = 'Heating'
            segment[flat & (diff2 > self.sensitivity)] = 'Cooling'

            # Number each run of the same segment type, from 1 per type.
            labels = pd.Series(segment, index=group.index)
            run_number = (labels != labels.shift()).groupby(labels).cumsum()
            group['profile'] = labels + '_' + run_number.astype(str)
            return group

        if "name" in df.columns:
            processed = [process_group(group) for _, group in df.groupby("name", sort=False)]
            return pd.concat(processed, ignore_index=True) if processed else df.copy()
        if "run_id" in df.columns:
            processed = [process_group(group) for _, group in df.groupby("run_id", sort=False)]
            return pd.concat(processed, ignore_index=True) if processed else df.copy()

        return process_group(df).reset_index(drop=True)
