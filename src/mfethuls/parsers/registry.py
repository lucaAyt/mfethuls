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
    key = (type_, model)
    if key not in _PARSER_REGISTRY:
        raise ValueError(f"No parser for {type_} {model}")
    return _PARSER_REGISTRY[key]