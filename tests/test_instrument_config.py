"""Every configured instrument can be ingested: parser, schema and data folder are all present."""

import json
from pathlib import Path

import pytest

import mfethuls.config
import mfethuls.parsers  # noqa: F401  (registers the parsers)
from mfethuls.parsers.registry import _PARSER_REGISTRY

CONFIG_DIR = Path(mfethuls.config.__file__).parent
INSTRUMENTS = json.loads((CONFIG_DIR / "instrument_params.json").read_text(encoding="utf8"))


@pytest.mark.parametrize("instrument", INSTRUMENTS, ids=[entry["name"] for entry in INSTRUMENTS])
def test_instrument_is_complete(instrument):
    assert (instrument["type"], instrument["model"]) in _PARSER_REGISTRY, "no parser registered for type/model"
    assert (CONFIG_DIR / "schemas" / f"{instrument['type']}.json").exists(), "no schema file for the type"
    assert instrument.get("folder_name"), "no folder_name: raw files cannot be located"


def test_instrument_names_are_unique():
    names = [entry["name"] for entry in INSTRUMENTS]
    assert len(names) == len(set(names))


def test_every_parser_is_used_by_an_instrument():
    configured = {(entry["type"], entry["model"]) for entry in INSTRUMENTS}
    assert sorted(set(_PARSER_REGISTRY) - configured) == []
