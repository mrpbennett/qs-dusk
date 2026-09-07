import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dusk import cli, ipc
from dusk import config as config_mod
from dusk import paths as paths_mod
from dusk import state as state_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy, write_config

LIGHT = "catppuccin-latte"
DARK = "catppuccin"
OTHER = "gruvbox"

ENV_KEYS = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")


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
        # Sandbox via XDG overrides: dusk.paths resolves from the environment
        # on every call, so fakes flow through the interface and nothing is
        # patched at module level.
        self._old_env = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ[key] = self.tmp.name

        self.fake = FakeOmarchy(installed=[LIGHT, DARK, OTHER])
        self.deps_up = cli.Deps(omarchy=self.fake, control=lambda path: UpClient(path))
        self.deps_down = cli.Deps(omarchy=self.fake, control=lambda path: DownClient(path))
        self.deps_rejecting = cli.Deps(
            omarchy=self.fake,
            control=lambda path: RejectingClient(path),
        )

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    @property
    def config_path(self) -> Path:
        return paths_mod.config_file()

    @property
    def state_path(self) -> Path:
        return paths_mod.state_file()

    def status_document(self, deps) -> dict:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.cmd_status(True, deps), 0)
        return __import__("json").loads(output.getvalue())

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
