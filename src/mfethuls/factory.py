import os

from dotenv import load_dotenv

from mfethuls.parsers import get_parser
from mfethuls.instruments.generic import GenericInstrument
from mfethuls.characterizers.dsc import DSCProfiling
from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.registry_validator import RegistryValidator, RegistryValidationError

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
        return DSCProfiling(config.get('sensitivity', 0.1))


def _apply_characterizer(dataset: Dataset, instrument) -> Dataset:
    """Apply optional instrument characterizer to Dataset.data in-place."""

    characterizer = getattr(instrument, "characterizer", None)
    if characterizer is None:
        return dataset

    if not hasattr(characterizer, "characterize"):
        return dataset

    dataset.data = characterizer.characterize(dataset.data)

    if not isinstance(dataset.metadata, dict):
        dataset.metadata = {}
    characterization = dataset.metadata.get("characterization")
    if not isinstance(characterization, dict):
        characterization = {}
    characterization.update(
        {
            "applied": True,
            "name": characterizer.__class__.__name__,
        }
    )
    dataset.metadata["characterization"] = characterization
    return dataset


def parse_experiment(
    experiment: Experiment,
    dict_data_paths,
    instrument,
):
    """High-level helper to parse data for a given Experiment.

    This function is an initial glue layer between the new Experiment / Dataset
    abstractions and the existing instrument + parser machinery. It does not
    alter existing code paths but provides a single-place entry point for the
    new flow.

    Runs registry validation first to fail fast if instrument/model/profile
    expectations are not coherent.
    """

    # Validate registry before attempting parse
    validator = RegistryValidator()
    is_valid, errors = validator.validate_experiment(experiment)
    if not is_valid:
        error_msg = "\n".join(errors)
        raise RegistryValidationError(
            f"Registry validation failed for experiment '{experiment.name}':\n{error_msg}"
        )

    experiment_id = RegistryValidator.validate_experiment_id(experiment.experiment_id)
    sample_id = RegistryValidator.validate_sample_id(experiment.sample_id)
    run_id = RegistryValidator.validate_run_id(experiment.run_id)

    parser = instrument.parser if hasattr(instrument, "parser") else get_parser(instrument.type_, instrument.model)

    # Prefer parsers that understand experiment context and can return a
    # Dataset directly. Fallback to the old behaviour (DataFrame + wrapper)
    # when they don't.
    parse_kwargs = dict(
        experiment_id=experiment_id,
        sample_id=sample_id,
        run_id=run_id,
        instrument_type=instrument.type_,
        instrument_model=instrument.model,
        instrument_name=instrument.name,
        experiment_name=experiment.name,
        metadata=experiment.metadata,
    )
    if instrument.type_ in {"rheometer", "dma"}:
        parse_kwargs["measurement_profile"] = experiment.metadata.get("registry_measurement_profile")

    parsed = parser.parse(dict_data_paths, **parse_kwargs)

    if isinstance(parsed, Dataset):
        return _apply_characterizer(parsed, instrument)

    # Backwards-compatible wrapper for parsers that still return DataFrames.
    metadata = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "sample_id": sample_id,
        "run_id": run_id,
        "instrument_type": instrument.type_,
        "instrument_model": instrument.model,
        "instrument_name": instrument.name,
        "experiment_name": experiment.name,
    }
    metadata.update(experiment.metadata)

    dataset = Dataset(data=parsed, metadata=metadata)
    return _apply_characterizer(dataset, instrument)
