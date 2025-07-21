import os
import json

from dotenv import load_dotenv
from mfethuls.factory import create_instrument, create_characterizer

load_dotenv()
data_root_path = os.environ.get('PATH_TO_DATA')


# instrument_config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'instrument_params.json')


def load_instruments_from_json(instrument_config_path, filters=None, experiments=None):
    with open(instrument_config_path, encoding='utf8') as f:
        config = json.load(f)

    instruments = {}
    dict_data_paths = {}
    for entry in config:
        if filters:
            if not any(
                    entry.get(key) in values for key, values in filters.items() if key in entry
            ):
                continue

        type_ = entry["type"]
        model = entry["model"]
        name = entry["name"]
        exps = entry["experiments"] if not experiments else experiments
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        env_suffix = f'{type_.upper()}_FOLDER_NAME'
        data_root_path_inst = os.path.join(data_root_path, os.environ.get(env_suffix))

        instr = create_instrument(type_, name, model, characterizer, data_root_path_inst)
        instruments[name] = instr

        # Load data paths assoc. with instrument and experiments specified
        dict_data_paths[name] = instrument_data_path_constructor(data_root_path_inst, exps)

    return [instruments, dict_data_paths]


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
