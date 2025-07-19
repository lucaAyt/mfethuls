import os

from dotenv import load_dotenv
import pandas as pd

from mfethuls.instruments import instrumentation as instrm


# Constructs paths from .env and user requirements
def path_constructor(instrmnt_kw, *args):
    # Load environment variables for .env
    load_dotenv()

    # Path to folder containing instrument data
    path = os.environ.get('PATH_TO_DATA')
    env_suffix = f'{instrmnt_kw.upper()}_FOLDER_NAME'
    path = os.path.join(path, os.environ.get(env_suffix))

    # Folders/Files interested in for analysis
    if [*args]:
        args = [*args]
    else:
        print('No files to lookup given therefore look all files in root')
        args = [os.environ.get(env_suffix)]

    # Create dictionary of folders in accordance with args and folders present
    dict_paths = {}
    for root, dirs, files in os.walk(path):
        name = [os.path.normpath(root).split(os.path.sep)[-1] for name in args if name in root]
        if name:
            is_parquet = check_parquet(files)
            dict_paths[name[0]] = [os.path.join(root, f) for f in sorted(files)] if not is_parquet else \
                [os.path.join(root, f) for f in sorted(files) if '.parquet' in f]

    if not [*sum([*dict_paths.values()], [])] and not os.path.exists(path):
        raise KeyError(f'path: {path} does not exist')

    return dict_paths


def check_parquet(files):
    return True if '.parquet' in ''.join(files) else False


# Construct dataframe from different instruments via walk through paths
def get_data(dict_paths, instrmnt_kw, *args, **kwargs):
    instrmnt_kw_lwr = instrmnt_kw.lower()
    obj = None

    df = pd.DataFrame()
    for name, paths in dict_paths.items():
        for path in paths:
            print(path)

            # TODO: develop method to read type of file - user decides on path
            if instrmnt_kw_lwr == 'uv':
                if not obj:
                    obj = instrm.UV()
                obj.parse(path)

            elif instrmnt_kw_lwr == 'ftir':
                if not obj:
                    obj = instrm.FTIR()
                obj.parse(path)

            elif instrmnt_kw_lwr == 'tga':
                if not obj:
                    obj = instrm.TGA()
                obj.parse(path)

            elif instrmnt_kw_lwr == 'dsc':
                if not obj:
                    obj = instrm.DSC()
                obj.parse(path, *args, **kwargs)

            elif instrmnt_kw_lwr == 'rheology':
                if not obj:
                    obj = instrm.RHEOMETER()
                obj.parse(path)

            elif instrmnt_kw_lwr == 'insitu_uv':
                if not obj:
                    obj = instrm.UVinSitu()
                obj.parse(path)

            else:
                raise KeyError(f'The instrument keyword {instrmnt_kw} is not found')

        if obj and not obj.df.empty:
            obj.df.loc[:, 'name'] = name if 'rheo' not in instrmnt_kw_lwr else obj.df.loc[:, 'name']
            df = pd.concat([df, obj.df], axis=0)

        if obj:
            obj.clear()

    return df


if __name__ == '__main__':
    kw = 'inSitu_UV'
    df = get_data(path_constructor(kw, '2cycle'), kw)
