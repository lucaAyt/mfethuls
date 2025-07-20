import mfethuls.parsers
from mfethuls.config_loader import load_instruments_from_json, instrument_data_path_constructor


def main():
    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["dsc"],
        # "type": ["dsc"],
        # "model": ["prior"]
    }

    # Load instrument
    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["dsc"],
        # "type": ["dsc"],
        # "model": ["prior"]
    }
    path = r'C:\\Users\\BertossL\\dev\\mfethuls\\config\\instrument_params.json'
    dsc = load_instruments_from_json(path, filters=filters).get('dsc')
    print(f'Loaded Instrument:\n{dsc}')

    # Load paths to data for instrument and specific experiments
    # experiment_names = ''
    data_paths = instrument_data_path_constructor(dsc.type_)
    print(data_paths)
    df = dsc.parse_data(data_paths)

    print(df)

    # print("Loaded instruments:")
    # for name, instr in instruments.items():
    #     print(f"  {name}: {instr}")


if __name__ == "__main__":
    main()
