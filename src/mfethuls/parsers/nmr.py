import os

import pandas as pd
import nmrglue as ng

from mfethuls.parsers.registry import register_parser


@register_parser('nmr', 'bruker_nmr')
class RheometerAntPaarParser:
    def __init__(self, file_extension='.txt'):
        self.file_extension = file_extension

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
        dic, data = ng.bruker.read_pdata(os.path.join(path, '1', 'pdata', '1'))
        udic = ng.bruker.guess_udic(dic, data)
        uc = ng.fileiobase.uc_from_udic(udic, 0)
        return [uc, data]
