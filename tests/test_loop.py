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
        self.now_calls = 0

        def now():
            self.now_calls += 1
            return self.clock["now"]

        self.scheduler = scheduler_mod.Scheduler(
            now_fn=now,
            tz_fn=lambda: UTC,
            location_provider=lambda: None,
            omarchy=self.om,
            config_path=self.config_path,
            state_path=self.state_path,
            socket_path=self.sock_path,
            logger=scheduler_mod.log,
        )

    def tearDown(self):
        if self.scheduler.server is not None:
            self.scheduler.server.close()
        self.tmp.cleanup()

    def test_startup_status_reload_and_shutdown(self):
        thread = threading.Thread(target=self.scheduler.run, daemon=True)
        thread.start()
        try:
            # Startup tick applies the desired theme through the adapter.
            self.assertTrue(wait_until(lambda: self.om.applied == [LIGHT]))
            self.assertEqual(self.now_calls, 1)

            # A status query is answered mid-wait, out of the live engine.
            client = scheduler_mod.ipc.ControlClient(self.sock_path)
            response = client.request("status")
            self.assertTrue(response["ok"])
            self.assertTrue(response["state"]["daemonRunning"])
            self.assertEqual(response["state"]["desiredTheme"], LIGHT)
            time.sleep(0.05)
            self.assertEqual(self.now_calls, 1, "status must preserve the transition deadline")

            # Reload after the clock jumps past the evening transition must
            # recompute promptly: the regression that was previously untested.
            self.clock["now"] = at(2026, 8, 19, 20, 0)
            reload_response = client.request("reload")
            self.assertTrue(reload_response["ok"])
            self.assertEqual(reload_response["state"]["desiredTheme"], DARK)
            self.assertEqual(self.om.applied, [LIGHT, DARK])
            self.assertEqual(self.now_calls, 2)
            time.sleep(0.05)
            self.assertEqual(self.now_calls, 2, "reload must not cause a duplicate tick")
            state = state_mod.load_state(self.state_path)
            self.assertEqual(state.applied_theme, DARK)

            self.assertFalse(client.request("bogus")["ok"])
        finally:
            self.stop_scheduler(thread)

        self.assertFalse(thread.is_alive())
        self.assertFalse(self.sock_path.exists(), "shutdown must unlink the socket")
        self.assertEqual(self.now_calls, 2, "stop Wake must not cause a final Tick")

    def test_reload_reports_failed_state_persistence_through_control_socket(self):
        invalid_parent = Path(self.tmp.name) / "not-a-directory"
        invalid_parent.write_text("occupied", encoding="utf-8")
        self.scheduler.state_path = invalid_parent / "state.json"
        thread = threading.Thread(target=self.scheduler.run, daemon=True)
        thread.start()
        try:
            self.assertTrue(wait_until(self.sock_path.exists))
            response = scheduler_mod.ipc.ControlClient(self.sock_path).request("reload")
            self.assertFalse(response["ok"])
            self.assertIn("persist", response["error"])
        finally:
            self.stop_scheduler(thread)

    def test_timeout_and_signal_wakes_each_cause_exactly_one_tick(self):
        class WakeServer:
            def __init__(self, first_wake):
                self.first_wake = first_wake
                self.calls = 0
                self.scheduler = None

            def register_wake(self, _fd):
                pass

            def poll(self, _timeout, handler=None):
                self.calls += 1
                if self.calls == 1:
                    return self.first_wake
                self.scheduler.stop()
                return [{"cmd": "__signal"}]

            def close(self):
                pass

        for first_wake in ([], [{"cmd": "__signal"}]):
            with self.subTest(first_wake=first_wake):
                now_calls = []

                def now():
                    now_calls.append(True)
                    return self.clock["now"]

                scheduler = scheduler_mod.Scheduler(
                    now_fn=now,
                    tz_fn=lambda: UTC,
                    location_provider=lambda: None,
                    omarchy=FakeOmarchy(installed=[LIGHT, DARK], current=LIGHT),
                    config_path=self.config_path,
                    state_path=self.state_path,
                    socket_path=None,
                    logger=scheduler_mod.log,
                )
                server = WakeServer(first_wake)
                scheduler.server = server
                server.scheduler = scheduler
                thread = threading.Thread(target=scheduler.run, daemon=True)
                thread.start()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(now_calls), 2)

    def test_stop_wake_rejects_simultaneous_reload_without_ticking(self):
        now_calls = []

        def now():
            now_calls.append(True)
            return self.clock["now"]

        scheduler = scheduler_mod.Scheduler(
            now_fn=now,
            tz_fn=lambda: UTC,
            location_provider=lambda: None,
            omarchy=FakeOmarchy(installed=[LIGHT, DARK], current=LIGHT),
            config_path=self.config_path,
            state_path=self.state_path,
            socket_path=None,
            logger=scheduler_mod.log,
        )

        class StopAndReloadServer:
            response = None

            def register_wake(self, _fd):
                pass

            def poll(self, _timeout, handler=None):
                scheduler.stop()
                self.response = handler({"cmd": "reload"})
                return [{"cmd": "reload"}, {"cmd": "__signal"}]

            def close(self):
                pass

        server = StopAndReloadServer()
        scheduler.server = server
        thread = threading.Thread(target=scheduler.run, daemon=True)
        thread.start()
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertFalse(server.response["ok"])
        self.assertEqual(len(now_calls), 1)

    def stop_scheduler(self, thread):
        self.scheduler.stop()
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
