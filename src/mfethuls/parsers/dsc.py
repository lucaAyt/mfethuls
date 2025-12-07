import os
import re

import pandas as pd

from mfethuls.parsers.registry import register_parser


@register_parser('dsc', 'prior')
class DSCPriorParser:
    def __init__(self, file_extension='.txt'):
        self.file_extension = file_extension

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

        # Make up columns by combining 1st and 2nd lines
        cols_row_2 = [''] + lines[0]
        cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

        df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        return df


@register_parser('dsc', 'perkin_elmer')
class DSCPerkinElmerParser:
    def __init__(self, file_extension='.txt', parse_char_start='\tTime', parse_char_end='Shiiit', delimiter='\t'):
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

                elif path.endswith('.csv'):
                    df = pd.concat([df, self.parse_raw_data(path)], axis=0)

                elif path.endswith('.parquet'):
                    df = pd.concat([df, pd.read_parquet(path)], axis=0)

                else:
                    print(f'Not reading: {path}')

        return df.reset_index(drop=True)

    def parse_raw_data(self, path):

        if not path.endswith('.csv'):

            pattern_start = re.compile(self.parse_char_start)
            pattern_end = re.compile(self.parse_char_end)

            lines = []
            with open(path) as f:
                take = False
                for line in f.readlines():

                    if take:
                        l = re.split(self.delimiter, line.strip())
                        lines.append(l)

                    if pattern_start.match(line):
                        cols = re.split(self.delimiter, line.strip())
                        take = True

                    elif pattern_end.match(line):
                        take = False

            # Make up columns by combining 1st and 2nd lines
            cols_row_2 = [''] + lines[0]
            cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, cols_row_2)]

            df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
            df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        else:

            filename = f'{os.path.basename(os.path.normpath(path)).rstrip(".csv")}'
            df = pd.read_csv(path).assign(name=filename)

        return df


@register_parser('dsc', 'mettler_toledo')
class DSCMettlerToledoParser:
    def __init__(self, file_extension='.txt', parse_char_start='\s+Index', parse_char_end='Shiiit', delimiter='\s\s+'):
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

        lines = []
        with open(path) as f:
            take = False
            for line in f.readlines():

                if take:
                    l = re.split(self.delimiter, line.strip())
                    lines.append(l)

                if pattern_start.match(line):
                    cols = re.split(self.delimiter, line.strip())
                    take = True

                elif pattern_end.match(line):
                    take = False

        # Make up columns by combining 1st and 2nd lines
        cols = [' '.join([col1.strip(), col2.strip()]).strip() for col1, col2 in zip(cols, lines[0])]

        df = pd.DataFrame(lines[1:], columns=cols).apply(pd.to_numeric, errors='coerce').dropna(axis=0)
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.normpath(path)).rstrip(self.file_extension)}'] * df.shape[0]

        return df
