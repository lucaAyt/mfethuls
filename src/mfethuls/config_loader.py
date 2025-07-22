import os
import json

from collections import namedtuple

from mfethuls.factory import get_data_root_path, instrument_data_path_constructor, create_instrument, \
    create_characterizer

# Load config
instrument_config_path = os.path.join(os.path.dirname(__file__), 'config', 'instrument_params.json')
with open(instrument_config_path, encoding='utf8') as f:
    config = json.load(f)

InstrumentBundle = namedtuple("InstrumentBundle", ["instruments", "data_paths"])


def prepare_instruments(filters=None, experiments=None):
    instruments = {}
    dict_data_paths = {}

    for entry in filter_entries(filters):
        type_ = entry["type"]
        model = entry["model"]
        name = entry["name"]
        exps = entry["experiments"] if not experiments else experiments
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        data_root = get_data_root_path(entry)
        instr = create_instrument(type_, name, model, characterizer, data_root)
        instruments[name] = instr

        # Load data paths assoc. with instrument and experiments specified
        dict_data_paths[name] = instrument_data_path_constructor(data_root, exps)

    return InstrumentBundle(instruments, dict_data_paths)


def filter_entries(filters):
    if not filters:
        return config
    return [
        entry for entry in config
        if any(entry.get(k) in v for k, v in filters.items() if k in entry)
    ]
