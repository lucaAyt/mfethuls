import os
import json

from mfethuls.factory import create_instrument, create_characterizer

# instrument_config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'instrument_params.json')


def load_instruments_from_json(instrument_config_path, filters=None):
    with open(instrument_config_path) as f:
        config = json.load(f)

    instruments = []
    for entry in config:
        if filters:
            if not any(
                    entry.get(key) in values for key, values in filters.items() if key in entry
            ):
                continue

        type_ = entry["type"]
        model = entry["model"]
        name = entry["name"]
        characterizer = None

        if "characterizer" in entry:
            characterizer = create_characterizer(type_, entry["characterizer"])

        instr = create_instrument(type_, name, model, characterizer)
        instruments.append(instr)

    return instruments
