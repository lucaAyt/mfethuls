import os

import pandas as pd

from mfethuls.parsers.registry import register_parser


@register_parser('ftir', 'bruker')
class BrukerFTIRParser:
    def __init__(self, file_extension='.csv', delimiter=','):
        self.file_extension = file_extension
        self.delimiter = delimiter

    def parse(self, dict_paths):
        # Store data here
        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=1).dropna(how='all', axis=1)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        return df

    def parse_raw_data(self, path):
        return pd.read_csv(path, skiprows=lambda x: x in [0, 0], sep=self.delimiter) \
                 .set_index('cm-1') \
                 .rename(columns={'%T': os.path.basename(os.path.normpath(path)).split('_')[-1].rstrip(self.file_extension).lstrip('0')}) \
                 .astype(float)