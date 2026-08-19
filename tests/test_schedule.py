import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from dusk import schedule
from tests import util  # noqa: F401

LIGHT = "catppuccin-latte"
DARK = "catppuccin"


def cfg(mode="scheduled", **overrides):
    from dusk import config as config_mod

    c = config_mod.defaults()
    c["lightTheme"] = LIGHT
    c["darkTheme"] = DARK
    c["mode"] = mode
    c.update(overrides)
    return c


def now_local(y, m, d, hh, mm, tz):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def resolve(c, n, tz=None, location=None, theme_available=None):
    return schedule.resolve(
        c, n, tz or ZoneInfo("Europe/London"), location, theme_available=theme_available
    )


def always(slug):
    return True


class ScheduledModeTest(unittest.TestCase):
    tz = ZoneInfo("Europe/London")

    def setUp(self):
        self.c = cfg("scheduled", scheduled={"light": "07:00", "dark": "19:00"})

    def test_before_first_transition(self):
        d = resolve(self.c, now_local(2026, 8, 19, 6, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(d.desiredKind, "dark")
        self.assertEqual(d.desiredTheme, DARK)
        self.assertEqual(d.nextTransitionKind, "light")
        self.assertEqual(d.nextTransition.hour, 7)

    def test_between_transitions(self):
        d = resolve(self.c, now_local(2026, 8, 19, 10, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(d.desiredKind, "light")
        self.assertEqual(d.nextTransitionKind, "dark")
        self.assertEqual(d.nextTransition.hour, 19)

    def test_after_dark(self):
        d = resolve(self.c, now_local(2026, 8, 19, 20, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(d.desiredKind, "dark")
        self.assertEqual(d.nextTransitionKind, "light")
        self.assertEqual(d.nextTransition.date().day, 20)  # tomorrow

    def test_midnight_crossing_schedule(self):
        c = cfg("scheduled", scheduled={"light": "20:00", "dark": "07:00"})
        # Dark engages at 07:00, light at 20:00 (chronological).
        at_5 = resolve(c, now_local(2026, 8, 19, 5, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(at_5.desiredKind, "light")
        self.assertEqual(at_5.nextTransitionKind, "dark")
        at_10 = resolve(c, now_local(2026, 8, 19, 10, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(at_10.desiredKind, "dark")
        self.assertEqual(at_10.nextTransitionKind, "light")
        at_22 = resolve(c, now_local(2026, 8, 19, 22, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(at_22.desiredKind, "light")
        self.assertEqual(at_22.nextTransition.date().day, 20)  # tomorrow 07:00 dark

    def test_equal_times_rejected(self):
        c = cfg("scheduled", scheduled={"light": "07:00", "dark": "07:00"})
        d = resolve(c, now_local(2026, 8, 19, 10, 0, self.tz), self.tz, theme_available=always)
        self.assertFalse(d.ok)
        self.assertFalse(d.configured)


class SolarModeTest(unittest.TestCase):
    tz = ZoneInfo("Europe/London")

    def setUp(self):
        self.c = cfg("solar")
        self.location = (50.71429, -1.98458)

    def test_daytime_light(self):
        d = resolve(self.c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, self.location, theme_available=always)
        self.assertEqual(d.desiredKind, "light")
        self.assertEqual(d.nextTransitionKind, "dark")
        self.assertEqual(d.locationSource, "weather")

    def test_night_dark(self):
        d = resolve(self.c, now_local(2026, 8, 19, 23, 0, self.tz), self.tz, self.location, theme_available=always)
        self.assertEqual(d.desiredKind, "dark")
        self.assertEqual(d.nextTransitionKind, "light")

    def test_sunrise_offset_shifts_transition(self):
        c = cfg("solar", solar={**self.c["solar"], "sunriseOffsetMinutes": 60, "sunsetOffsetMinutes": 0})
        base = resolve(self.c, now_local(2026, 8, 19, 7, 0, self.tz), self.tz, self.location, theme_available=always)
        shifted = resolve(c, now_local(2026, 8, 19, 7, 0, self.tz), self.tz, self.location, theme_available=always)
        self.assertEqual(base.desiredKind, "light")
        self.assertEqual(shifted.desiredKind, "dark")  # +60 min moves sunrise past 07:00

    def test_no_location_uses_fallback(self):
        d = resolve(self.c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, None, theme_available=always)
        self.assertIsNotNone(d.solarUnavailable)
        self.assertIn("coordinates", d.solarUnavailable)
        self.assertEqual(d.desiredKind, "light")
        self.assertEqual(d.nextTransitionKind, "dark")
        self.assertEqual(d.locationSource, None)

    def test_polar_day_active_light(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        d = resolve(self.c, datetime(2026, 6, 21, 12, 0, tzinfo=tz), tz, (78.2232, 15.6469), theme_available=always)
        self.assertEqual(d.desiredKind, "light")
        self.assertEqual(d.nextTransition, None)

    def test_polar_night_active_dark(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        d = resolve(self.c, datetime(2026, 12, 21, 12, 0, tzinfo=tz), tz, (78.2232, 15.6469), theme_available=always)
        self.assertEqual(d.desiredKind, "dark")
        self.assertEqual(d.nextTransition, None)

    def test_invalid_location_falls_back(self):
        d = resolve(self.c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, (999.0, -1.0), theme_available=always)
        self.assertIsNotNone(d.solarUnavailable)
        self.assertEqual(d.desiredKind, "light")  # fallback schedule still resolves


class ManualAndConfigTest(unittest.TestCase):
    tz = ZoneInfo("Europe/London")

    def test_manual_light(self):
        c = cfg("manual", manualTheme="light")
        d = resolve(c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(d.desiredTheme, LIGHT)
        self.assertEqual(d.nextTransition, None)

    def test_manual_dark(self):
        c = cfg("manual", manualTheme="dark")
        d = resolve(c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, theme_available=always)
        self.assertEqual(d.desiredTheme, DARK)

    def test_unconfigured_themes(self):
        c = cfg("scheduled")
        c["lightTheme"] = None
        c["darkTheme"] = None
        d = resolve(c, now_local(2026, 8, 19, 12, 0, self.tz), self.tz, theme_available=always)
        self.assertFalse(d.configured)
        self.assertIsNone(d.desiredTheme)

    def test_invalid_theme_slug(self):
        def available(slug):
            return False

        d = resolve(self._c(), now_local(2026, 8, 19, 12, 0, self.tz), self.tz, theme_available=available)
        self.assertFalse(d.ok)

    def _c(self):
        return cfg("scheduled", scheduled={"light": "07:00", "dark": "19:00"})


if __name__ == "__main__":
    unittest.main()