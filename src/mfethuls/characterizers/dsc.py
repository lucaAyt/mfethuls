import pandas as pd


class DSCProfiling:
    def __init__(self, name_program_temperature: str, sensitivity=0.1):
        self.name_program_temperature = name_program_temperature
        self.sensitivity = sensitivity

    # TODO: Characterise Isothermal too
    def characterize(self, df: pd.DataFrame) -> pd.DataFrame:
        def process_group(group):
            group = group.copy()  # safe but can be memery intensive

            # Initialize profile
            group['profile'] = 'Isothermal'
            group['diff'] = group[self.name_program_temperature].diff()
            group['diff2'] = group['diff'].diff()

            # Label transitions
            group.loc[group['diff'] > 0, 'profile'] = 'Heating'
            group.loc[group['diff'] < 0, 'profile'] = 'Cooling'
            group.loc[
                (group['diff2'] < -self.sensitivity) & (group['profile'] != 'Isothermal'), 'profile'] = 'Cooling_start'
            group.loc[
                (group['diff2'] < -self.sensitivity) & (group['profile'] == 'Isothermal'), 'profile'] = 'Heating_end'
            group.loc[
                (group['diff2'] > self.sensitivity) & (group['profile'] != 'Isothermal'), 'profile'] = 'Heating_start'
            group.loc[
                (group['diff2'] > self.sensitivity) & (group['profile'] == 'Isothermal'), 'profile'] = 'Cooling_end'

            # Add cycle numbering
            heating_cycle = 0
            cooling_cycle = 0
            for idx, row in group.iterrows():
                profile = row['profile']
                if row['diff'] > 0:
                    if 'Heating_end' not in profile:
                        group.at[idx, 'profile'] += f'_{heating_cycle}'
                    else:
                        heating_cycle += 1
                elif row['diff'] < 0:
                    if 'Cooling_end' not in profile:
                        group.at[idx, 'profile'] += f'_{cooling_cycle}'
                    else:
                        cooling_cycle += 1
                else:
                    if 'Heating_end' in profile:
                        heating_cycle += 1
                    elif 'Cooling_end' in profile:
                        cooling_cycle += 1

            return group.drop(columns=['diff', 'diff2'])

        return df.groupby('name', group_keys=False).apply(process_group)
