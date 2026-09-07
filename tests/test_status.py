import unittest
from datetime import datetime, timezone

from dusk import config as config_mod
from dusk import state as state_mod
from dusk import status
from tests import util  # noqa: F401

LIGHT = "catppuccin-latte"
DARK = "catppuccin"
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def configured(mode="scheduled"):
    cfg = config_mod.defaults()
    cfg.update({"mode": mode, "lightTheme": LIGHT, "darkTheme": DARK})
    return cfg


class StatusDocumentTest(unittest.TestCase):
    def test_live_document_projects_state_config_and_liveness(self):
        state = state_mod.DuskState(
            configured=True,
            mode="scheduled",
            desired_kind="light",
            desired_theme=LIGHT,
        )

        document = status.document(state, configured(), daemon_running=True)

        self.assertTrue(document["daemonRunning"])
        self.assertEqual(document["desiredTheme"], LIGHT)
        self.assertEqual(document["lightTheme"], LIGHT)
        self.assertEqual(document["darkTheme"], DARK)
        self.assertIn("failuresSinceSuccess", document)

    def test_offline_manual_document_uses_live_config(self):
        state = state_mod.DuskState(
            configured=True,
            mode="scheduled",
            desired_kind="light",
            desired_theme=LIGHT,
            next_transition="2026-09-07T19:00:00+00:00",
        )
        cfg = configured("manual")
        cfg["manualTheme"] = "dark"

        document = status.document(
            state,
            cfg,
            daemon_running=False,
            now=NOW,
            theme_available=lambda _slug: True,
        )

        self.assertFalse(document["daemonRunning"])
        self.assertEqual(document["mode"], "manual")
        self.assertEqual(document["desiredKind"], "dark")
        self.assertEqual(document["desiredTheme"], DARK)
        self.assertIsNone(document["nextTransition"])

    def test_offline_automatic_document_does_not_present_stale_decision(self):
        state = state_mod.DuskState(
            configured=True,
            mode="scheduled",
            desired_kind="light",
            desired_theme=LIGHT,
            next_transition="2026-09-07T19:00:00+00:00",
            next_transition_kind="dark",
            location={"latitude": 50.0, "longitude": -1.0},
            location_source="weather",
        )

        document = status.document(
            state,
            configured("solar"),
            daemon_running=False,
            now=NOW,
            theme_available=lambda _slug: True,
        )

        self.assertEqual(document["mode"], "solar")
        self.assertIsNone(document["desiredKind"])
        self.assertIsNone(document["desiredTheme"])
        self.assertIsNone(document["nextTransition"])
        self.assertIsNone(document["location"])
        self.assertIsNone(document["locationSource"])

    def test_document_includes_config_warning(self):
        document = status.document(
            state_mod.DuskState(),
            config_mod.defaults(),
            daemon_running=False,
            config_warning="using defaults",
            now=NOW,
        )

        self.assertEqual(document["configWarning"], "using defaults")

    def test_offline_document_rejects_uninstalled_themes(self):
        document = status.document(
            state_mod.DuskState(),
            configured("manual"),
            daemon_running=False,
            now=NOW,
            theme_available=lambda _slug: False,
        )

        self.assertFalse(document["configured"])
        self.assertIsNone(document["desiredTheme"])


if __name__ == "__main__":
    unittest.main()
