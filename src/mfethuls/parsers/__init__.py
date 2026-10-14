from .registry import get_parser, register_parser  # noqa: F401  (re-exported)
# Importing the parser modules registers their parsers.
from . import dsc, ftir, nmr, rheometer, tga, uv_vis, sec, dma, saxs, ms  # noqa: F401
