import mfethuls.parsers
from mfethuls.config_loader import load_instruments_from_json


def main():

    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["ftir"],
        # "type": ["dsc"],
        # "model": ["prior"]
    }

    # Load instruments and data paths for each
    dict_instr, dict_data_paths = load_instruments_from_json(filters=filters, experiments=None)
    print(f'Loaded Instruments:\n{dict_instr}')
    print(f'Data Paths:\n{dict_data_paths}\n')

    # Load data for instrument and specific experiments
    dict_data_df = {}
    for name, instr in dict_instr.items():
        dict_data_df[name] = instr.parse_data(dict_data_paths[name])
    print(dict_data_df)


if __name__ == "__main__":
    main()
