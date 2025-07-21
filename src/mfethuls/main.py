import mfethuls.parsers
from mfethuls.config_loader import load_instruments_from_json


def main():
    # Load instrument
    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["ftir"],
        # "type": ["dsc"],
        # "model": ["prior"]
    }
    path = r'C:\Users\BertossL\dev\mfethuls\config\instrument_params.json'
    dict_instr, dict_data_paths = load_instruments_from_json(path, filters=filters, experiments=None)
    print(f'Loaded Instruments:\n{dict_instr}')
    print(f'Data Paths:\n{dict_data_paths}\n')

    # Load paths to data for instrument and specific experiments
    dict_data_df = {}
    for name, instr in dict_instr.items():
        dict_data_df[name] = instr.parse_data(dict_data_paths[name])
    print(dict_data_df)


if __name__ == "__main__":
    main()
