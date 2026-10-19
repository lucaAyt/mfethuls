"""Build an experiment's instrument (parser + characterizer) and parse its raw files into a Dataset."""

import os

from mfethuls.parsers import get_parser
from mfethuls.parsers.registry import reader_fingerprint
from mfethuls.instruments.definition import CHARACTERIZERS
from mfethuls.instruments.generic import GenericInstrument
from mfethuls.characterizers.dsc import DSCProfiling
from mfethuls.characterizers.tga import TGACharacterizer
from mfethuls.dataset import Dataset
from mfethuls.experiments import Experiment
from mfethuls.registry_validator import RegistryValidator, RegistryValidationError
from mfethuls.settings import get_settings


def get_data_root_path(folder_name: str) -> str:
    """The instrument's raw-data folder: ``folder_name`` from instrument_params.json under PATH_TO_DATA."""
    return os.path.join(get_settings().data_root, folder_name)


def instrument_data_path_constructor(path, raw_filenames):
    """``{raw_data_filename: [sorted file paths]}`` for each name in ``raw_filenames``.

    Looks in ``path`` (the instrument folder) for the files with that stem, or a
    folder named after it (see ``manifest.find_data_files``).
    """
    from mfethuls.manifest import find_data_files

    return {raw_filename: find_data_files(path, raw_filename)[1] for raw_filename in raw_filenames}


def create_instrument(type_, name, model, characterizer=None, data_root_path=None):
    parser = get_parser(type_, model)
    return GenericInstrument(type_, name, model, parser, characterizer, data_root_path)


# How to build each characterizer in ``definition.CHARACTERIZERS`` (which says the type it works on).
_BUILDERS = {
    "dsc_profiling": lambda config: DSCProfiling(config.get("sensitivity", 0.1)),
    "tga": lambda config: TGACharacterizer(),
}


def create_characterizer(type_, config):
    """The characterizer ``config`` names (``{"type": "dsc_profiling", "sensitivity": 0.1}``) for data of
    instrument type ``type_``, or None when there is none for that type."""
    name = (config or {}).get("type")
    if name not in _BUILDERS or CHARACTERIZERS[name][0] != type_:
        return None
    return _BUILDERS[name](config)


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
    """Parse the raw data of ``experiment`` with its instrument's parser and characterizer.

    Runs registry validation first to fail fast if instrument/model/profile
    expectations are not coherent. The registry row's metadata (including its
    measurement profile) is passed to the parser, and the reader's fingerprint is
    stored with the dataset.
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

    parser = instrument.parser

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
    parsed = parser.parse(dict_data_paths, **parse_kwargs)
    parsed.metadata["reader_fingerprint"] = reader_fingerprint(parser)
    return _apply_characterizer(parsed, instrument)
