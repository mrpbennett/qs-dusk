"""Configuration loading, validation, and atomic persistence.

Preferences live in `~/.config/omarchy/dusk/config.json`. Missing or malformed
files fall back to defaults; validation errors are returned as a list rather
than raising, so a bad edit can never invalidate the running schedule.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from . import paths

CONFIG_VERSION = 1

MODES = ("solar", "scheduled", "manual")

_TIME_RE = re.compile(r"^(?P<h>[01]\d|2[0-3]):(?P<m>[0-5]\d)$")


def defaults() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "mode": "scheduled",
        "lightTheme": None,
        "darkTheme": None,
        "manualTheme": "light",
        "scheduled": {"light": "07:00", "dark": "19:00"},
        "solar": {
            "sunriseOffsetMinutes": 0,
            "sunsetOffsetMinutes": 0,
            "fallback": {"light": "07:00", "dark": "19:00"},
        },
        "retryIntervalSeconds": 120,
        "maxRetries": 5,
    }


def validate_hm(value: Any) -> str | None:
    """Return a normalized `HH:MM` string, or an error message."""
    if not isinstance(value, str):
        return f"expected HH:MM string, got {value!r}"
    match = _TIME_RE.match(value)
    if not match:
        return f"invalid time {value!r} (expected HH:MM, 00:00-23:59)"
    return None


def validate_hm_pair(light: Any, dark: Any, where: str) -> list[str]:
    errors: list[str] = []
    for label, value in (("light", light), ("dark", dark)):
        err = validate_hm(value)
        if err:
            errors.append(f"{where}.{label}: {err}")
    if not errors and isinstance(light, str) and isinstance(dark, str) and light == dark:
        errors.append(f"{where}: light and dark transition times must differ")
    return errors


def validate_offset(value: Any, label: str) -> list[str]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [f"{label}: expected an integer number of minutes, got {value!r}"]
    if value < -720 or value > 720:
        return [f"{label}: offset {value} out of range (-720..720 minutes)"]
    return []


def validate_config(
    cfg: dict[str, Any],
    theme_available: Any | None = None,
) -> list[str]:
    """Validate a config dict, returning a list of human-readable errors.

    `theme_available` is an optional callable `slug -> bool` used to validate
    the selected themes against the installed theme list.
    """
    errors: list[str] = []

    mode = cfg.get("mode")
    if mode not in MODES:
        errors.append(f"mode must be one of {', '.join(MODES)}, got {mode!r}")

    for label in ("lightTheme", "darkTheme"):
        value = cfg.get(label)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label} must be a non-empty theme slug")
            continue
        if theme_available is not None and not theme_available(value):
            errors.append(f"{label}: theme {value!r} is not installed")

    if cfg.get("manualTheme") not in ("light", "dark"):
        errors.append(f"manualTheme must be 'light' or 'dark', got {cfg.get('manualTheme')!r}")

    scheduled = cfg.get("scheduled")
    if not isinstance(scheduled, dict):
        errors.append("scheduled must be an object with light and dark times")
    else:
        errors.extend(
            validate_hm_pair(
                scheduled.get("light"), scheduled.get("dark"), "scheduled"
            )
        )

    solar = cfg.get("solar")
    if not isinstance(solar, dict):
        errors.append("solar must be an object with offsets and fallback times")
    else:
        errors.extend(
            validate_offset(solar.get("sunriseOffsetMinutes"), "solar.sunriseOffsetMinutes")
        )
        errors.extend(
            validate_offset(solar.get("sunsetOffsetMinutes"), "solar.sunsetOffsetMinutes")
        )
        fallback = solar.get("fallback")
        if not isinstance(fallback, dict):
            errors.append("solar.fallback must be an object with light and dark times")
        else:
            errors.extend(
                validate_hm_pair(
                    fallback.get("light"), fallback.get("dark"), "solar.fallback"
                )
            )

    retry = cfg.get("retryIntervalSeconds")
    if not isinstance(retry, int) or retry <= 0:
        errors.append(f"retryIntervalSeconds must be a positive integer, got {retry!r}")
    max_retries = cfg.get("maxRetries")
    if not isinstance(max_retries, int) or max_retries < 0:
        errors.append(f"maxRetries must be a non-negative integer, got {max_retries!r}")

    return errors


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Any = None) -> tuple[dict[str, Any], str | None]:
    """Return `(config, load_warning)`. Never raises on missing/malformed files."""
    cfg = defaults()
    path = Path(path) if path is not None else paths.config_file()
    warning = None
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                cfg = _deep_merge(defaults(), raw)
            else:
                warning = f"config file {path} is not a JSON object; using defaults"
        except (OSError, ValueError) as exc:
            warning = f"could not read config file {path}: {exc}; using defaults"
    return cfg, warning


def save_config(cfg: dict[str, Any], path: Any = None) -> None:
    """Atomically write the config (temp file + rename)."""
    path = Path(path) if path is not None else paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".config-", dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise