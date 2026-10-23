from .registry import get_parser, register_parser  # noqa: F401  (re-exported)
# Importing the parser modules registers their parsers.
from . import nmr  # noqa: F401

# Readers described by a definition (config/readers/*.json) share one parser.
# The lab's own definitions (in the data folder) are read when readers are listed.
from mfethuls.instruments.configured import _builtin as _register_builtin_definitions

_register_builtin_definitions()
