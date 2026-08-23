"""Apply engine: turn a desired theme slug into a recorded outcome.

One implementation of observe → retry-budget reset → no-op check → apply →
record, driven by the Daemon's Tick (:meth:`dusk.scheduler.Scheduler._apply`)
and by the CLI's standalone manual path when the daemon is down. The rules
for how an attempt mutates :class:`dusk.state.DuskState` live here and in the
State module — nowhere else.

Pure with respect to its inputs: state goes in, new state comes out, callers
log and print from the returned :class:`Outcome`. The only side effect is the
`omarchy theme set` call itself, made through the Omarchy adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .omarchy import ApplyResult, Omarchy
from .state import DuskState


@dataclass(frozen=True)
class Outcome:
    """What one engine step did."""

    attempted: bool  # `omarchy theme set` ran
    noop: bool  # desired theme was already active; nothing applied
    exhausted: bool  # retry budget spent; apply withheld until next transition
    result: ApplyResult | None = None

    @property
    def success(self) -> bool:
        return self.result is not None and self.result.success


def apply_and_record(
    state: DuskState,
    omarchy: Omarchy,
    desired: str,
    *,
    now: datetime,
    max_retries: int | None,
) -> tuple[DuskState, Outcome]:
    """Attempt to apply `desired`, recording the outcome in `state`.

    `max_retries` caps consecutive failures per target theme; pass None where
    budgeting does not apply (an interactive command reports instead).
    """
    current = omarchy.current_theme()
    state = state.observe_current(current)

    # A failure belongs to one target theme. The next scheduled target must
    # get its own retry budget rather than inheriting a previous failure.
    if state.retry_theme != desired:
        state = state.reset_retry_budget(desired)

    if desired == current:
        state = state.mark_no_op(desired)
        return state, Outcome(attempted=False, noop=True, exhausted=False)

    if max_retries is not None and state.failures_since_success >= max_retries:
        return state, Outcome(attempted=False, noop=False, exhausted=True)

    result = omarchy.apply_theme(desired)
    detail = result.stderr or result.stdout or f"exit code {result.returncode}"
    state = state.record_apply(desired, result.success, detail, now)
    return state, Outcome(attempted=True, noop=False, exhausted=False, result=result)
