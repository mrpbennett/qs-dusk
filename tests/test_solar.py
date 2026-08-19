import unittest
from datetime import date
from zoneinfo import ZoneInfo

from dusk import solar
from tests import util  # noqa: F401


class SolarEventsTest(unittest.TestCase):
    tz = ZoneInfo("Europe/London")

    def test_pool_summer(self):
        day = solar.solar_day(50.71429, -1.98458, date(2026, 8, 19), self.tz)
        self.assertIsNone(day.polar)
        self.assertEqual(len(day.events), 2)
        rise, kind_light = day.events[0]
        sunset, kind_dark = day.events[1]
        self.assertEqual(kind_light, "light")
        self.assertEqual(kind_dark, "dark")
        # Sunrise ~06:02 BST, sunset ~20:21 BST (validated vs astral).
        self.assertAlmostEqual(rise.hour * 60 + rise.minute, 6 * 60 + 2, delta=3)
        self.assertAlmostEqual(sunset.hour * 60 + sunset.minute, 20 * 60 + 21, delta=3)

    def test_pool_winter(self):
        day = solar.solar_day(50.71429, -1.98458, date(2026, 1, 15), self.tz)
        self.assertEqual(len(day.events), 2)
        rise, kind = day.events[0]
        self.assertEqual(kind, "light")
        self.assertAlmostEqual(rise.hour * 60 + rise.minute, 8 * 60 + 4, delta=3)

    def test_leap_day(self):
        day = solar.solar_day(50.71429, -1.98458, date(2024, 2, 29), self.tz)
        self.assertEqual(len(day.events), 2)

    def test_dst_transition_day(self):
        day = solar.solar_day(50.71429, -1.98458, date(2026, 3, 29), self.tz)
        self.assertEqual(len(day.events), 2)
        for at, _kind in day.events:
            self.assertIsNotNone(at.tzinfo)

    def test_polar_day(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        day = solar.solar_day(78.2232, 15.6469, date(2026, 6, 21), tz)
        self.assertEqual(day.polar, "day")
        self.assertEqual(day.events, ())

    def test_polar_night(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        day = solar.solar_day(78.2232, 15.6469, date(2026, 12, 21), tz)
        self.assertEqual(day.polar, "night")
        self.assertEqual(day.events, ())

    def test_offsets(self):
        base = solar.solar_day(50.71429, -1.98458, date(2026, 8, 19), self.tz)
        shifted = solar.solar_day(
            50.71429,
            -1.98458,
            date(2026, 8, 19),
            self.tz,
            sunrise_offset_minutes=30,
            sunset_offset_minutes=-20,
        )
        rise_before, _ = base.events[0]
        rise_after, _ = shifted.events[0]
        set_before, _ = base.events[1]
        set_after, _ = shifted.events[1]
        self.assertEqual((rise_after - rise_before).total_seconds(), 30 * 60)
        self.assertEqual((set_after - set_before).total_seconds(), -20 * 60)

    def test_southern_hemisphere(self):
        tz = ZoneInfo("Australia/Sydney")
        day = solar.solar_day(-33.8688, 151.2093, date(2026, 6, 21), tz)
        self.assertEqual(len(day.events), 2)
        rise, kind = day.events[0]
        self.assertEqual(kind, "light")
        self.assertTrue(6 <= rise.hour <= 8)  # Sydney winter sunrise


if __name__ == "__main__":
    unittest.main()