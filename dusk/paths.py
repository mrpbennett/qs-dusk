"""Filesystem paths for Dusk.

Dusk keeps its preferences under Omarchy's config dir and its mutable runtime
state under Omarchy's state dir, using filenames that are distinct from any
file Omarchy manages itself. Omarchy-owned state is only ever read, never
written.
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(name: str, fallback: str) -> Path:
    value = os.environ.get(name)
    if value:
        return Path(value)
    return Path.home() / fallback


def _runtime_dir() -> Path:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    return Path("/tmp") / f"dusk-{os.getuid()}"


# Omarchy-owned output we observe (read-only).
def omarchy_state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "omarchy"


def omarchy_current_theme_file() -> Path:
    return omarchy_state_dir() / "current" / "theme.name"


def omarchy_weather_file() -> Path:
    return omarchy_state_dir() / "settings" / "weather.json"


# Dusk-owned files.
def config_file() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "omarchy" / "dusk" / "config.json"


def state_file() -> Path:
    return omarchy_state_dir() / "dusk" / "state.json"


def socket_path() -> Path:
    return _runtime_dir() / "dusk" / "control.sock"