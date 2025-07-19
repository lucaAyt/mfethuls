import os
import re

from datetime import timedelta
from dateutil.tz import gettz, UTC
from dateutil.parser import parse
import pandas as pd
import nmrglue as ng

from ..abstractions import InstrumentParser, InstrumentMethod


# Collection of instruments which perform a bunch of collective functions

class UV(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if '.txt' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path)], axis=0)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):
        data_df = pd.read_csv(path, header=1, sep='\t').astype(float)

        # Additional 'meta' data: You can use underscore for titration meta data. Delete post if not needed in output
        titrant_info = os.path.basename(os.path.normpath(path)).split('_')[-1].rstrip('.txt').lstrip('0')
        data_df.loc[:, 'titrant'] = titrant_info if not titrant_info == '' else '0'

        return data_df

    def clear(self):
        self.df = pd.DataFrame()


class FTIR(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if '.csv' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path)], axis=1).dropna(how='all', axis=1)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):
        return pd.read_csv(path, skiprows=lambda x: x in [0, 0], sep=',') \
            .set_index('cm-1') \
            .rename(columns={'%T': os.path.basename(os.path.normpath(path)).split('_')[-1].rstrip('.csv').lstrip('0')}) \
            .astype(float)

    def clear(self):
        self.df = pd.DataFrame()


class TGA(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if '.txt' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path)], axis=1).dropna(how='all', axis=1)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):
        lines = []
        with open(path) as f:
            take = 0
            for line in f.readlines():

                if take == 1:
                    curate_line = re.split('\s+', line.strip(), maxsplit=5)
                    lines.append(curate_line)

                if 'Index' in line:
                    cols = re.split('\s+', line.strip(), maxsplit=5)
                    take = 1
                elif 'Results' in line:
                    take = 0

        return pd.DataFrame(lines, columns=cols).apply(pd.to_numeric, errors='coerce').dropna() \
            .rename(columns={'Value': f'Value_{os.path.basename(os.path.normpath(path)).rstrip(".txt")}'}) \
            .set_index('Tr') \
            .drop(columns=['Index', 't', 'Ts'])

    def clear(self):
        self.df = pd.DataFrame()


class DSC(InstrumentParser, InstrumentMethod):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path, *args, **kwargs):
        if '.txt' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path, *args, **kwargs)], axis=0).dropna(how='all', axis=1)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path, char_start='\s+Index', char_end='Result', delim='\s+'):

        pattern_start = re.compile(char_start)
        pattern_end = re.compile(char_end)

        lines = []
        with open(path) as f:
            take = False
            for line in f.readlines():

                if take:
                    curate_line = re.split(delim, line.strip())
                    lines.append(curate_line)

                if pattern_start.match(line):
                    cols = re.split(delim, line.strip())
                    take = 1
                elif pattern_end.match(line):
                    take = 0

        df = pd.DataFrame(lines, columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df['name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(".txt")}'] * df.shape[0]

        # TODO: Make more elegant >: AND PULL OUT of get_data_df !!!!!!
        # Cut heating, cooling and isothermal cycles - label accordingly
        df['cycle'] = ['Isothermal'] * len(df.Tr)
        df['differ'] = df.Tr.diff()
        df['differ_1'] = df.differ.diff()

        df.loc[df.differ > 0, 'cycle'] = 'Heating'
        df.loc[df.differ < 0, 'cycle'] = 'Cooling'
        df.loc[(df.differ_1 < -0.1) & (df.cycle != 'Isothermal'), 'cycle'] = 'Cooling_start'
        df.loc[(df.differ_1 < -0.1) & (df.cycle == 'Isothermal'), 'cycle'] = 'Heating_end'
        df.loc[(df.differ_1 > 0.1) & (df.cycle != 'Isothermal'), 'cycle'] = 'Heating_start'
        df.loc[(df.differ_1 > 0.1) & (df.cycle == 'Isothermal'), 'cycle'] = 'Cooling_end'

        heating_cycle_num = 0
        cooling_cycle_num = 0
        for index, row in df.iterrows():
            if row.differ > 0.0:
                if 'Heating_end' not in row.cycle:
                    df.loc[index, 'cycle'] = df.loc[index, 'cycle'] + f'_{str(heating_cycle_num)}'
                else:
                    heating_cycle_num += 1

            elif row.differ < 0.0:
                if 'Cooling_end' not in row.cycle:
                    df.loc[index, 'cycle'] = df.loc[index, 'cycle'] + f'_{str(cooling_cycle_num)}'
                else:
                    cooling_cycle_num += 1

            else:
                if 'Heating_end' in row.cycle:
                    heating_cycle_num += 1
                elif 'Cooling_end' in row.cycle:
                    cooling_cycle_num += 1

        return df.drop(columns=['differ', 'differ_1'])

    def characterise_data(self, temp_name: str = 'Tr [°C]', sensitivity: float = 0.01):

        # TODO: Make more elegant >:
        # Cut heating, cooling and isothermal cycles - label accordingly
        self.df['cycle'] = ['Isothermal'] * len(self.df[temp_name])
        self.df['differ'] = self.df[temp_name].diff()
        self.df['differ_1'] = self.df.differ.diff()

        self.df.loc[self.df.differ > 0, 'cycle'] = 'Heating'
        self.df.loc[self.df.differ < 0, 'cycle'] = 'Cooling'
        self.df.loc[(self.df.differ_1 < -sensitivity) & (self.df.cycle != 'Isothermal'), 'cycle'] = 'Cooling_start'
        self.df.loc[(self.df.differ_1 < -sensitivity) & (self.df.cycle == 'Isothermal'), 'cycle'] = 'Heating_end'
        self.df.loc[(self.df.differ_1 > sensitivity) & (self.df.cycle != 'Isothermal'), 'cycle'] = 'Heating_start'
        self.df.loc[(self.df.differ_1 > sensitivity) & (self.df.cycle == 'Isothermal'), 'cycle'] = 'Cooling_end'

        heating_cycle_num = 0
        cooling_cycle_num = 0
        for index, row in self.df.iterrows():
            if row.differ > 0.0:
                if 'Heating_end' not in row.cycle:
                    self.df.loc[index, 'cycle'] = self.df.loc[index, 'cycle'] + f'_{str(heating_cycle_num)}'
                else:
                    heating_cycle_num += 1

            elif row.differ < 0.0:
                if 'Cooling_end' not in row.cycle:
                    self.df.loc[index, 'cycle'] = self.df.loc[index, 'cycle'] + f'_{str(cooling_cycle_num)}'
                else:
                    cooling_cycle_num += 1

            else:
                if 'Heating_end' in row.cycle:
                    heating_cycle_num += 1
                elif 'Cooling_end' in row.cycle:
                    cooling_cycle_num += 1

        return self.df.drop(columns=['differ', 'differ_1'])

    def clear(self):
        self.df = pd.DataFrame()


class NMR(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if '.txt' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path)], axis=1).dropna(how='all', axis=1)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):
        dic, data = ng.bruker.read_pdata(os.path.join(path, '1', 'pdata', '1'))
        udic = ng.bruker.guess_udic(dic, data)
        uc = ng.fileiobase.uc_from_udic(udic, 0)
        return [uc, data]

    def clear(self):
        self.df = pd.DataFrame()


