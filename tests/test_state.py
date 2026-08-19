import tempfile
import unittest
from pathlib import Path

from dusk import state as state_mod
from dusk.omarchy import normalize_slug, weather_location
from tests import util  # noqa: F401


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_gives_defaults(self):
        s = state_mod.load_state(self.path)
        self.assertFalse(s["configured"])
        self.assertIsNone(s["nextTransition"])

    def test_malformed_gives_defaults(self):
        self.path.write_text("[]", encoding="utf-8")
        s = state_mod.load_state(self.path)
        self.assertFalse(s["configured"])

    def test_round_trip(self):
        s = state_mod.new_state()
        s["mode"] = "solar"
        s["appliedTheme"] = "catppuccin"
        s["nextTransition"] = "2026-08-19T20:22:00+01:00"
        state_mod.save_state(s, self.path)
        loaded = state_mod.load_state(self.path)
        self.assertEqual(loaded["mode"], "solar")
        self.assertEqual(loaded["appliedTheme"], "catppuccin")
        self.assertEqual(loaded["nextTransition"], "2026-08-19T20:22:00+01:00")


class NormalizeSlugTest(unittest.TestCase):
    def test_lowercase_and_spaces(self):
        self.assertEqual(normalize_slug("Catppuccin Latte"), "catppuccin-latte")

    def test_tags_removed(self):
        self.assertEqual(normalize_slug("Tokyo <Night>"), "tokyo-")

    def test_identity(self):
        self.assertEqual(normalize_slug("matte-black"), "matte-black")


class WeatherLocationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "weather.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        import json

        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_valid(self):
        self.write({"name": "Poole", "latitude": 50.71429, "longitude": -1.98458})
        self.assertEqual(weather_location(self.path), (50.71429, -1.98458))

    def test_missing(self):
        self.assertEqual(weather_location(self.path), None)

    def test_missing_coordinates(self):
        self.write({"name": "Poole"})
        self.assertEqual(weather_location(self.path), None)

    def test_invalid_types(self):
        self.write({"latitude": "abc", "longitude": 1.0})
        self.assertEqual(weather_location(self.path), None)

    def test_out_of_range(self):
        self.write({"latitude": 95.0, "longitude": 1.0})
        self.assertEqual(weather_location(self.path), None)

    def test_malformed(self):
        self.path.write_text("{nope", encoding="utf-8")
        self.assertEqual(weather_location(self.path), None)


if __name__ == "__main__":
    unittest.main()