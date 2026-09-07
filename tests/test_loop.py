"""End-to-end tests for the daemon loop: pump, tick, and seam contracts.

These pin the two contracts that used to be folklore:

1. ``ControlServer.poll`` returns after the first ready round or at timeout,
   so a ``reload`` sent mid-wait reaches the engine promptly.
2. The signal wake pipe interrupts a blocking ``poll``.
"""

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dusk import scheduler as scheduler_mod
from dusk import state as state_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy, write_config

UTC = timezone.utc
LIGHT = "catppuccin-latte"
DARK = "catppuccin"


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def wait_until(pred, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


class PollContractTest(unittest.TestCase):
    """Pins ControlServer.poll's break-after-first-round contract."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self.tmp.name) / "control.sock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_poll_returns_promptly_on_request_during_long_wait(self):
        server = scheduler_mod.ipc.ControlServer(self.sock)
        handled_seen = []

        def serve():
            handled_seen.extend(server.poll(30.0, handler=lambda req: {"ok": True}))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        time.sleep(0.1)

        started = time.monotonic()
        response = scheduler_mod.ipc.ControlClient(self.sock).request("reload")
        elapsed = time.monotonic() - started

        thread.join(timeout=5)
        self.assertTrue(response["ok"])
        self.assertLess(elapsed, 5.0, "poll must not sit out the full timeout")
        self.assertEqual(handled_seen, [{"cmd": "reload"}])
        server.close()

    def test_wake_pipe_interrupts_poll(self):
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        os.set_blocking(write_fd, False)
        server = scheduler_mod.ipc.ControlServer(self.sock)
        server.register_wake(read_fd)
        handled_seen = []

        def serve():
            handled_seen.extend(server.poll(30.0))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        time.sleep(0.1)

        started = time.monotonic()
        os.write(write_fd, b"x")
        thread.join(timeout=5)

        self.assertEqual(handled_seen, [{"cmd": "__signal"}])
        self.assertLess(time.monotonic() - started, 5.0)
        os.close(read_fd)
        os.close(write_fd)
        server.close()


class RunLoopIntegrationTest(unittest.TestCase):
    """Drives the real run() loop over a real socket with a scripted clock."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tmp.name) / "config.json"
        self.state_path = Path(self.tmp.name) / "state.json"
        self.sock_path = Path(self.tmp.name) / "control.sock"
        write_config(
            self.config_path,
            {"mode": "scheduled", "lightTheme": LIGHT, "darkTheme": DARK},
        )
        self.om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox")
        self.clock = {"now": at(2026, 8, 19, 10, 0)}
        self.scheduler = scheduler_mod.Scheduler(
            now_fn=lambda: self.clock["now"],
            tz_fn=lambda: UTC,
            location_provider=lambda: None,
            omarchy=self.om,
            config_path=self.config_path,
            state_path=self.state_path,
            socket_path=self.sock_path,
            logger=scheduler_mod.log,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_startup_status_reload_and_shutdown(self):
        ticks = []
        original_tick = self.scheduler.tick

        def counted_tick():
            ticks.append(True)
            return original_tick()

        self.scheduler.tick = counted_tick
        thread = threading.Thread(target=self.scheduler.run, daemon=True)
        thread.start()
        try:
            # Startup tick applies the desired theme through the adapter.
            self.assertTrue(wait_until(lambda: self.om.applied == [LIGHT]))
            self.assertEqual(len(ticks), 1)

            # A status query is answered mid-wait, out of the live engine.
            client = scheduler_mod.ipc.ControlClient(self.sock_path)
            response = client.request("status")
            self.assertTrue(response["ok"])
            self.assertTrue(response["state"]["daemonRunning"])
            self.assertEqual(response["state"]["desiredTheme"], LIGHT)
            time.sleep(0.05)
            self.assertEqual(len(ticks), 1, "status must preserve the transition deadline")

            # Reload after the clock jumps past the evening transition must
            # recompute promptly: the regression that was previously untested.
            self.clock["now"] = at(2026, 8, 19, 20, 0)
            reload_response = client.request("reload")
            self.assertTrue(reload_response["ok"])
            self.assertEqual(reload_response["state"]["desiredTheme"], DARK)
            self.assertEqual(self.om.applied, [LIGHT, DARK])
            self.assertEqual(len(ticks), 2)
            time.sleep(0.05)
            self.assertEqual(len(ticks), 2, "reload must not cause a duplicate tick")
            state = state_mod.load_state(self.state_path)
            self.assertEqual(state.applied_theme, DARK)

            self.assertFalse(client.request("bogus")["ok"])
        finally:
            self.stop_scheduler(thread)

        self.assertFalse(thread.is_alive())
        self.assertFalse(self.sock_path.exists(), "shutdown must unlink the socket")

    def stop_scheduler(self, thread):
        self.scheduler._stop = True
        wake_w = getattr(self.scheduler, "_wake_w", None)
        if wake_w is not None:
            try:
                os.write(wake_w, b"x")
            except OSError:
                pass
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
