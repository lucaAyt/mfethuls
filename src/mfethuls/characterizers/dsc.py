import pandas as pd


class DSCProfiling:
    def __init__(self, name_program_temperature: str, sensitivity=0.1):
        self.name_program_temperature = name_program_temperature
        self.sensitivity = sensitivity

    def characterize(self, data: pd.DataFrame()):

        # TODO: Make more elegant >: and characterise isothermals !!
        # Cut heating, cooling and isothermal cycles - label accordingly
        data['profile'] = ['Isothermal'] * len(data[self.name_program_temperature])
        data['diff'] = data[self.name_program_temperature].diff()
        data['diff2'] = data.differ.diff()

        data.loc[data.differ > 0, 'profile'] = 'Heating'
        data.loc[data.differ < 0, 'profile'] = 'Cooling'
        data.loc[(data.differ_1 < -self.sensitivity) & (data.cycle != 'Isothermal'), 'profile'] = 'Cooling_start'
        data.loc[(data.differ_1 < -self.sensitivity) & (data.cycle == 'Isothermal'), 'profile'] = 'Heating_end'
        data.loc[(data.differ_1 > self.sensitivity) & (data.cycle != 'Isothermal'), 'profile'] = 'Heating_start'
        data.loc[(data.differ_1 > self.sensitivity) & (data.cycle == 'Isothermal'), 'profile'] = 'Cooling_end'

        heating_cycle_num = 0
        cooling_cycle_num = 0
        for index, row in data.iterrows():
            if row.differ > 0.0:
                if 'Heating_end' not in row.profile:
                    data.loc[index, 'profile'] = data.loc[index, 'profile'] + f'_{str(heating_cycle_num)}'
                else:
                    heating_cycle_num += 1

            elif row.differ < 0.0:
                if 'Cooling_end' not in row.profile:
                    data.loc[index, 'profile'] = data.loc[index, 'profile'] + f'_{str(cooling_cycle_num)}'
                else:
                    cooling_cycle_num += 1

            else:
                if 'Heating_end' in row.profile:
                    heating_cycle_num += 1
                elif 'Cooling_end' in row.profile:
                    cooling_cycle_num += 1

        return data.drop(columns=['differ', 'differ_1'])
