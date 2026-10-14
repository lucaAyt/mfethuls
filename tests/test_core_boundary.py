"""mfethuls stands on its own: it never imports mfethuls_server or the server's dependencies.

The server builds on the core by passing its own stores and app backend in; the
core must not reach back. These tests keep that boundary in place.
"""

import ast
import subprocess
import sys
import warnings
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "mfethuls"
SERVER_ONLY = {"mfethuls_server", "sqlalchemy", "psycopg2", "fastapi", "uvicorn", "boto3", "botocore", "azure", "requests"}


def _imported_modules(path: Path):
    with warnings.catch_warnings():  # some parsers have regex strings with unescaped backslashes
        warnings.simplefilter("ignore", (DeprecationWarning, SyntaxWarning))
        tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_core_source_never_imports_server_packages():
    offending = [
        f"{path.relative_to(CORE.parent)}: {module}"
        for path in CORE.rglob("*.py")
        for module in _imported_modules(path)
        if module.split(".")[0] in SERVER_ONLY
    ]
    assert offending == []


def test_importing_the_core_loads_no_server_packages():
    modules = ["mfethuls", "mfethuls.stores", "mfethuls.reconcile", "mfethuls.discovery",
               "mfethuls.storage", "mfethuls.app.backend", "mfethuls.app.page"]
    code = (
        "import sys\n"
        + "".join(f"import {m}\n" for m in modules)
        + f"print(sorted(m for m in sys.modules if m.split('.')[0] in {sorted(SERVER_ONLY)!r}))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
