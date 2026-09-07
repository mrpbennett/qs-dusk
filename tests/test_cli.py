import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from dusk import cli, ipc
from dusk import config as config_mod
from dusk import omarchy as omarchy_mod
from dusk import state as state_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy, write_config

LIGHT = "catppuccin-latte"
DARK = "catppuccin"
OTHER = "gruvbox"

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class UpClient:
    """ControlClient stand-in with the daemon running."""

    def __init__(self, path, timeout=3.0):
        pass

    def request(self, cmd, **kwargs):
        if cmd == "status":
            state = state_mod.DuskState(mode="solar", configured=True).as_dict()
            state.update(
                {
                    "daemonRunning": True,
                    "lightTheme": LIGHT,
                    "darkTheme": DARK,
                    "configWarning": None,
                }
            )
            return {"ok": True, "state": state}
        return {"ok": True}


class DownClient:
    """ControlClient stand-in with the daemon not running."""

    def __init__(self, path, timeout=3.0):
        pass

    def request(self, cmd, **kwargs):
        raise ipc.ControlError("daemon down")


class RejectingClient:
    def __init__(self, path, timeout=3.0):
        pass

    def request(self, cmd, **kwargs):
        return {"ok": False, "error": "could not persist State"}


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.fake = FakeOmarchy(installed=[LIGHT, DARK, OTHER])
        self.deps_up = self.deps(UpClient)
        self.deps_down = self.deps(DownClient)
        self.deps_rejecting = self.deps(RejectingClient)

    def tearDown(self):
        self.tmp.cleanup()

    def deps(self, client, omarchy=None):
        return cli.Deps(
            omarchy=omarchy or self.fake,
            control=lambda path: client(path),
            config_path=self.root / "config.json",
            state_path=self.root / "state.json",
            socket_path=self.root / "control.sock",
            now_fn=lambda: NOW,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    @property
    def config_path(self) -> Path:
        return self.deps_up.config_path

    @property
    def state_path(self) -> Path:
        return self.deps_up.state_path

    def status_document(self, deps) -> dict:
        self.stdout.seek(0)
        self.stdout.truncate()
        self.assertEqual(cli.cmd_status(True, deps), 0)
        return __import__("json").loads(self.stdout.getvalue())

    def test_status_json_daemon_up(self):
        doc = self.status_document(self.deps_up)
        self.assertTrue(doc["daemonRunning"])
        self.assertEqual(doc["mode"], "solar")

    def test_status_json_daemon_down(self):
        state_mod.save_state(state_mod.DuskState(), self.state_path)
        doc = self.status_document(self.deps_down)
        self.assertFalse(doc["daemonRunning"])

    def test_status_daemon_down_uses_current_manual_preferences(self):
        write_config(
            self.config_path,
            {"mode": "manual", "manualTheme": "dark", "lightTheme": LIGHT, "darkTheme": DARK},
        )
        stale = state_mod.DuskState(mode="scheduled", desired_kind="light", desired_theme=LIGHT)
        state_mod.save_state(stale, self.state_path)
        doc = self.status_document(self.deps_down)
        self.assertEqual(doc["mode"], "manual")
        self.assertEqual(doc["desiredTheme"], DARK)

    def test_missing_option_value_returns_usage_error(self):
        for args in (
            ["scheduled", "--light", "07:00", "--dark"],
            ["themes", "--light"],
            ["offsets", "--sunrise", "0", "--sunset"],
        ):
            with self.subTest(args=args):
                self.assertEqual(cli.main(args, self.deps_up), 1)

    def test_reload_reports_daemon_state(self):
        self.assertEqual(cli.main(["reload"], self.deps_up), 0)
        self.assertEqual(cli.main(["reload"], self.deps_down), 1)
        self.assertEqual(cli.main(["reload"], self.deps_rejecting), 1)

    def test_manual_does_not_apply_standalone_when_daemon_rejects_reload(self):
        self.fake.current = OTHER
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})

        rc = cli.cmd_manual("light", self.deps_rejecting)

        self.assertEqual(rc, 1)
        self.assertEqual(self.fake.applied, [])

    def test_scheduled_rejects_equal_times(self):
        rc = cli.cmd_scheduled("07:00", "07:00", self.deps_up)
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.config_path.exists())

    def test_scheduled_accepts_valid_times(self):
        rc = cli.cmd_scheduled("07:00", "19:00", self.deps_up)
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["mode"], "scheduled")
        self.assertEqual(cfg["scheduled"]["light"], "07:00")

    def test_themes_rejects_unknown_slug(self):
        rc = cli.cmd_themes("does-not-exist", DARK, self.deps_up)
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.config_path.exists())

    def test_themes_accepts_installed_slugs(self):
        rc = cli.cmd_themes("Catppuccin Latte", "catppuccin", self.deps_up)
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["lightTheme"], LIGHT)
        self.assertEqual(cfg["darkTheme"], DARK)

    def test_theme_list_reports_catalog_discovery_failure(self):
        unavailable = FakeOmarchy()
        unavailable.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (), "could not list Omarchy themes: unavailable", discovery_complete=False
        )
        deps = self.deps(DownClient, unavailable)

        self.assertEqual(cli.cmd_themes_list(True, deps), 1)
        self.assertIn("could not list Omarchy themes", self.stderr.getvalue())

    def test_offline_status_treats_catalog_failure_as_unknown_not_absent(self):
        write_config(self.config_path, {"mode": "manual", "lightTheme": LIGHT, "darkTheme": DARK})
        unavailable = FakeOmarchy()
        unavailable.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (), "could not list Omarchy themes: unavailable", discovery_complete=False
        )

        document = self.status_document(self.deps(DownClient, unavailable))

        self.assertTrue(document["configured"])
        self.assertIn("could not list Omarchy themes", document["configWarning"])

    def test_offline_status_rejects_confirmed_absence_during_partial_failure(self):
        write_config(self.config_path, {"mode": "manual", "lightTheme": LIGHT, "darkTheme": DARK})
        partial = FakeOmarchy()
        partial.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (),
            "could not list Omarchy themes: unavailable",
            absent_slugs=frozenset((LIGHT,)),
            discovery_complete=False,
        )

        document = self.status_document(self.deps(DownClient, partial))

        self.assertFalse(document["configured"])
        self.assertIsNone(document["desiredTheme"])

    def test_human_status_prints_catalog_discovery_warning(self):
        unavailable = FakeOmarchy()
        unavailable.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (), "could not list Omarchy themes: unavailable", discovery_complete=False
        )

        self.assertEqual(cli.cmd_status(False, self.deps(DownClient, unavailable)), 0)

        self.assertIn("Warning: could not list Omarchy themes", self.stdout.getvalue())

    def test_daemon_backed_human_status_prints_fresh_catalog_warning(self):
        unavailable = FakeOmarchy()
        unavailable.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (), "could not list Omarchy themes: unavailable", discovery_complete=False
        )

        self.assertEqual(cli.cmd_status(False, self.deps(UpClient, unavailable)), 0)

        self.assertIn("Warning: could not list Omarchy themes", self.stdout.getvalue())

    def test_setting_confirmed_theme_reports_partial_catalog_failure(self):
        partial = FakeOmarchy()
        themes = (
            omarchy_mod.Theme(LIGHT, "Catppuccin Latte"),
            omarchy_mod.Theme(DARK, "Catppuccin"),
        )
        partial.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            themes, "could not list Omarchy themes: unavailable", discovery_complete=False
        )

        rc = cli.cmd_themes(LIGHT, DARK, self.deps(DownClient, partial))

        self.assertEqual(rc, 0)
        self.assertIn("note: could not list Omarchy themes", self.stderr.getvalue())

    def test_setting_theme_rejects_confirmed_absent_existing_counterpart(self):
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})
        partial = FakeOmarchy()
        partial.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (omarchy_mod.Theme(LIGHT, "Catppuccin Latte"),),
            "could not list Omarchy themes: unavailable",
            absent_slugs=frozenset((DARK,)),
            discovery_complete=False,
        )

        rc = cli.cmd_themes(LIGHT, None, self.deps(DownClient, partial))

        self.assertEqual(rc, 1)
        self.assertIn("darkTheme", self.stderr.getvalue())

    def test_setting_confirmed_absent_theme_does_not_report_unknown(self):
        partial = FakeOmarchy()
        partial.theme_catalog = lambda candidates=(): omarchy_mod.ThemeCatalog(
            (),
            "could not list Omarchy themes: unavailable",
            absent_slugs=frozenset((LIGHT,)),
            discovery_complete=False,
        )

        rc = cli.cmd_themes(LIGHT, None, self.deps(DownClient, partial))

        self.assertEqual(rc, 1)
        self.assertIn("lightTheme", self.stderr.getvalue())
        self.assertIn("not installed", self.stderr.getvalue())

    def test_offsets_validate_range(self):
        rc = cli.cmd_offsets("9999", "0", self.deps_up)
        self.assertNotEqual(rc, 0)

    def test_offsets_accept(self):
        rc = cli.cmd_offsets("-15", "30", self.deps_up)
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["solar"]["sunriseOffsetMinutes"], -15)

    def test_manual_applies_directly_when_daemon_down(self):
        self.fake.current = OTHER
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})
        rc = cli.cmd_manual("light", self.deps_down)
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.applied, [LIGHT])
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["mode"], "manual")
        self.assertEqual(cfg["manualTheme"], "light")
        st = state_mod.load_state(self.state_path)
        self.assertEqual(st.applied_theme, LIGHT)
        self.assertIsNone(st.last_error)

    def test_manual_is_noop_when_theme_already_active(self):
        self.fake.current = LIGHT
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})
        rc = cli.cmd_manual("light", self.deps_down)
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.applied, [])  # no native call for a no-op
        st = state_mod.load_state(self.state_path)
        self.assertEqual(st.applied_theme, LIGHT)

    def test_manual_records_failure_when_apply_fails(self):
        self.fake.current = OTHER
        self.fake.fail_on = [LIGHT]
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})
        rc = cli.cmd_manual("light", self.deps_down)
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.fake.applied, [])
        st = state_mod.load_state(self.state_path)
        self.assertIsNotNone(st.last_error)
        self.assertEqual(st.failures_since_success, 1)

    def test_manual_rejects_bad_kind(self):
        rc = cli.cmd_manual("pink", self.deps_up)
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
