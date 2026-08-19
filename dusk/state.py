"""Runtime state persistence.

State is separate from user preferences: it records what the scheduler last
observed and did, and must survive restarts so `status` is meaningful even
before the daemon recomputes. Written atomically; absent or malformed state
falls back to safe defaults.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths

STATE_VERSION = 1


def new_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "configured": False,
        "mode": "scheduled",
        "desiredKind": None,
        "desiredTheme": None,
        "appliedTheme": None,
        "currentTheme": None,
        "nextTransition": None,
        "nextTransitionKind": None,
        "location": None,
        "locationSource": None,
        "solarUnavailable": None,
        "lastError": None,
        "lastSuccess": None,
        "failuresSinceSuccess": 0,
        "retryTheme": None,
        "updatedAt": None,
    }


def load_state(path: Any = None) -> dict[str, Any]:
    path = Path(path) if path is not None else paths.state_file()
    state = new_state()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                state.update(raw)
        except (OSError, ValueError):
            pass
    return state


def save_state(state: dict[str, Any], path: Any = None) -> None:
    path = Path(path) if path is not None else paths.state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
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
