"""``mfethuls-app``: start the Streamlit app. Extra arguments are passed to ``streamlit run``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_streamlit(script: Path, argv: list[str] | None = None) -> int:
    """Run ``streamlit run script`` with this Python; returns its exit code."""
    args = sys.argv[1:] if argv is None else argv
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(script), *args])


def main(argv: list[str] | None = None) -> int:
    return run_streamlit(Path(__file__).with_name("streamlit_app.py"), argv)


if __name__ == "__main__":
    raise SystemExit(main())
