"""Small file helpers shared by the manifest and the saved settings."""

from __future__ import annotations

import os
import time


def replace_with_retry(source: str, target: str, attempts: int = 10) -> None:
    """``os.replace``, retried briefly: on Windows it fails while another process has the target open.

    Virus scanners, indexers and sync clients (OneDrive) open freshly written files for
    a moment; waiting a little and trying again is enough.
    """
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
