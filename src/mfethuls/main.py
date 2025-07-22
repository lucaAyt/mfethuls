import mfethuls.parsers
from mfethuls.config_loader import prepare_instruments


def main():

    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["rheometer"],
        # "type": ["dsc"],
        # "model": ["prior"]
    }

    # Load instruments and data paths for each
    bundle = prepare_instruments(filters=filters, experiments='CL_uv')

    for name, instr in bundle.instruments.items():
        print(f"{name}: {instr}")
        print("Data paths:", bundle.data_paths[name])

    # Load data for instrument and specific experiments
    dict_data_df = {}
    for name, instr in bundle.instruments.items():
        dict_data_df[name] = instr.parse_data(bundle.data_paths[name])
    print(dict_data_df)


if __name__ == "__main__":
    main()
