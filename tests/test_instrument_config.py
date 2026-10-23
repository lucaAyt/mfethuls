"""mfethuls' own instruments and readers are complete, and each reader tells its files apart from the others'."""

from pathlib import Path

import pytest

import mfethuls.config
import mfethuls.parsers  # noqa: F401  (registers the parsers)
from mfethuls.examples import DATA_DIR
from mfethuls.instruments.configured import instrument_for_folder, instruments, readers, readers_of, recognising_readers
from mfethuls.parsers.registry import _PARSER_REGISTRY, data_extensions

CONFIG_DIR = Path(mfethuls.config.__file__).parent
# Built-in only, never the developer's data folder.
INSTRUMENTS = instruments(data_root="")
READERS = readers(data_root="")


@pytest.mark.parametrize("reader", READERS, ids=[r.name for r in READERS])
def test_reader_is_complete(reader):
    assert (reader.type, reader.model) in _PARSER_REGISTRY, "no parser registered for type/model"
    assert (CONFIG_DIR / "schemas" / f"{reader.type}.json").exists(), "no schema file for the type"
    assert reader.layout in {"file", "folder"}
    if reader.layout == "file":
        # Discovery finds one-file-per-experiment data by the reader's extensions.
        assert data_extensions(reader.parser), "a single-file reader must say which files it reads"


@pytest.mark.parametrize("instrument", INSTRUMENTS, ids=[i.name for i in INSTRUMENTS])
def test_instrument_is_complete(instrument):
    assert instrument.builtin and instrument.folder_name
    assert readers_of(instrument, data_root=""), "no reader for its type"


def test_names_and_folders_are_unique():
    for values in ([i.name for i in INSTRUMENTS], [i.folder_name.casefold() for i in INSTRUMENTS],
                   [r.name for r in READERS], [(r.type, r.model) for r in READERS]):
        assert len(values) == len(set(values))


def test_every_type_has_an_instrument_and_every_parser_a_reader():
    assert {r.type for r in READERS} == {i.type for i in INSTRUMENTS}
    assert sorted(set(_PARSER_REGISTRY) - {(r.type, r.model) for r in READERS}) == []


def _example_files():
    for path in sorted(DATA_DIR.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            yield path


@pytest.mark.parametrize("path", list(_example_files()), ids=lambda p: str(p.relative_to(DATA_DIR)))
def test_each_example_file_is_recognised_by_exactly_one_reader_of_its_instrument(path):
    """The reader matrix: two readers of one type that both claim a file are a definition bug."""
    instrument = instrument_for_folder(path.relative_to(DATA_DIR).parts[0], data_root="")
    recognising = [r.name for r in recognising_readers(readers_of(instrument, data_root=""), path)]
    assert len(recognising) == 1, recognising
