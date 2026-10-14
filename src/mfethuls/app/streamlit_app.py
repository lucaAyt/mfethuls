"""Streamlit entry script for the app on this computer (started by ``mfethuls-app``)."""

from mfethuls.app.backend import LocalBackend
from mfethuls.app.page import run

run(LocalBackend())
