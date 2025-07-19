import os

from dotenv import load_dotenv


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
