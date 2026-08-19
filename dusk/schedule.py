"""Scheduling decision engine.

Pure logic: given a config, a clock, a zone, a location, and a theme
availability check, decide which theme should be active, the next transition,
and whether a scheduled fallback is in use. No side effects here — the daemon
owns applying decisions.

Events are `(datetime, kind)` pairs (`kind` is `light` or `dark`). The active
theme is the target of the most recent event `<= now` across yesterday and
today; the next transition is the earliest event `> now` across today and
tomorrow. A polar day/night with no events is modelled as a marker at local
midnight of the appropriate kind.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from . import config, solar

Event = tuple[datetime, str]

_TIME_RE = re.compile(r"^(?P<h>[01]\d|2[0-3]):(?P<m>[0-5]\d)$")


class SolarUnavailable(Exception):
    """Raised when solar data cannot be computed for the given inputs."""


def parse_hm(value: str) -> time:
    match = _TIME_RE.match(value)
    if not match:
        raise ValueError(f"invalid time {value!r} (expected HH:MM)")
    return time(int(match.group("h")), int(match.group("m")))


def scheduled_events(day: date, light_hm: str, dark_hm: str, tz) -> list[Event]:
    light = datetime.combine(day, parse_hm(light_hm), tzinfo=tz)
    dark = datetime.combine(day, parse_hm(dark_hm), tzinfo=tz)
    return [(light, "light"), (dark, "dark")]


def _resolve_solar(
    lat: float,
    lon: float,
    solar_cfg: dict[str, Any],
    now: datetime,
    tz,
) -> tuple[str | None, Event | None]:
    """Active kind + next real transition from solar events for 3 local days.

    Polar days/nights carry no sunrise/sunset event, so they cannot move the
    next transition; they only pin the active kind (via a midnight marker).
    """
    candidates: list[Event] = []  # for the active state
    transitions: list[Event] = []  # real sunrise/sunset, for the next event
    for offset in (-1, 0, 1):
        day = now.date() + timedelta(days=offset)
        solar_day = solar.solar_day(
            lat,
            lon,
            day,
            tz,
            sunrise_offset_minutes=solar_cfg.get("sunriseOffsetMinutes", 0),
            sunset_offset_minutes=solar_cfg.get("sunsetOffsetMinutes", 0),
        )
        if solar_day.polar is not None:
            kind = "light" if solar_day.polar == "day" else "dark"
            candidates.append((datetime.combine(day, time(0, 0), tzinfo=tz), kind))
        else:
            candidates.extend(solar_day.events)
            transitions.extend(solar_day.events)

    before = [e for e in candidates if e[0] <= now]
    active = max(before, key=lambda e: e[0]) if before else None
    after = [e for e in transitions if e[0] > now]
    nxt = min(after, key=lambda e: e[0]) if after else None
    return (active[1] if active else None), nxt


def resolve_active_and_next(
    events: dict[date, list[Event]], now: datetime
) -> tuple[str | None, Event | None]:
    """Active kind + next event given per-day event lists for 3 consecutive days."""
    dates = sorted(events)
    before: list[Event] = []
    after: list[Event] = []
    for day in dates:
        for ev in events[day]:
            if ev[0] <= now:
                before.append(ev)
            else:
                after.append(ev)
    active = max(before, key=lambda ev: ev[0]) if before else None
    nxt = min(after, key=lambda ev: ev[0]) if after else None
    return (active[1] if active else None), nxt


@dataclass
class Decision:
    """Result of resolving the schedule at a point in time."""

    mode: str
    configured: bool = False
    desiredTheme: str | None = None
    desiredKind: str | None = None
    nextTransition: datetime | None = None
    nextTransitionKind: str | None = None
    locationSource: str | None = None
    solarUnavailable: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _resolve_events(
    cfg: dict[str, Any],
    now: datetime,
    tz,
    location: tuple[float, float] | None,
) -> tuple[str | None, Event | None, str | None, str | None]:
    """Return (active_kind, next_event, location_source, solar_unavailable)."""
    mode = cfg.get("mode", "scheduled")

    if mode == "scheduled":
        scheduled = cfg.get("scheduled", {})
        light, dark = scheduled.get("light", "07:00"), scheduled.get("dark", "19:00")
        events = {
            day: scheduled_events(day, light, dark, tz)
            for day in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1))
        }
        active, nxt = resolve_active_and_next(events, now)
        return active, nxt, None, None

    if mode == "manual":
        return None, None, None, None

    # Solar mode.
    if location is None:
        return _fallback_events(cfg, now, tz, "weather coordinates unavailable")

    lat, lon = location
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return _fallback_events(cfg, now, tz, "invalid weather coordinates")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return _fallback_events(cfg, now, tz, "weather coordinates out of range")

    solar_cfg = cfg.get("solar", {})
    try:
        active, nxt = _resolve_solar(lat, lon, solar_cfg, now, tz)
    except Exception as exc:  # noqa: BLE001 - any solar failure uses the fallback
        return _fallback_events(cfg, now, tz, f"solar calculation failed: {exc}")

    return active, nxt, "weather", None


def _fallback_events(
    cfg: dict[str, Any], now: datetime, tz, reason: str
) -> tuple[str | None, Event | None, str | None, str]:
    fallback = cfg.get("solar", {}).get("fallback", {})
    light, dark = fallback.get("light", "07:00"), fallback.get("dark", "19:00")
    events = {
        day: scheduled_events(day, light, dark, tz)
        for day in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1))
    }
    active, nxt = resolve_active_and_next(events, now)
    return active, nxt, None, reason


def resolve(
    cfg: dict[str, Any],
    now: datetime,
    tz,
    location: tuple[float, float] | None,
    theme_available: Callable[[str], bool] | None = None,
) -> Decision:
    """Resolve the schedule at `now`. Pure — performs no I/O."""
    errors = config.validate_config(cfg, theme_available=theme_available)
    decision = Decision(mode=cfg.get("mode", "scheduled"), errors=list(errors))

    if errors:
        return decision

    light_theme = cfg.get("lightTheme")
    dark_theme = cfg.get("darkTheme")
    if not light_theme or not dark_theme:
        decision.configured = False
        return decision

    decision.configured = True
    mode = cfg.get("mode")

    if mode == "manual":
        kind = cfg.get("manualTheme", "light")
        decision.desiredKind = kind
        decision.desiredTheme = light_theme if kind == "light" else dark_theme
        return decision

    active_kind, nxt, location_source, solar_reason = _resolve_events(cfg, now, tz, location)
    decision.locationSource = location_source
    decision.solarUnavailable = solar_reason

    if active_kind is None:
        # Should not happen for valid event schedules; keep last state safe.
        decision.errors = ["could not determine active theme"]
        return decision

    decision.desiredKind = active_kind
    decision.desiredTheme = light_theme if active_kind == "light" else dark_theme
    if nxt is not None:
        decision.nextTransition, decision.nextTransitionKind = nxt
    return decision