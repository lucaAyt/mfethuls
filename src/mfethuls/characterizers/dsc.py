import pandas as pd
import numpy as np


class DSCProfiling:
    def __init__(self, sensitivity=0.1):
        self.sensitivity = sensitivity

    # Characterize vectorized
    def characterize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        if "temperature_C" not in df.columns:
            raise KeyError("DSCProfiling requires canonical column 'temperature_C'.")

        temperature_column = "temperature_C"

        def process_group(group: pd.DataFrame) -> pd.DataFrame:
            group = group.copy(deep=False)

            temperature = group[temperature_column]
            diff = temperature.diff()
            diff2 = diff.diff()

            profile = np.full(len(group), 'Isothermal', dtype=object)

            # Assign base profile
            profile[diff > 0] = 'Heating'
            profile[diff < 0] = 'Cooling'
            profile[(diff2 < -self.sensitivity) & (profile != 'Isothermal')] = 'Cooling_start'
            profile[(diff2 < -self.sensitivity) & (profile == 'Isothermal')] = 'Heating_end'
            profile[(diff2 > self.sensitivity) & (profile != 'Isothermal')] = 'Heating_start'
            profile[(diff2 > self.sensitivity) & (profile == 'Isothermal')] = 'Cooling_end'

            group = group.assign(diff=diff, diff2=diff2, profile=profile)
            profile = profile.astype(str, copy=False)

            # Identify segment ends
            heating_ends = np.char.find(profile, 'Heating_end') != -1
            cooling_ends = np.char.find(profile, 'Cooling_end') != -1

            # Segment masks
            heating_mask = np.char.startswith(profile, 'Heating')
            cooling_mask = np.char.startswith(profile, 'Cooling')
            isothermal_mask = profile == 'Isothermal'

            # Vectorized cycle IDs via cumulative sum of ends
            heating_ids = np.cumsum(heating_ends)
            cooling_ids = np.cumsum(cooling_ends)

            # For isothermal: start a new block when previous label was not Isothermal.
            prev_profile = np.insert(profile[:-1], 0, '')
            isothermal_starts = isothermal_mask & (prev_profile != 'Isothermal')
            isothermal_ids = np.cumsum(isothermal_starts) - 1

            # Apply cycle numbers
            profile[heating_mask & ~heating_ends] = [
                f"{label}_{cycle}" for label, cycle in zip(
                    profile[heating_mask & ~heating_ends],
                    heating_ids[heating_mask & ~heating_ends])
            ]

            profile[cooling_mask & ~cooling_ends] = [
                f"{label}_{cycle}" for label, cycle in zip(
                    profile[cooling_mask & ~cooling_ends],
                    cooling_ids[cooling_mask & ~cooling_ends])
            ]

            profile[isothermal_mask] = [
                f"Isothermal_{cycle}" for cycle in isothermal_ids[isothermal_mask]
            ]

            group['profile'] = profile
            return group.drop(columns=['diff', 'diff2'])

        if "name" in df.columns:
            processed = [process_group(group) for _, group in df.groupby("name", sort=False)]
            return pd.concat(processed, ignore_index=True) if processed else df.copy()
        if "run_id" in df.columns:
            processed = [process_group(group) for _, group in df.groupby("run_id", sort=False)]
            return pd.concat(processed, ignore_index=True) if processed else df.copy()

        return process_group(df).reset_index(drop=True)