class RHEOMETER(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if '.csv' in path[-4:]:

            self.df = pd.concat([self.df, self.get_data_df(path)], axis=0).dropna(how='all', axis=1)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):
        # Quite a shitty parse
        df = pd.read_csv(path, engine='python', encoding='utf-8', on_bad_lines='skip', skip_blank_lines=True,
                         header=[4, 6], sep='\t') \
            .dropna(how='all') \
            .reset_index(drop=True) \
            .sort_index(axis=1) \
            .drop(columns=['Interval data:', 'Point No.'])

        # Rename columns
        df.columns = df.columns.get_level_values(0) + [f' {col}' if 'Unnamed' not in col else '' for col in
                                                       df.columns.get_level_values(1)]
        df.loc[:, 'name'] = os.path.basename(os.path.normpath(path)).split('$')[0]
        df.loc[:, 'test_type'] = os.path.basename(os.path.normpath(path)).split('$')[-1].rstrip('.csv').strip('0')

        return df

    def clear(self):
        self.df = pd.DataFrame()


class UVinSitu(InstrumentParser):

    def __init__(self):
        super().__init__()
        self.df = pd.DataFrame()

    def parse(self, path):
        if path.endswith('.txt'):

            # self.df = pd.concat([self.df, self.get_data_df(path)], axis=1).dropna(how='all', axis=1)
            self.df = pd.concat([self.df, self.get_data_df(path)], axis=0)

        elif path.endswith('.parquet'):

            self.df = pd.concat([self.df, pd.read_parquet(path)], axis=0)

        else:
            print(f'Not reading: {path}')

    def get_data_df(self, path):

        def handle_tz(ts: str):
            tzinfos = {"CET": gettz("Europe/Zurich"), "CEST": gettz("Europe/Zurich")}
            timestamp_eu = parse(ts, tzinfos=tzinfos)
            return pd.to_datetime(timestamp_eu.astimezone(UTC).isoformat())

        # Get milliseconds from timestamp in filename if data was saved with timestamp suffix
        filenname_suffix = os.path.basename(path).split('_')[-1].rstrip('.txt')
        milliseconds = timedelta(milliseconds=float(filenname_suffix.split('-')[-1])) if '-' in filenname_suffix \
            else timedelta(0)

        with open(path) as file:
            for line in file:
                if line.startswith('Date'):
                    timestamp = line.split(': ')[-1].strip()
                if 'Number of Pixels' in line:
                    break
            data_df = pd.read_csv(file, sep='\t', header=1)

        data_df.columns = ['wavelength (nm)', 'transmission']
        data_df.loc[:, 'timestamp'] = handle_tz(timestamp) + milliseconds

        # cut data
        data_df = data_df[data_df['wavelength (nm)'].between(280, 900)]

        return data_df

    def clear(self):
        self.df = pd.DataFrame()
