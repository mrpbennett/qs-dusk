import tempfile
import unittest
from datetime import datetime, timezone

from dusk import engine
from dusk import state as state_mod
from tests import util  # noqa: F401
from tests.helpers import FakeOmarchy

UTC = timezone.utc
LIGHT = "catppuccin-latte"
DARK = "catppuccin"
NOW = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


class ApplyEngineTest(unittest.TestCase):
    """Drives the apply-and-record engine through its interface alone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_path = f"{self.tmp.name}/state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return state_mod.load_state(self.state_path)

    def test_applies_and_records_success(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox")
        state, outcome = engine.apply_and_record(
            state_mod.DuskState(), om, LIGHT, now=NOW, max_retries=5
        )
        state_mod.save_state(state, self.state_path)
        self.assertTrue(outcome.attempted)
        self.assertTrue(outcome.success)
        self.assertEqual(om.applied, [LIGHT])
        st = self.load()
        self.assertEqual(st.applied_theme, LIGHT)
        self.assertEqual(st.current_theme, LIGHT)
        self.assertEqual(st.failures_since_success, 0)

    def test_noop_when_already_active(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current=LIGHT)
        state, outcome = engine.apply_and_record(
            state_mod.DuskState(), om, LIGHT, now=NOW, max_retries=5
        )
        self.assertFalse(outcome.attempted)
        self.assertTrue(outcome.noop)
        self.assertEqual(om.applied, [])  # no native call for a no-op
        st = state  # mark_no_op effects visible in returned record
        self.assertEqual(st.applied_theme, LIGHT)
        self.assertEqual(st.retry_theme, None)

    def test_failure_then_retry_succeeds(self):
        om = FakeOmarchy(installed=[LIGHT], current="gruvbox", fail_once=True)
        state, outcome = engine.apply_and_record(
            state_mod.DuskState(), om, LIGHT, now=NOW, max_retries=5
        )
        self.assertTrue(outcome.attempted)
        self.assertFalse(outcome.success)
        self.assertEqual(state.failures_since_success, 1)

        state, outcome = engine.apply_and_record(
            state, om, LIGHT, now=NOW, max_retries=5
        )
        self.assertTrue(outcome.success)
        self.assertEqual(state.failures_since_success, 0)

    def test_exhausted_budget_withholds_apply(self):
        om = FakeOmarchy(installed=[LIGHT], current="gruvbox", fail_on=[LIGHT])
        state = state_mod.DuskState()
        for _ in range(3):
            state, _outcome = engine.apply_and_record(
                state, om, LIGHT, now=NOW, max_retries=3
            )
        self.assertEqual(state.failures_since_success, 3)
        state, outcome = engine.apply_and_record(
            state, om, LIGHT, now=NOW, max_retries=3
        )
        self.assertTrue(outcome.exhausted)
        self.assertFalse(outcome.attempted)  # withheld, budget not exceeded
        self.assertEqual(state.failures_since_success, 3)

    def test_budget_resets_for_new_target(self):
        om = FakeOmarchy(installed=[LIGHT, DARK], current="gruvbox", fail_on=[LIGHT])
        state = state_mod.DuskState()
        for _ in range(5):
            state, _outcome = engine.apply_and_record(
                state, om, LIGHT, now=NOW, max_retries=5
            )
        self.assertEqual(state.failures_since_success, 5)

        # The evening transition targets dark, which must not inherit light's
        # exhausted retry budget.
        state, outcome = engine.apply_and_record(
            state, om, DARK, now=NOW, max_retries=5
        )
        self.assertTrue(outcome.success)
        self.assertEqual(om.applied, [DARK])
        self.assertEqual(state.failures_since_success, 0)


if __name__ == "__main__":
    unittest.main()
