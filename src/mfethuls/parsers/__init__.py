from .registry import get_parser, register_parser  # noqa: F401  (re-exported)
# Importing the parser modules registers their parsers.
from . import nmr  # noqa: F401

# Instruments described by a definition (config/instruments/*.json) share one parser.
# The lab's own definitions (in the data folder) are registered when instruments are listed.
from mfethuls.instruments.configured import _builtin as _register_builtin_definitions

_register_builtin_definitions()
