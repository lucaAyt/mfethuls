import os

from dotenv import load_dotenv

from mfethuls.parsers import get_parser
from mfethuls.instruments.generic import GenericInstrument
from mfethuls.characterizers.dsc import DSCProfiling
from mfethuls.characterizers.tga import TGACharacterizer
from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.registry_validator import RegistryValidator, RegistryValidationError

# Load environment variables from .env
load_dotenv()


# Prefer explicit folder name from config/instrument_params.json. Fallback is .env 
def get_data_root_path(folder_name=None, instrument_type=None):
    data_root = os.environ.get("PATH_TO_DATA")
    if folder_name:
        return os.path.join(data_root, folder_name)
    env_key = f'{instrument_type.upper()}_FOLDER_NAME'
    return os.path.join(data_root, os.environ.get(env_key, instrument_type))


def instrument_data_path_constructor(path, *args):
    """Build a dict mapping raw_data_filename → list of file paths.

    Walks ``path`` (the instrument root folder) and locates files whose stem
    matches each entry in ``args``.  All non-parquet files co-located in the
    same directory as the matched file are collected, so multi-file experiments
    work transparently.

    Returns ``{raw_data_filename: [sorted_file_paths], ...}``.
    """
    from mfethuls.manifest import find_data_files

    args = args[0] if len(args) == 1 and isinstance(args[0], list) else [*args]

    if not args:
        if not os.path.exists(path):
            raise KeyError(f'path: {path} does not exist')
        files = sorted(
            os.path.join(path, f) for f in os.listdir(path)
            if os.path.isfile(os.path.join(path, f)) and not f.endswith(".parquet")
        )
        key = os.path.basename(os.path.normpath(path))
        return {key: files}

    dict_paths: dict[str, list[str]] = {}
    for raw_filename in args:
        _parent_dir, files = find_data_files(path, raw_filename)
        dict_paths[raw_filename] = files

    return dict_paths


def create_instrument(type_, name, model, characterizer=None, data_root_path=None):
    parser = get_parser(type_, model)
    return GenericInstrument(type_, name, model, parser, characterizer, data_root_path)


def create_characterizer(type_, config):
    if type_ == 'dsc' and config.get('type') == 'dsc_profiling':
        return DSCProfiling(config.get('sensitivity', 0.1))
    if type_ == 'tga':
        return TGACharacterizer()


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

    experiment_id = experiment.experiment_id
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
