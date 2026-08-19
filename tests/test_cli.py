import tempfile
import unittest
from pathlib import Path

import dusk.paths as paths_mod
from dusk import cli, ipc
from dusk import config as config_mod
from dusk import omarchy as omarchy_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy, write_config

LIGHT = "catppuccin-latte"
DARK = "catppuccin"
OTHER = "gruvbox"


class UpClient:
    """ControlClient stand-in with the daemon running."""

    def __init__(self, path, timeout=3.0):
        pass

    def request(self, cmd, **kwargs):
        if cmd == "status":
            return {"ok": True, "state": {"mode": "solar", "configured": True}}
        return {"ok": True}


class DownClient:
    """ControlClient stand-in with the daemon not running."""

    def __init__(self, path, timeout=3.0):
        pass

    def request(self, cmd, **kwargs):
        raise ipc.ControlError("daemon down")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.state_path = Path(self.tmp.name) / "state.json"
        self.sock_path = Path(self.tmp.name) / "control.sock"
        self._patch_paths()
        self._original_omarchy = omarchy_mod.Omarchy
        self._original_client = ipc.ControlClient
        self.fake = FakeOmarchy(installed=[LIGHT, DARK, OTHER])
        omarchy_mod.Omarchy = lambda: self.fake
        ipc.ControlClient = UpClient

    def _patch_paths(self):
        paths_mod.config_file = lambda: self.config_path
        paths_mod.state_file = lambda: self.state_path
        paths_mod.socket_path = lambda: self.sock_path

    def tearDown(self):
        omarchy_mod.Omarchy = self._original_omarchy
        ipc.ControlClient = self._original_client
        self.tmp.cleanup()

    def test_status_json_daemon_up(self):
        self.assertEqual(cli.cmd_status(json_out=True), 0)
        self.assertTrue(self.config_path.parent.exists())

    def test_status_json_daemon_down(self):
        ipc.ControlClient = DownClient
        from dusk import state as state_mod

        state_mod.save_state(state_mod.new_state(), self.state_path)
        self.assertEqual(cli.cmd_status(json_out=True), 0)

    def test_scheduled_rejects_equal_times(self):
        rc = cli.cmd_scheduled("07:00", "07:00")
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.config_path.exists())

    def test_scheduled_accepts_valid_times(self):
        rc = cli.cmd_scheduled("07:00", "19:00")
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["mode"], "scheduled")
        self.assertEqual(cfg["scheduled"]["light"], "07:00")

    def test_themes_rejects_unknown_slug(self):
        rc = cli.cmd_themes("does-not-exist", DARK)
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.config_path.exists())

    def test_themes_accepts_installed_slugs(self):
        rc = cli.cmd_themes("Catppuccin Latte", "catppuccin")
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["lightTheme"], LIGHT)
        self.assertEqual(cfg["darkTheme"], DARK)

    def test_offsets_validate_range(self):
        rc = cli.cmd_offsets("9999", "0")
        self.assertNotEqual(rc, 0)

    def test_offsets_accept(self):
        rc = cli.cmd_offsets("-15", "30")
        self.assertEqual(rc, 0)
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["solar"]["sunriseOffsetMinutes"], -15)

    def test_manual_applies_directly_when_daemon_down(self):
        ipc.ControlClient = DownClient
        self.fake.current = OTHER
        write_config(self.config_path, {"lightTheme": LIGHT, "darkTheme": DARK})
        rc = cli.cmd_manual("light")
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.applied, [LIGHT])
        cfg, _ = config_mod.load_config(self.config_path)
        self.assertEqual(cfg["mode"], "manual")
        self.assertEqual(cfg["manualTheme"], "light")

    def test_manual_rejects_bad_kind(self):
        rc = cli.cmd_manual("pink")
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()