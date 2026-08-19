import json
import tempfile
import unittest
from pathlib import Path

from dusk import config as config_mod
from tests import util  # noqa: F401


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_gives_defaults(self):
        cfg, warning = config_mod.load_config(self.path)
        self.assertIsNone(warning)
        self.assertEqual(cfg["mode"], "scheduled")
        self.assertIsNone(cfg["lightTheme"])

    def test_malformed_file_gives_defaults_and_warning(self):
        self.path.write_text("{not json", encoding="utf-8")
        cfg, warning = config_mod.load_config(self.path)
        self.assertIsNotNone(warning)
        self.assertEqual(cfg["mode"], "scheduled")

    def test_round_trip(self):
        cfg = config_mod.defaults()
        cfg["mode"] = "solar"
        cfg["lightTheme"] = "catppuccin-latte"
        cfg["solar"]["sunriseOffsetMinutes"] = -15
        config_mod.save_config(cfg, self.path)
        loaded, warning = config_mod.load_config(self.path)
        self.assertIsNone(warning)
        self.assertEqual(loaded["mode"], "solar")
        self.assertEqual(loaded["lightTheme"], "catppuccin-latte")
        self.assertEqual(loaded["solar"]["sunriseOffsetMinutes"], -15)

    def test_user_fields_survive_default_merge(self):
        self.path.write_text(
            json.dumps({"mode": "manual", "customField": {"x": 1}}), encoding="utf-8"
        )
        cfg, _ = config_mod.load_config(self.path)
        self.assertEqual(cfg["mode"], "manual")
        self.assertEqual(cfg["customField"]["x"], 1)
        self.assertEqual(cfg["scheduled"]["light"], "07:00")  # default preserved

    def test_validation_equal_times(self):
        cfg = config_mod.defaults()
        cfg["scheduled"] = {"light": "07:00", "dark": "07:00"}
        errors = config_mod.validate_config(cfg)
        self.assertTrue(any("must differ" in e for e in errors))

    def test_validation_bad_time(self):
        cfg = config_mod.defaults()
        cfg["scheduled"] = {"light": "25:00", "dark": "19:00"}
        errors = config_mod.validate_config(cfg)
        self.assertTrue(any("invalid time" in e for e in errors))

    def test_validation_offset_range(self):
        cfg = config_mod.defaults()
        cfg["solar"]["sunriseOffsetMinutes"] = 9999
        errors = config_mod.validate_config(cfg)
        self.assertTrue(any("out of range" in e for e in errors))

    def test_validation_theme_availability(self):
        cfg = config_mod.defaults()
        cfg["lightTheme"] = "nope"
        errors = config_mod.validate_config(cfg, theme_available=lambda s: False)
        self.assertTrue(any("not installed" in e for e in errors))

    def test_validation_bad_mode(self):
        cfg = config_mod.defaults()
        cfg["mode"] = "twilight"
        errors = config_mod.validate_config(cfg)
        self.assertTrue(any("mode" in e for e in errors))


if __name__ == "__main__":
    unittest.main()