"""Build the consumer-facing Status document from live domain data."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from . import schedule
from .state import DuskState


def document(
    state: DuskState,
    config: dict[str, Any],
    *,
    daemon_running: bool,
    config_warning: str | None = None,
    now: datetime | None = None,
    theme_available: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Project State and live Config into one stable consumer document."""
    projected = state.as_dict()
    if not daemon_running:
        now = now or datetime.now().astimezone()
        decision = schedule.resolve(
            config,
            now,
            now.tzinfo,
            None,
            theme_available=theme_available,
        )
        is_manual = decision.ok and config.get("mode") == "manual"
        projected.update(
            {
                "configured": decision.configured and decision.ok,
                "mode": config.get("mode"),
                "desiredKind": decision.desiredKind if is_manual else None,
                "desiredTheme": decision.desiredTheme if is_manual else None,
                "nextTransition": None,
                "nextTransitionKind": None,
                "location": None,
                "locationSource": None,
                "solarUnavailable": None,
            }
        )

    projected.update(
        {
            "daemonRunning": daemon_running,
            "lightTheme": config.get("lightTheme"),
            "darkTheme": config.get("darkTheme"),
            "configWarning": config_warning,
        }
    )
    return projected
