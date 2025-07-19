import os
import re

import pandas as pd

from mfethuls.parsers import register_parser


@register_parser('tga', 'tgaX')
class TGAXParser:
    def __init__(self, file_extension='.txt', delimiter='\s+'):
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
        lines = []
        with open(path) as f:
            take = 0
            for line in f.readlines():

                if take == 1:
                    curate_line = re.split(self.delimiter, line.strip(), maxsplit=5)
                    lines.append(curate_line)

                if 'Index' in line:
                    cols = re.split(self.delimiter, line.strip(), maxsplit=5)
                    take = 1

                elif 'Results' in line:
                    take = 0

        return pd.DataFrame(lines, columns=cols).apply(pd.to_numeric, errors='coerce').dropna() \
            .rename(columns={'Value': f'Value_{os.path.basename(os.path.normpath(path)).rstrip(".txt")}'}) \
            .set_index('Tr') \
            .drop(columns=['Index', 't', 'Ts'])
