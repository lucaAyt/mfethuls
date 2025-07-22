import os

from dotenv import load_dotenv

from mfethuls.parsers import get_parser
from mfethuls.instruments.generic import GenericInstrument
from mfethuls.characterizers.dsc import DSCProfiling

# Load environment variables from .env
load_dotenv()
DATA_ROOT_PATH = os.environ.get('PATH_TO_DATA')


# Use .env but entries in instrument_params.json (data_subdir) can override .env
def get_data_root_path(entry):
    if "data_subdir" in entry:
        return os.path.join(DATA_ROOT_PATH, entry["data_subdir"])
    env_key = f'{entry["type"].upper()}_FOLDER_NAME'
    return os.path.join(DATA_ROOT_PATH, os.environ.get(env_key, entry["type"]))


# Constructs paths from .env and user requirements
def instrument_data_path_constructor(path, *args):
    # Load paths into dictionary
    dict_paths = {}

    # Folders/Files interested in for analysis
    args = args[0] if len(args) == 1 and isinstance(args[0], list) else [*args]
    if not args:
        print('No files to lookup given therefore look all files in root')
        dict_paths[os.path.basename(os.path.normpath(path))] = [os.path.join(path, f) for f in os.listdir(path) \
                                                                if os.path.isfile(os.path.join(path, f))]
    else:
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


def create_instrument(type_, name, model, characterizer=None, data_root_path=None):
    parser = get_parser(type_, model)
    return GenericInstrument(type_, name, model, parser, characterizer, data_root_path)


def create_characterizer(type_, config):
    if type_ == 'dsc' and config.get('type') == 'dsc_profiling':
        return DSCProfiling(config.get('name_program_temperature', 'Tr [°C]'), config.get('sensitivity', 0.1))
