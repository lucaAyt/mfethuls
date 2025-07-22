import os

import pandas as pd

from dateutil.parser import parse
from datetime import timedelta
from dateutil.tz import gettz, UTC

from mfethuls.parsers.registry import register_parser


@register_parser('inSitu_UV', 'flame')
@register_parser('reflection', 'flame')
class FlameOceanOpticsParser:
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
        # Get milliseconds from timestamp in filename if data was saved with timestamp suffix
        filenname_suffix = os.path.basename(path).split('_')[-1].rstrip(self.file_extension)
        milliseconds = timedelta(milliseconds=float(filenname_suffix.split('-')[-1])) if '-' in filenname_suffix \
            else timedelta(0)

        with open(path) as file:
            for line in file:
                if line.startswith('Date'):
                    timestamp = line.split(': ')[-1].strip()
                if 'Number of Pixels' in line:
                    break
            df = pd.read_csv(file, sep='\t', header=1)

        df.columns = ['wavelength (nm)', 'transmission']
        df.loc[:, 'timestamp'] = handle_tz(timestamp) + milliseconds

        # cut data
        df = df[df['wavelength (nm)'].between(280, 900)]

        return df


@register_parser('uv_vis', 'Shimadzu')
class ShimadzuUVVisParser:
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
        df = pd.read_csv(path, header=1, sep='\t').astype(float)

        # Additional 'meta' data: You can use underscore for titration meta data. Delete post if not needed in output
        titrant_info = os.path.basename(os.path.normpath(path)).split('_')[-1].rstrip(self.file_extension).lstrip('0')
        df.loc[:, 'titrant'] = titrant_info if not titrant_info == '' else '0'  # I DNA
        df.loc[:, 'name'] = [f'{os.path.basename(os.path.dirname(path))}'] * df.shape[0]

        return df


def handle_tz(ts: str):
    tzinfos = {"CET": gettz("Europe/Zurich"), "CEST": gettz("Europe/Zurich")}
    timestamp_eu = parse(ts, tzinfos=tzinfos)
    return pd.to_datetime(timestamp_eu.astimezone(UTC).isoformat())
