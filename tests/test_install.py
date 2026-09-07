import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.systemctl_log = self.root / "systemctl.log"
        self.systemctl = self.root / "systemctl"
        self.systemctl.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$SYSTEMCTL_LOG\"\n",
            encoding="utf-8",
        )
        self.systemctl.chmod(0o755)

    def tearDown(self):
        self.temp_dir.cleanup()

    def env(self, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "SYSTEMCTL": str(self.systemctl),
                "SYSTEMCTL_LOG": str(self.systemctl_log),
            }
        )
        env.update({key: str(value) for key, value in overrides.items()})
        return env

    def run_script(self, script, *args, env=None, check=True):
        return subprocess.run(
            [str(script), *args],
            env=env or self.env(),
            text=True,
            capture_output=True,
            check=check,
        )

    def test_plugin_bootstrap_installs_checks_and_detects_repairs(self):
        bin_dir = self.root / "bin"
        unit_dir = self.root / "units"
        env = self.env(BIN_DIR=bin_dir, UNIT_DIR=unit_dir)
        bootstrap = ROOT / "bin" / "dusk-bootstrap"

        self.run_script(bootstrap, env=env)
        self.assertEqual(
            (bin_dir / "omarchy-auto-theme").readlink(),
            ROOT / "bin" / "omarchy-auto-theme",
        )
        self.assertIn(str(ROOT), (unit_dir / "dusk.service").read_text(encoding="utf-8"))
        self.run_script(bootstrap, "--check", env=env)

        (bin_dir / "omarchy-auto-theme").unlink()
        (bin_dir / "omarchy-auto-theme").write_text("occupied\n", encoding="utf-8")
        result = self.run_script(bootstrap, "--check", env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.run_script(bootstrap, env=env)
        self.assertTrue((bin_dir / "omarchy-auto-theme").is_symlink())

        (unit_dir / "dusk.service").write_text("stale\n", encoding="utf-8")
        result = self.run_script(bootstrap, "--check", env=env, check=False)
        self.assertNotEqual(result.returncode, 0)

        self.run_script(bootstrap, env=env)
        self.run_script(bootstrap, "--check", env=env)
        calls = self.systemctl_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            calls,
            [
                "--user daemon-reload",
                "--user enable dusk.service",
                "--user start dusk.service",
            ]
            * 3,
        )

    def test_direct_install_copies_complete_qml_layout(self):
        dusk_home = self.root / "dusk-home"
        bin_dir = self.root / "bin"
        unit_dir = self.root / "units"
        plugin_dir = self.root / "plugin"
        env = self.env(
            DUSK_HOME=dusk_home,
            BIN_DIR=bin_dir,
            UNIT_DIR=unit_dir,
            PLUGIN_DIR=plugin_dir,
        )

        self.run_script(ROOT / "install.sh", env=env)
        self.run_script(ROOT / "install.sh", env=env)

        for name in ("manifest.json", "Panel.qml", "Service.qml", "Icon.qml", "Bootstrap.qml"):
            self.assertTrue((plugin_dir / name).is_file(), name)
        self.assertTrue((plugin_dir / "bin" / "dusk-bootstrap").is_file())
        self.assertTrue((dusk_home / "bin" / "dusk-install").is_file())
        self.assertTrue((dusk_home / "systemd" / "dusk.service.tpl").is_file())
        marker = (plugin_dir / ".dusk-home").read_text(encoding="utf-8").strip()
        self.assertEqual(marker, str(dusk_home))

        qml_env = env.copy()
        qml_env.pop("DUSK_HOME")
        qml_env.pop("PLUGIN_DIR")
        self.run_script(plugin_dir / "bin" / "dusk-bootstrap", "--check", env=qml_env)

        runtime_module = dusk_home / "dusk" / "config.py"
        runtime_module.unlink()
        runtime_module.mkdir()
        result = self.run_script(
            plugin_dir / "bin" / "dusk-bootstrap", "--check", env=qml_env, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.run_script(ROOT / "install.sh", env=env)
        self.assertEqual(
            runtime_module.read_text(encoding="utf-8"),
            (ROOT / "dusk" / "config.py").read_text(encoding="utf-8"),
        )

        plugin_service = plugin_dir / "Service.qml"
        plugin_service.unlink()
        plugin_service.mkdir()
        result = self.run_script(
            plugin_dir / "bin" / "dusk-bootstrap", "--check", env=qml_env, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.run_script(ROOT / "install.sh", env=env)
        self.assertEqual(
            plugin_service.read_text(encoding="utf-8"),
            (ROOT / "Service.qml").read_text(encoding="utf-8"),
        )

        plugin_bootstrap = plugin_dir / "bin" / "dusk-bootstrap"
        plugin_bootstrap.chmod(0o644)
        result = self.run_script(ROOT / "install.sh", "--check", env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.run_script(ROOT / "install.sh", env=env)
        self.assertTrue(os.access(plugin_bootstrap, os.X_OK))
        self.run_script(ROOT / "install.sh", "--check", env=env)


if __name__ == "__main__":
    unittest.main()
