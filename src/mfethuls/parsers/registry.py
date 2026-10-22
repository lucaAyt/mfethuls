"""The parser registry: one parser per (instrument type, model), and the fingerprint of the reader used."""

import os

_PARSER_REGISTRY = {}


def register_parser(type_, model):
    def decorator(cls):
        _PARSER_REGISTRY[(type_, model)] = cls()
        return cls

    return decorator


def data_extensions(parser):
    """File extensions (lower case) the parser reads, or ``None`` if it reads every file it is given.

    A parser declares ``file_extension`` and, when it also reads other formats,
    ``extra_extensions``. Other files next to the data (plots, notes) are ignored.
    """
    if not hasattr(parser, "file_extension"):
        return None
    return {ext.casefold() for ext in (parser.file_extension, *getattr(parser, "extra_extensions", ()))}


def reads(parser, path) -> bool:
    """Whether ``parser`` reads the file at ``path`` (see :func:`data_extensions`)."""
    extensions = data_extensions(parser)
    return extensions is None or os.path.splitext(str(path))[1].casefold() in extensions


def get_parser(type_, model):
    """The parser of the instrument with this type and model.

    Instruments are looked up by name (:func:`mfethuls.instruments.configured.parser_for`), since
    several may share a type and model; this finds the one instrument that has them, or the
    code parser registered for them. ``ValueError`` if none, or if several read them differently.
    """
    from mfethuls.instruments.configured import instrument_entries, parser_for

    names = [e["name"] for e in instrument_entries() if (e["type"], e["model"]) == (type_, model)]
    parsers = {id(p): p for p in (parser_for(name) for name in names)}
    if len(parsers) == 1:
        return next(iter(parsers.values()))
    if len(parsers) > 1:
        raise ValueError(f"Several instruments are {type_} {model} ({', '.join(sorted(names))}): "
                         "look the parser up by instrument name (parser_for).")
    if (type_, model) in _PARSER_REGISTRY:
        return _PARSER_REGISTRY[(type_, model)]
    raise ValueError(f"No parser for {type_} {model}")


def reader_fingerprint(parser) -> str:
    """Which reader read the data: a definition's content hash, or a code parser's name and version.

    Stored with every dataset; when it changes (a definition edited, a parser
    improved), Clean up offers to read the raw data again.
    """
    definition = getattr(parser, "definition", None)
    if definition is not None:
        # The definition and the version of the reader that runs it: "<hash>@tabular1".
        return f"{definition.fingerprint}@tabular{getattr(type(parser), 'version', 1)}"
    return f"{type(parser).__name__}-v{getattr(parser, 'version', 1)}"
