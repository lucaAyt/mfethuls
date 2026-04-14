import os
import json

from collections import namedtuple

from mfethuls.factory import (
    get_data_root_path,
    instrument_data_path_constructor,
    create_instrument,
    create_characterizer,
    parse_experiment as _parse_experiment,
)
from mfethuls.experiments import get_experiment

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


def load_experiment_dataset(experiment_name):
    """Load and parse data for a given experiment name into a Dataset.

    This is a high-level helper that ties together the Experiment registry,
    instrument configuration, and the existing parser machinery. It keeps the
    current prepare_instruments behaviour intact while offering a simpler
    interface for users who only know the experiment name.
    """

    exp = get_experiment(experiment_name)

    # Restrict to the instrument associated with this experiment.
    filters = {"name": [exp.instrument_name]}
    bundle = prepare_instruments(filters=filters, experiments=[exp.experiment_id])

    try:
        instrument = bundle.instruments[exp.instrument_name]
        dict_data_paths = bundle.data_paths[exp.instrument_name]
    except KeyError as exc:
        raise KeyError(
            f"Instrument {exp.instrument_name!r} for experiment {experiment_name!r} "
            f"is not present in the current instrument configuration."
        ) from exc

    # Delegate parsing + Dataset construction to the factory helper.
    return _parse_experiment(exp, dict_data_paths, instrument)
