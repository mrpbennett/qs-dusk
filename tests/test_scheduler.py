import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dusk import scheduler as scheduler_mod
from dusk import state as state_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy, write_config

UTC = timezone.utc
LIGHT = "catppuccin-latte"
DARK = "catppuccin"
TZ_LONDON = ZoneInfo("Europe/London")
TZ_TOKYO = ZoneInfo("Asia/Tokyo")


def at(y, m, d, hh, mm, tz=UTC):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def make_scheduler(tmp, *, now=None, tz=UTC, location=None, omarchy=None, solar_cfg=None, mode="scheduled"):
    config_path = Path(tmp) / "config.json"
    state_path = Path(tmp) / "state.json"
    write_config(
        config_path,
        {
            "mode": mode,
            "lightTheme": LIGHT,
            "darkTheme": DARK,
            **({"solar": solar_cfg} if solar_cfg else {}),
        },
    )
    return scheduler_mod.Scheduler(
        now_fn=lambda: now,
        tz_fn=lambda: tz,
        location_provider=lambda: location,
        omarchy=omarchy or FakeOmarchy(installed=[LIGHT, DARK]),
        config_path=config_path,
        state_path=state_path,
        socket_path=None,
        logger=scheduler_mod.log,
    )


class SchedulerApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_startup_applies_desired_theme_once(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox")
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 10, 0),
            omarchy=om,
            mode="scheduled",
        )
        s.tick()
        self.assertEqual(om.applied, [LIGHT])  # exactly one native call
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.applied_theme, LIGHT)
        self.assertEqual(st.desired_theme, LIGHT)
        self.assertIsNone(st.last_error)

    def test_noop_when_already_current(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current=LIGHT)
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 10, 0),
            omarchy=om,
            mode="scheduled",
        )
        s.tick()
        self.assertEqual(om.applied, [])  # no native call for a no-op
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.applied_theme, LIGHT)

    def test_failed_apply_keeps_last_success_and_retries(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox", fail_once=True)
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 10, 0),
            omarchy=om,
            mode="scheduled",
        )
        s.tick()
        st = state_mod.load_state(s.state_path)
        self.assertIsNotNone(st.last_error)
        self.assertEqual(st.failures_since_success, 1)
        self.assertNotEqual(st.applied_theme, LIGHT)  # last success preserved

        # Retry after the retry interval elapses (late wake).
        s.now_fn = lambda: at(2026, 8, 19, 10, 3)  # +3m > retryInterval 120s
        s.tick()
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.last_error, None)
        self.assertEqual(st.applied_theme, LIGHT)
        self.assertEqual(st.failures_since_success, 0)

    def test_retries_exhausted_stops(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox", fail_on=[LIGHT])
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 10, 0),
            omarchy=om,
            mode="scheduled",
        )
        for _ in range(5):
            s.tick()
            s.now_fn = lambda: at(2026, 8, 19, 10, 0)  # same wall clock, retry backoff
        attempts = len([x for x in om.applied])
        self.assertEqual(attempts, 0)  # never applied; all failed
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.failures_since_success, 5)

        # Further ticks stop trying until a real transition.
        before = st.failures_since_success
        s.now_fn = lambda: at(2026, 8, 19, 12, 0)
        s.tick()
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.failures_since_success, before)

    def test_retry_budget_resets_for_next_transition(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox", fail_on=[LIGHT])
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 10, 0),
            omarchy=om,
            mode="scheduled",
        )
        for _ in range(5):
            s.tick()

        # The evening transition targets dark, which must not inherit light's
        # exhausted retry budget.
        s.now_fn = lambda: at(2026, 8, 19, 20, 0)
        s.tick()
        st = state_mod.load_state(s.state_path)
        self.assertEqual(om.applied, [DARK])
        self.assertEqual(st.failures_since_success, 0)
        self.assertIsNone(st.retry_theme)

    def test_manual_mode_applies_selected_theme(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox")
        s = make_scheduler(self.tmp.name, now=at(2026, 8, 19, 10, 0), omarchy=om, mode="manual")
        from dusk import config as config_mod

        cfg, _ = config_mod.load_config(s.config_path)
        cfg["mode"] = "manual"
        cfg["manualTheme"] = "dark"
        config_mod.save_config(cfg, s.config_path)
        s.tick()
        self.assertEqual(om.applied, [DARK])
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.desired_theme, DARK)

    def test_late_wake_catches_missed_transition(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        s = make_scheduler(self.tmp.name, now=at(2026, 8, 19, 20, 0), omarchy=om, mode="scheduled")
        s.tick()
        self.assertEqual(om.applied, [DARK])
        # Clock jumps past the next sunrise while asleep.
        s.now_fn = lambda: at(2026, 8, 20, 8, 0)
        s.tick()
        self.assertEqual(om.applied, [DARK, LIGHT])

    def test_external_theme_change_reapplies_desired(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        s = make_scheduler(self.tmp.name, now=at(2026, 8, 19, 20, 0), omarchy=om, mode="scheduled")
        s.tick()
        self.assertEqual(om.applied, [DARK])
        # A user runs `omarchy theme set gruvbox` outside dusk.
        om.current = "gruvbox"
        s.tick()
        self.assertEqual(om.applied, [DARK, DARK])

    def test_timezone_jump_changes_decision(self):
        holder = {"tz": TZ_LONDON}
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        config_path = Path(self.tmp.name) / "config.json"
        state_path = Path(self.tmp.name) / "state.json"
        write_config(config_path, {"mode": "scheduled", "lightTheme": LIGHT, "darkTheme": DARK})
        s = scheduler_mod.Scheduler(
            now_fn=lambda: at(2026, 8, 19, 12, 0, tz=holder["tz"]),
            tz_fn=lambda: holder["tz"],
            location_provider=lambda: None,
            omarchy=om,
            config_path=config_path,
            state_path=state_path,
            socket_path=None,
            logger=scheduler_mod.log,
        )
        s.tick()
        self.assertEqual(om.applied, [LIGHT])
        # Timezone changes (travel): local 12:00 in Tokyo is 04:00 in London.
        holder["tz"] = TZ_TOKYO
        s.now_fn = lambda: at(2026, 8, 19, 12, 0, tz=holder["tz"])
        s.tick()
        # Tokyo 12:00 -> no scheduled change, still light in both? 12:00 local is
        # between 07:00 and 19:00 in either zone, so theme stays light.
        self.assertEqual(om.applied, [LIGHT])
        # Jump to a local time that flips the decision.
        holder["tz"] = TZ_TOKYO
        s.now_fn = lambda: at(2026, 8, 19, 21, 0, tz=holder["tz"])
        s.tick()
        self.assertEqual(om.applied, [LIGHT, DARK])


class SchedulerStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_unconfigured_idles_without_apply(self):
        config_path = Path(self.tmp.name) / "config.json"
        state_path = Path(self.tmp.name) / "state.json"
        write_config(config_path, {"mode": "scheduled"})  # no themes
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        s = scheduler_mod.Scheduler(
            now_fn=lambda: at(2026, 8, 19, 10, 0),
            tz_fn=lambda: UTC,
            location_provider=lambda: None,
            omarchy=om,
            config_path=config_path,
            state_path=state_path,
            socket_path=None,
            logger=scheduler_mod.log,
        )
        s.tick()
        self.assertEqual(om.applied, [])
        st = state_mod.load_state(state_path)
        self.assertFalse(st.configured)
        self.assertIsNone(st.desired_theme)

    def test_invalid_config_no_apply_and_error_recorded(self):
        config_path = Path(self.tmp.name) / "config.json"
        state_path = Path(self.tmp.name) / "state.json"
        write_config(
            config_path,
            {"mode": "scheduled", "lightTheme": LIGHT, "darkTheme": DARK, "scheduled": {"light": "07:00", "dark": "07:00"}},
        )
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        s = scheduler_mod.Scheduler(
            now_fn=lambda: at(2026, 8, 19, 10, 0),
            tz_fn=lambda: UTC,
            location_provider=lambda: None,
            omarchy=om,
            config_path=config_path,
            state_path=state_path,
            socket_path=None,
            logger=scheduler_mod.log,
        )
        s.tick()
        self.assertEqual(om.applied, [])
        st = state_mod.load_state(state_path)
        self.assertFalse(st.configured)

    def test_solar_fallback_recorded(self):
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 20, 0),
            location=None,
            mode="solar",
        )
        s.tick()
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.desired_kind, "dark")
        self.assertIsNotNone(st.solar_unavailable)
        self.assertIn("coordinates", st.solar_unavailable)

    def test_solar_with_weather_location(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        s = make_scheduler(
            self.tmp.name,
            now=at(2026, 8, 19, 12, 0),
            location=(50.71429, -1.98458),
            omarchy=om,
            mode="solar",
        )
        s.tick()
        self.assertEqual(om.applied, [LIGHT])
        st = state_mod.load_state(s.state_path)
        self.assertEqual(st.location_source, "weather")
        self.assertEqual(st.location["latitude"], 50.71429)
        self.assertIsNone(st.solar_unavailable)

    def test_polar_day_no_transition(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        om = FakeOmarchy(installed=[LIGHT, DARK], current=None)
        config_path = Path(self.tmp.name) / "config.json"
        state_path = Path(self.tmp.name) / "state.json"
        write_config(config_path, {"mode": "solar", "lightTheme": LIGHT, "darkTheme": DARK})
        s = scheduler_mod.Scheduler(
            now_fn=lambda: datetime(2026, 6, 21, 12, 0, tzinfo=tz),
            tz_fn=lambda: tz,
            location_provider=lambda: (78.2232, 15.6469),
            omarchy=om,
            config_path=config_path,
            state_path=state_path,
            socket_path=None,
            logger=scheduler_mod.log,
        )
        wait = s.tick()
        self.assertEqual(om.applied, [LIGHT])
        self.assertEqual(wait, scheduler_mod.MAX_WAIT_SECONDS)


class NextWakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_waits_until_next_transition(self):
        s = make_scheduler(self.tmp.name, now=at(2026, 8, 19, 10, 0), mode="scheduled")
        wait = s.tick()
        self.assertGreater(wait, 8 * 3600 - 2)
        self.assertLessEqual(wait, 9 * 3600)

    def test_retry_shortens_wait(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox", fail_on=[LIGHT])
        s = make_scheduler(self.tmp.name, now=at(2026, 8, 19, 10, 0), omarchy=om, mode="scheduled")
        wait = s.tick()
        self.assertLessEqual(wait, 121)  # ~retryIntervalSeconds, not hours


if __name__ == "__main__":
    unittest.main()
