import os

import pandas as pd

from mfethuls.parsers.registry import register_parser


@register_parser('sec', 'agilent')
class AgilentSec:
    def __init__(self, file_extension='.csv', delimiter=','):
        self.file_extension = file_extension
        self.delimiter = delimiter

    def parse(self, dict_paths):
        # Store data here
        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.casefold().endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0)

                elif path.casefold().endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        return df.reset_index(drop=True)

    def parse_raw_data(self, path):
        df = pd.read_csv(path, sep=self.delimiter, names=['time (min)', 'value'], header=None) \
               .apply(pd.to_numeric, errors='coerce')
        name = f'{os.path.basename(os.path.normpath(path)).casefold().rstrip(self.file_extension)}'.replace('.dx_', '_')
        df.loc[:, 'name'] = [name] * df.shape[0]

        return df
