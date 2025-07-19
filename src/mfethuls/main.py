from mfethuls.config_loader import load_instruments_from_json
import mfethuls.parsers


def main():
    # Example filter: only load specific instruments by name, type, or model
    filters = {
        "name": ["dsc"],
        "type": ["dsc"],
        "model": ["prior"]
    }
    path = r'C:\\Users\\BertossL\\dev\\mfethuls\\config\\instrument_params.json'
    instruments = load_instruments_from_json(path, filters=filters)
    for instr in instruments:
        print(f"{instr.name}: {instr}")


if __name__ == "__main__":
    main()
