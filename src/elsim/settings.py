"""Loads the settings file from the project root (the current directory):
config/settings.toml, or the file named by the ELSIM_SETTINGS environment
variable (for example config/settings_eurocup.toml)."""

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # the test environment runs Python 3.10
    import tomli as tomllib


def load() -> dict:
    with open(Path(os.environ.get("ELSIM_SETTINGS", "config/settings.toml")), "rb") as f:
        return tomllib.load(f)
