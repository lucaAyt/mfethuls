"""How names are compared: raw data names and catalog view names.

Kept free of other mfethuls imports, so the manifest, discovery, the registry
validator and storage can all use the same rules.
"""

from __future__ import annotations

import re


def stem_key(raw_data_filename: str) -> str:
    """How raw data names are compared: ignoring case (``LUB446`` and ``lub446`` are the same experiment).

    Names are stored as written; every comparison of raw data names goes through this.
    """
    return str(raw_data_filename).strip().casefold()


def view_name(basename: str) -> str:
    """The catalog view for ``basename``: characters outside ``A-Za-z0-9_`` become ``_``.

    DuckDB matches view names ignoring case, so two basenames whose view names are
    equal ignoring case share one view (see :func:`view_key`).
    """
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", basename).strip("_")
    return safe or "dataset"


def view_key(basename: str) -> str:
    """What two experiments must not share: their view name, ignoring case."""
    return view_name(basename).casefold()
