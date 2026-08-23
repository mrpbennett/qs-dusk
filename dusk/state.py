"""Runtime state: one owner for the schema and every mutation rule.

State is separate from user preferences: it records what the scheduler last
observed and did, and must survive restarts so `status` is meaningful even
before the daemon recomputes.

:class:`DuskState` is an immutable record. All changes go through semantic
operations that return a new instance — callers never touch fields by name,
so the on-disk schema and the rules for how it evolves live here alone.
The wire format (camelCase JSON keys) is stable: `from_dict` tolerates
missing or unknown keys, so files written by other versions still load.
Written atomically; absent or malformed state falls back to safe defaults.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths
from .schedule import Decision

STATE_VERSION = 1

# Wire-format freeze: these JSON key names are consumed by the CLI and the
# bar widget's status document; they do not change.
_WIRE = {
    "version": "version",
    "configured": "configured",
    "mode": "mode",
    "desired_kind": "desiredKind",
    "desired_theme": "desiredTheme",
    "applied_theme": "appliedTheme",
    "current_theme": "currentTheme",
    "next_transition": "nextTransition",
    "next_transition_kind": "nextTransitionKind",
    "location": "location",
    "location_source": "locationSource",
    "solar_unavailable": "solarUnavailable",
    "last_error": "lastError",
    "last_success": "lastSuccess",
    "failures_since_success": "failuresSinceSuccess",
    "retry_theme": "retryTheme",
    "updated_at": "updatedAt",
}


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


@dataclass(frozen=True)
class DuskState:
    version: int = STATE_VERSION
    configured: bool = False
    mode: str = "scheduled"
    desired_kind: str | None = None
    desired_theme: str | None = None
    applied_theme: str | None = None
    current_theme: str | None = None
    next_transition: str | None = None
    next_transition_kind: str | None = None
    location: dict[str, float] | None = None
    location_source: str | None = None
    solar_unavailable: str | None = None
    last_error: str | None = None
    last_success: str | None = None
    failures_since_success: int = 0
    retry_theme: str | None = None
    updated_at: str | None = None

    # ---- wire format ------------------------------------------------------

    @classmethod
    def from_dict(cls, raw: Any) -> DuskState:
        field_by_wire = {wire: name for name, wire in _WIRE.items()}
        kwargs: dict[str, Any] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                name = field_by_wire.get(key)
                if name is not None:
                    kwargs[name] = value
        if not isinstance(kwargs.get("failures_since_success"), int):
            try:
                kwargs["failures_since_success"] = int(kwargs.get("failures_since_success", 0))
            except (TypeError, ValueError):
                kwargs["failures_since_success"] = 0
        return cls(**kwargs)

    def as_dict(self) -> dict[str, Any]:
        return {wire: getattr(self, name) for name, wire in _WIRE.items()}

    # ---- transitions ------------------------------------------------------

    def synced_from(
        self,
        decision: Decision,
        location: tuple[float, float] | None,
        now: datetime,
    ) -> DuskState:
        """Reflect a fresh Decision into this record."""
        clear_error = decision.ok or (not decision.configured and self.applied_theme is None)
        return dataclasses.replace(
            self,
            configured=decision.configured and decision.ok,
            mode=decision.mode,
            desired_kind=decision.desiredKind,
            desired_theme=decision.desiredTheme,
            next_transition=decision.nextTransition.isoformat() if decision.nextTransition else None,
            next_transition_kind=decision.nextTransitionKind,
            solar_unavailable=decision.solarUnavailable,
            location={"latitude": location[0], "longitude": location[1]} if location else None,
            location_source=decision.locationSource,
            last_error=None if clear_error else self.last_error,
            updated_at=_iso(now),
        )

    def observe_current(self, current: str | None) -> DuskState:
        """Record the currently observed Omarchy theme."""
        return dataclasses.replace(self, current_theme=current)

    def reset_retry_budget(self, desired: str) -> DuskState:
        """A failure belongs to one target theme; the next target gets its own budget."""
        return dataclasses.replace(self, failures_since_success=0, retry_theme=desired)

    def mark_no_op(self, desired: str) -> DuskState:
        """The desired theme is already active; nothing was applied."""
        return dataclasses.replace(
            self,
            applied_theme=desired,
            last_error=None,
            failures_since_success=0,
            retry_theme=None,
        )

    def record_apply(
        self,
        desired: str,
        ok: bool,
        detail: str | None,
        now: datetime,
    ) -> DuskState:
        """Record an `omarchy theme set` outcome."""
        if ok:
            return dataclasses.replace(
                self,
                applied_theme=desired,
                current_theme=desired,
                last_success=_iso(now),
                last_error=None,
                failures_since_success=0,
                retry_theme=None,
            )
        trimmed = ((detail or "").strip())[:400]
        return dataclasses.replace(
            self,
            failures_since_success=self.failures_since_success + 1,
            last_error=f"omarchy theme set {desired!r} failed: {trimmed}",
        )


def load_state(path: Any = None) -> DuskState:
    path = Path(path) if path is not None else paths.state_file()
    raw: Any = None
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            raw = None
    return DuskState.from_dict(raw)


def save_state(state: DuskState, path: Any = None) -> None:
    path = Path(path) if path is not None else paths.state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.as_dict(), fh, indent=2, sort_keys=True)
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
