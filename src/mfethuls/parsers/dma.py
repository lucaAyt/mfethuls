import os
import re

import pandas as pd

from mfethuls.parsers.registry import register_parser


@register_parser('dma', 'ta_q800')
class DmaTaQ800:
    def __init__(self, file_extension='.txt', parse_char_start='StartOfData', parse_char_end='Shiiit', delimiter='\t'):
        self.file_extension = file_extension
        self.parse_char_start = parse_char_start
        self.parse_char_end = parse_char_end
        self.delimiter = delimiter

    def parse(self, dict_paths):
        # Store data here
        df = pd.DataFrame()

        for name, paths in dict_paths.items():
            for path in paths:

                if path.endswith(self.file_extension):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        return df.reset_index(drop=True)

    def parse_raw_data(self, path):

        pattern_start = re.compile(self.parse_char_start)
        pattern_end = re.compile(self.parse_char_end)

        # Specific for DMAQ800 - pull out signal\column names
        pattern_column_name = re.compile('Sig\d')

        lines = []
        column_names = []
        with open(path) as f:
            take = False
            for line in f.readlines():

                # Match signal name - this could break if line empty (edgecase)
                if pattern_column_name.match(line):
                    column_names.append(re.split(self.delimiter, line.strip(), maxsplit=2)[1].casefold())

                if take:
                    l = re.split(self.delimiter, line.strip())
                    lines.append(l)

                if pattern_start.match(line):
                    take = True

                elif pattern_end.match(line):
                    take = False

        # Make up columns by combining 1st and 2nd lines
        df = pd.DataFrame(lines, columns=column_names).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        return df
