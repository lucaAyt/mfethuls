import os

import pandas as pd

from mfethuls.parsers import register_parser


@register_parser('rheometer', 'anton_paar')
class RheometerAntPaarParser:
    def __init__(self, file_extension='.csv', delimiter='\t'):
        self.file_extension = file_extension
        self.delimiter = delimiter

    def parse(self, dict_paths):
        # Store data here
        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0).dropna(how='all', axis=1)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        return df

    def parse_raw_data(self, path):
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
        df.loc[:, 'test_type'] = os.path.basename(os.path.normpath(path)).split('$')[-1].rstrip(self.file_extension).strip('0')

        return df