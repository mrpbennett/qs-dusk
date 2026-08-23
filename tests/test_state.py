import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dusk import state as state_mod
from dusk.omarchy import normalize_slug, weather_location
from dusk.schedule import Decision
from tests import util  # noqa: F401

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def decision(**overrides):
    return Decision(mode="scheduled", configured=True, **overrides)


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    # ---- persistence --------------------------------------------------

    def test_missing_gives_defaults(self):
        s = state_mod.load_state(self.path)
        self.assertFalse(s.configured)
        self.assertIsNone(s.next_transition)

    def test_malformed_gives_defaults(self):
        self.path.write_text("[]", encoding="utf-8")
        s = state_mod.load_state(self.path)
        self.assertFalse(s.configured)

    def test_corrupt_failures_coerced(self):
        self.path.write_text('{"failuresSinceSuccess": "many"}', encoding="utf-8")
        s = state_mod.load_state(self.path)
        self.assertEqual(s.failures_since_success, 0)

    def test_unknown_keys_ignored_and_missing_keys_defaulted(self):
        self.path.write_text('{"appliedTheme": "catppuccin", "futureKey": 1}', encoding="utf-8")
        s = state_mod.load_state(self.path)
        self.assertEqual(s.applied_theme, "catppuccin")

    def test_round_trip_preserves_wire_keys(self):
        s = state_mod.DuskState(mode="solar", applied_theme="catppuccin",
                                next_transition="2026-08-19T20:22:00+01:00")
        state_mod.save_state(s, self.path)
        loaded = state_mod.load_state(self.path)
        self.assertEqual(loaded.mode, "solar")
        self.assertEqual(loaded.applied_theme, "catppuccin")
        self.assertEqual(loaded.next_transition, "2026-08-19T20:22:00+01:00")
        raw = __import__("json").loads(self.path.read_text())
        self.assertIn("appliedTheme", raw)  # wire format unchanged

    def test_as_dict_uses_wire_names(self):
        d = state_mod.DuskState(desired_theme="catppuccin").as_dict()
        self.assertEqual(d["desiredTheme"], "catppuccin")
        self.assertNotIn("desired_theme", d)

    # ---- synced_from ---------------------------------------------------

    def test_synced_from_reflects_decision(self):
        nxt = datetime(2026, 8, 19, 19, 0, tzinfo=timezone.utc)
        s = state_mod.DuskState().synced_from(
            decision(desiredTheme="catppuccin", desiredKind="dark", nextTransition=nxt,
                     nextTransitionKind="dark"),
            (50.7, -1.98), NOW,
        )
        self.assertTrue(s.configured)
        self.assertEqual(s.desired_theme, "catppuccin")
        self.assertEqual(s.next_transition, "2026-08-19T19:00:00+00:00")
        self.assertEqual(s.location, {"latitude": 50.7, "longitude": -1.98})
        self.assertEqual(s.updated_at, NOW.isoformat())

    def test_synced_from_clears_error_when_ok(self):
        s = state_mod.DuskState(last_error="boom")
        self.assertIsNone(s.synced_from(decision(), None, NOW).last_error)

    def test_synced_from_keeps_error_while_failing(self):
        s = state_mod.DuskState(last_error="boom", applied_theme="catppuccin")
        bad = decision(errors=["invalid schedule"])
        self.assertEqual(s.synced_from(bad, None, NOW).last_error, "boom")

    def test_synced_from_no_location(self):
        s = state_mod.DuskState(location={"latitude": 1.0, "longitude": 2.0})
        self.assertIsNone(s.synced_from(decision(), None, NOW).location)

    # ---- apply transitions ---------------------------------------------

    def test_reset_retry_budget(self):
        s = state_mod.DuskState(failures_since_success=3)
        s2 = s.reset_retry_budget("catppuccin")
        self.assertEqual((s2.failures_since_success, s2.retry_theme), (0, "catppuccin"))
        self.assertEqual(s.failures_since_success, 3)  # immutable

    def test_mark_no_op_clears_failure_bookkeeping(self):
        s = state_mod.DuskState(failures_since_success=4, retry_theme="gruvbox", last_error="boom")
        s2 = s.mark_no_op("catppuccin")
        self.assertEqual(s2.applied_theme, "catppuccin")
        self.assertIsNone(s2.last_error)
        self.assertEqual(s2.failures_since_success, 0)
        self.assertIsNone(s2.retry_theme)

    def test_record_apply_success(self):
        s = state_mod.DuskState().record_apply("catppuccin", True, None, NOW)
        self.assertEqual(s.applied_theme, "catppuccin")
        self.assertEqual(s.current_theme, "catppuccin")
        self.assertEqual(s.last_success, NOW.isoformat())
        self.assertIsNone(s.last_error)
        self.assertEqual(s.failures_since_success, 0)

    def test_record_apply_failure_truncates_detail(self):
        s = state_mod.DuskState().record_apply("catppuccin", False, "x" * 500, NOW)
        self.assertEqual(s.failures_since_success, 1)
        self.assertLessEqual(len(s.last_error), len("omarchy theme set 'catppuccin' failed: ") + 400)
        self.assertIn("'catppuccin'", s.last_error)

    def test_record_apply_failure_strips_whitespace(self):
        s = state_mod.DuskState().record_apply("catppuccin", False, "  boom  \n", NOW)
        self.assertTrue(s.last_error.endswith("boom"))

    def test_ops_return_new_instances(self):
        s = state_mod.DuskState()
        s2 = s.mark_no_op("catppuccin")
        self.assertIsNot(s, s2)
        self.assertIsNone(s.applied_theme)


LIGHT = "catppuccin-latte"


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
