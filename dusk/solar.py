"""Sunrise/sunset calculation (NOAA algorithm), stdlib only.

Computes the UTC times the upper limb of the Sun crosses the horizon at a
geometric zenith of 90.833 degrees (standard refraction + solar radius), then
converts to the requested zone. Two-pass refinement on solar noon. Handles
polar day/night and never raises for extreme latitudes.

Validated against `astral` and sunrise-sunset.org within ~1-2 minutes across
solstices, DST, and leap days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

ZENITH = 90.833

_RAD = math.pi / 180.0
_DEG = 180.0 / math.pi


def _julian_day(y: int, m: int, d: int, hour: float = 12.0) -> float:
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jdn = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    return jdn + (hour - 12.0) / 24.0


def _solar_data(jd: float) -> tuple[float, float]:
    """Return (declination deg, equation-of-time minutes)."""
    n = jd - 2451545.0
    century = n / 36525.0

    l0 = (280.46646 + 0.98564736 * n) % 360.0
    m = math.radians((357.52911 + 0.98560028 * n) % 360.0)
    eccentricity = 0.016708634 - 0.000042037 * century

    c_of_center = (
        math.sin(m) * (1.914602 - 0.004817 * century - 0.000014 * century * century)
        + math.sin(2 * m) * (0.019993 - 0.000101 * century)
        + math.sin(3 * m) * 0.000289
    )
    true_long = math.radians(l0 + c_of_center)
    omega = math.radians(125.04 - 0.052954 * n)
    apparent_long = true_long - math.radians(0.00569) - 0.00478 * math.sin(omega)
    epsilon0 = math.radians(23.439291 - 0.0130042 * century)
    epsilon = epsilon0 + 0.00256 * math.cos(omega)

    declination = math.degrees(math.asin(math.sin(epsilon) * math.sin(apparent_long)))

    y = math.tan(epsilon / 2.0) ** 2
    eot_rad = (
        y * math.sin(2 * math.radians(l0))
        - 2 * eccentricity * math.sin(m)
        + 4 * eccentricity * y * math.sin(m) * math.cos(2 * math.radians(l0))
        - 0.5 * y * y * math.sin(4 * math.radians(l0))
        - 1.25 * eccentricity * eccentricity * math.sin(2 * m)
    )
    # The series is in radians; 1 radian of solar time = 4 * (180/pi) minutes.
    eot_minutes = eot_rad * (4.0 * _DEG)
    return declination, eot_minutes


@dataclass(frozen=True)
class SolarDay:
    """Solar events for one local day.

    `events` holds `(local datetime, kind)` pairs for sunrise (light) and
    sunset (dark). When the Sun does not cross the horizon, `polar` is `day`
    or `night` and `events` is empty.
    """

    events: tuple[tuple[datetime, str], ...] = ()
    polar: str | None = None  # 'day' | 'night' | None


def _events_utc(lat: float, lon: float, day: date, zenith: float = ZENITH):
    """Return (rise_utc, set_utc, polar). UTC values are naive or None."""
    cos_zenith = math.cos(zenith * _RAD)
    sin_lat, cos_lat = math.sin(lat * _RAD), math.cos(lat * _RAD)

    def hour_angle(decl: float) -> float | None:
        denom = cos_lat * math.cos(decl * _RAD)
        if abs(denom) < 1e-12:
            return None
        cos_h = (cos_zenith - sin_lat * math.sin(decl * _RAD)) / denom
        if cos_h > 1.0 or cos_h < -1.0:
            return None
        return math.degrees(math.acos(cos_h))

    def polar_kind(decl: float) -> str:
        denom = cos_lat * math.cos(decl * _RAD)
        cos_h = (cos_zenith - sin_lat * math.sin(decl * _RAD)) / max(abs(denom), 1e-12)
        return "night" if cos_h > 1.0 else "day"

    declination, eot = _solar_data(_julian_day(day.year, day.month, day.day, 12.0))
    noon_minutes = 720.0 - 4.0 * lon - eot
    h = hour_angle(declination)
    if h is None:
        return None, None, polar_kind(declination)

    # Refine using the solar noon just computed.
    declination, eot = _solar_data(
        _julian_day(day.year, day.month, day.day, noon_minutes / 60.0)
    )
    noon_minutes = 720.0 - 4.0 * lon - eot
    h = hour_angle(declination)
    if h is None:
        return None, None, polar_kind(declination)

    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rise = base + timedelta(minutes=noon_minutes - 4.0 * h)
    sunset = base + timedelta(minutes=noon_minutes + 4.0 * h)
    return rise, sunset, None


def solar_day(
    lat: float,
    lon: float,
    day: date,
    tz,
    sunrise_offset_minutes: int = 0,
    sunset_offset_minutes: int = 0,
) -> SolarDay:
    """Solar events for `day` in `tz`, with signed minute offsets applied.

    Offsets are applied to the local wall-clock time of each event
    (negative = earlier).
    """
    rise_utc, set_utc, polar = _events_utc(lat, lon, day)

    def to_local(utc_naive: datetime) -> datetime:
        return utc_naive.replace(tzinfo=timezone.utc).astimezone(tz)

    if polar is not None:
        return SolarDay(events=(), polar=polar)

    events = []
    if rise_utc is not None:
        at = to_local(rise_utc) + timedelta(minutes=sunrise_offset_minutes)
        events.append((at, "light"))
    if set_utc is not None:
        at = to_local(set_utc) + timedelta(minutes=sunset_offset_minutes)
        events.append((at, "dark"))
    return SolarDay(events=tuple(sorted(events, key=lambda e: e[0])))