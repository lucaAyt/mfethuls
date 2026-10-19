"""Regular expressions from instrument definitions: checked when loaded, run with a time limit.

Definitions are written by chatbots, colleagues and people pasting text, so their
patterns are untrusted input. A pattern can be valid and still take minutes or
days on a line it almost matches (catastrophic backtracking, e.g. ``(\\w+\\s?)+:``),
which would freeze ingest without an error. So:

- :func:`problem` refuses, when a definition is loaded, patterns that are too long
  or repeat a part that itself repeats (the usual cause);
- :func:`search` runs every pattern with the :mod:`regex` engine and a time limit,
  raising :class:`PatternError` instead of hanging.

Every definition pattern must go through this module (``tests/test_patterns.py``
checks that no other module calls ``re`` with a pattern that is not written in the code).
"""

from __future__ import annotations

import re
from functools import lru_cache
from re import _constants as _sre  # the standard library's pattern parser, only for the shape check
from re import _parser as _sre_parse
from typing import Optional

import regex

MAX_LENGTH = 300
# Seconds one search may take. Searching one line normally takes microseconds.
TIMEOUT_S = 0.5
# In ``from_header`` patterns of workbooks: the name of each test sheet.
SHEET_PLACEHOLDER = "{sheet}"

_REPEATS = (_sre.MAX_REPEAT, _sre.MIN_REPEAT)
# Patterns that took too long once fail at once afterwards (not once per file).
_too_slow: set = set()


class PatternError(ValueError):
    """A definition's pattern took too long on a line of a file."""


def problem(pattern, *, groups: int = 0) -> Optional[str]:
    """Why ``pattern`` cannot be used in a definition (to follow its key's name), or None.

    ``groups``: how many groups ``( ... )`` the pattern needs at least.
    """
    if not isinstance(pattern, str) or not pattern:
        return "must be a regular expression"
    if len(pattern) > MAX_LENGTH:
        return f"is longer than {MAX_LENGTH} characters; keep patterns short"
    text = pattern.replace(SHEET_PLACEHOLDER, "x")
    try:
        parsed = _sre_parse.parse(text)
        compiled = _compile(text, 0)
    except (re.error, regex.error) as exc:
        return f"is not a valid regular expression ({exc})"
    if compiled.groups < groups:
        return "needs a group ( ... ) around the part to keep"
    if _nested_repeat(parsed.data, inside=False):
        return ("repeats a part that itself repeats, like (\\w+\\s?)+, which can take hours on some lines; "
                "repeat a single character class instead, like [\\w\\s]+")
    return None


def groups(pattern: str) -> int:
    """Number of groups in a checked pattern."""
    return _compile(pattern.replace(SHEET_PLACEHOLDER, "x"), 0).groups


def search(pattern: str, text: str, *, ignore_case: bool = False) -> Optional[regex.Match]:
    """``pattern`` searched in ``text``, giving up after :data:`TIMEOUT_S` seconds."""
    if pattern in _too_slow:
        raise PatternError(_slow_message(pattern))
    try:
        return _compile(pattern, regex.IGNORECASE if ignore_case else 0).search(text, timeout=TIMEOUT_S)
    except TimeoutError:
        _too_slow.add(pattern)
        raise PatternError(f"{_slow_message(pattern)} (on the text {text[:60]!r})") from None


def _slow_message(pattern: str) -> str:
    return (f"the pattern {pattern!r} took longer than {TIMEOUT_S} s to search one line; "
            "simplify it in the instrument definition")


@lru_cache(maxsize=512)
def _compile(pattern: str, flags: int) -> regex.Pattern:
    return regex.compile(pattern, flags)


def _nested_repeat(items, *, inside: bool) -> bool:
    """A repeat of variable length inside a repeat of variable length (``inside``: within one already)."""
    for op, av in items:
        if op in _REPEATS:
            low, high, sub = av
            variable = low != high
            if variable and inside:
                return True
            if _nested_repeat(sub, inside=inside or (variable and high > 1)):
                return True
        elif op == _sre.SUBPATTERN:
            if _nested_repeat(av[3], inside=inside):
                return True
        elif op == _sre.BRANCH:
            if any(_nested_repeat(branch, inside=inside) for branch in av[1]):
                return True
        elif op in (_sre.ASSERT, _sre.ASSERT_NOT):
            if _nested_repeat(av[1], inside=inside):
                return True
        elif op == _sre.GROUPREF_EXISTS:
            if any(_nested_repeat(branch, inside=inside) for branch in av[1:] if branch is not None):
                return True
        # Atomic groups and possessive repeats (``(?>...)``, ``a++``) never backtrack: not checked.
    return False
