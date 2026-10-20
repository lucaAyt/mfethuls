"""The app's accent colour, for buttons, toggles and the progress bar, and its fixed look.

Streamlit's own accent is red, which new users read as "something went wrong",
so the app starts in a calm teal; ⚙ Settings → Appearance offers a few others.
The choice is saved for this computer in ``appearance.json`` next to the saved
settings (see :func:`mfethuls.settings.settings_file`).
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List

from mfethuls.settings import settings_file

logger = logging.getLogger(__name__)

ACCENTS: Dict[str, str] = {
    "Teal": "#0E9384",
    "Blue": "#2563EB",
    "Violet": "#7C5CDB",
    "Green": "#2F855A",
    "Red (Streamlit's own)": "#FF4B4B",
}
DEFAULT_ACCENT = "Teal"


def appearance_file():
    return settings_file().with_name("appearance.json")


def saved_accent() -> str:
    """The chosen accent's name (the default when none was chosen or the file is unreadable)."""
    try:
        name = json.loads(appearance_file().read_text(encoding="utf-8")).get("accent")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_ACCENT
    return name if name in ACCENTS else DEFAULT_ACCENT


def save_accent(name: str) -> None:
    from mfethuls._files import replace_with_retry

    if name not in ACCENTS:
        raise ValueError(f"Unknown accent {name!r}; choose one of {', '.join(ACCENTS)}.")
    path = appearance_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"accent": name}, indent=2), encoding="utf-8")
    replace_with_retry(str(temp), str(path))


# Set for the light and the dark theme separately: a plain ``theme.primaryColor`` makes
# Streamlit treat the theme as custom and drops its Light / Dark choice.
THEME_OPTIONS = ("theme.light.primaryColor", "theme.dark.primaryColor")

# The same for every accent. No developer menu (Deploy, Rerun, Clear cache), which
# confused new users; and text a little larger than Streamlit's 16 px root (labels,
# buttons and captions are 0.875 rem, so 15 px instead of 14 px). The Light / Dark
# choice stays: Streamlit has no font size per theme, but this one does not drop it.
FIXED_OPTIONS: Dict[str, object] = {
    "client.toolbarMode": "viewer",
    "theme.baseFontSize": 17,
}

# Captions are drawn at 60 % opacity, about 3.5:1 on white: too faint for the hints new
# users rely on. At 80 % they are about 6.5:1, still lighter than body text. No theme
# option sets this, hence the one style rule.
# Text areas say "Press Ctrl+Enter to apply" in small print few notice; the app gives them a
# button instead (the text is taken when the box loses focus, e.g. when the button is pressed).
STYLE = ("<style>[data-testid='stCaptionContainer'] { opacity: 0.8; }"
         " [data-testid='stTextArea'] [data-testid='InputInstructions'] { display: none; }</style>")


def _options() -> Dict[str, object]:
    colour = ACCENTS[saved_accent()]
    return {**{option: colour for option in THEME_OPTIONS}, **FIXED_OPTIONS}


def theme_args() -> List[str]:
    """``streamlit run`` options that start the app in the saved accent, without the developer menu."""
    return [f"--{option}={value}" for option, value in _options().items()]


def apply_appearance() -> None:
    """Use the saved accent from the next rerun on (Streamlit sends the theme when a run starts)."""
    from streamlit import config

    for option, value in _options().items():
        if config.get_option(option) != value:
            config.set_option(option, value)


def apply_style() -> None:
    """Add :data:`STYLE` to the page (call once per run)."""
    import streamlit as st

    st.html(STYLE)
