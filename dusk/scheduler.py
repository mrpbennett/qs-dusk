"""The Dusk scheduler daemon.

Owns the decision loop: recompute the desired theme and next transition,
apply through `omarchy theme set` when needed, then wait for the single next
transition (or a reload/resume signal). All I/O that matters (clock, zone,
location, Omarchy) is injectable so the engine is testable without a desktop.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, ipc, paths, schedule
from . import omarchy as omarchy_mod
from . import state as state_mod

log = logging.getLogger("dusk")

# Upper bound on a single wait. The scheduler still sleeps only once per
# transition; the cap merely forces a cheap re-evaluation at least daily,
# which absorbs resume/late-wake and clock/timezone jumps on long waits.
MAX_WAIT_SECONDS = 24 * 3600


def local_tz() -> Any:
    return datetime.now().astimezone().tzinfo


class Scheduler:
    def __init__(
        self,
        now_fn: Callable[[], datetime] | None = None,
        tz_fn: Callable[[], Any] | None = None,
        location_provider: Callable[[], tuple[float, float] | None] | None = None,
        omarchy: Any | None = None,
        config_path: Path | None = None,
        state_path: Path | None = None,
        socket_path: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.now_fn = now_fn or (lambda: datetime.now().astimezone())
        self.tz_fn = tz_fn or local_tz
        self.location_provider = location_provider or (lambda: omarchy_mod.weather_location())
        self.omarchy = omarchy or omarchy_mod.Omarchy()
        self.config_path = Path(config_path) if config_path else paths.config_file()
        self.state_path = Path(state_path) if state_path else paths.state_file()
        self.logger = logger or log

        self.state = state_mod.load_state(self.state_path)
        self.server: ipc.ControlServer | None = None
        self._stop = False
        self._wake_r: int | None = None
        self._wake_w: int | None = None
        if socket_path is not None:
            self.server = ipc.ControlServer(socket_path)

    # ---- lifecycle --------------------------------------------------------

    def _install_signals(self) -> None:
        if self._wake_r is not None:
            return
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        if self.server is not None:
            self.server.register_wake(self._wake_r)

        def handler(signum: int, _frame: Any) -> None:
            if signum in (signal.SIGTERM, signal.SIGINT):
                self._stop = True
            elif signum == signal.SIGUSR1:
                self.logger.info("reload requested via SIGUSR1")
            if self._wake_w is not None:
                try:
                    os.write(self._wake_w, b"x")
                except OSError:
                    pass

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGUSR1, handler)

    def run(self) -> None:
        self._install_signals()
        try:
            while not self._stop:
                self.recompute()
                if self._stop:
                    break
                wait = self.compute_wait()
                if self.server is not None:
                    self.server.poll(wait, handler=self._request_handler)
                else:
                    time.sleep(min(wait, 1.0))
        finally:
            self.logger.info("scheduler stopped")
            if self.server is not None:
                self.server.close()
            if self._wake_r is not None:
                try:
                    os.close(self._wake_r)
                except OSError:
                    pass
            if self._wake_w is not None:
                try:
                    os.close(self._wake_w)
                except OSError:
                    pass

    # ---- requests ---------------------------------------------------------

    def _request_handler(self, request: dict[str, Any]) -> dict[str, Any]:
        cmd = request.get("cmd")
        if cmd == "status":
            return {"ok": True, "state": self.status_snapshot()}
        if cmd == "reload":
            self.logger.info("reload requested via control socket")
            return {"ok": True}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    # ---- decision loop ----------------------------------------------------

    def recompute(self) -> schedule.Decision:
        now = self.now_fn()
        tz = self.tz_fn()
        location = self.location_provider()
        cfg, cfg_warning = config.load_config(self.config_path)

        decision = schedule.resolve(
            cfg, now, tz, location, theme_available=self.omarchy.theme_available
        )
        if cfg_warning and decision.ok:
            decision.errors.append(cfg_warning)

        self._sync_state_from_config(cfg, decision, now, location)
        if decision.configured and decision.desiredTheme and decision.ok:
            self._apply(decision)
        self._persist_state()

        if not decision.ok:
            self.logger.warning("schedule invalid: %s", "; ".join(decision.errors))
        elif not decision.configured:
            self.logger.info("dusk not configured: set themes with `omarchy-auto-theme themes --light .. --dark ..`")
        else:
            nxt = decision.nextTransition
            nxt_txt = nxt.strftime("%Y-%m-%d %H:%M %Z") if nxt else "none"
            self.logger.info(
                "mode=%s desired=%s next=%s", decision.mode, decision.desiredTheme, nxt_txt
            )
        return decision

    def compute_wait(self) -> float:
        """Seconds until the next scheduled wake, capped and retry-aware."""
        now = self.now_fn()
        seconds = MAX_WAIT_SECONDS
        nxt = self.state.get("nextTransition")
        if nxt:
            try:
                nxt_dt = datetime.fromisoformat(nxt)
                if nxt_dt.tzinfo is None:
                    nxt_dt = nxt_dt.replace(tzinfo=self.tz_fn())
                seconds = (nxt_dt - now).total_seconds()
            except ValueError:
                seconds = MAX_WAIT_SECONDS
        seconds = max(1.0, min(seconds, MAX_WAIT_SECONDS))

        failures = int(self.state.get("failuresSinceSuccess", 0))
        if failures > 0:
            retries_left = self._retries_left()
            if retries_left > 0:
                retry_seconds = self._retry_interval()
                seconds = min(seconds, retry_seconds)
        return seconds

    def _apply(self, decision: schedule.Decision) -> None:
        desired = decision.desiredTheme
        current = self.omarchy.current_theme()
        self.state["currentTheme"] = current

        # A failure belongs to one target theme. The next scheduled target must
        # get its own retry budget rather than inheriting a previous failure.
        if self.state.get("retryTheme") != desired:
            self.state["failuresSinceSuccess"] = 0
            self.state["retryTheme"] = desired

        if desired == current:
            self.state["appliedTheme"] = desired
            self.state["lastError"] = None
            self.state["failuresSinceSuccess"] = 0
            self.state["retryTheme"] = None
            self.logger.info("theme %r already active; no-op", desired)
            return

        if self._retries_left() is not None and self._retries_left() <= 0:
            self.logger.warning("giving up on theme %r until the next transition", desired)
            return

        self.logger.info("applying theme %r via `omarchy theme set`", desired)
        result = self.omarchy.apply_theme(desired)
        if result.success:
            self.state["appliedTheme"] = desired
            self.state["currentTheme"] = desired
            self.state["lastSuccess"] = now_iso(self.now_fn())
            self.state["lastError"] = None
            self.state["failuresSinceSuccess"] = 0
            self.state["retryTheme"] = None
        else:
            self.state["failuresSinceSuccess"] = self.state.get("failuresSinceSuccess", 0) + 1
            detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
            self.state["lastError"] = f"omarchy theme set {desired!r} failed: {detail[:400]}"
            self.logger.error("%s", self.state["lastError"])

    def _sync_state_from_config(
        self,
        cfg: dict[str, Any],
        decision: schedule.Decision,
        now: datetime,
        location: tuple[float, float] | None,
    ) -> None:
        state = self.state
        state["configured"] = decision.configured and decision.ok
        state["mode"] = decision.mode
        state["desiredKind"] = decision.desiredKind
        state["desiredTheme"] = decision.desiredTheme
        state["nextTransition"] = (
            decision.nextTransition.isoformat() if decision.nextTransition else None
        )
        state["nextTransitionKind"] = decision.nextTransitionKind
        state["solarUnavailable"] = decision.solarUnavailable
        state["location"] = None
        state["locationSource"] = decision.locationSource
        if location is not None:
            state["location"] = {"latitude": location[0], "longitude": location[1]}
        if decision.ok or not decision.configured and not state.get("appliedTheme"):
            state["lastError"] = None
        state["updatedAt"] = now_iso(now)

    def _persist_state(self) -> None:
        try:
            state_mod.save_state(self.state, self.state_path)
        except OSError as exc:
            self.logger.error("could not persist state: %s", exc)

    # ---- helpers ----------------------------------------------------------

    def _retry_interval(self) -> float:
        cfg, _ = config.load_config(self.config_path)
        return float(cfg.get("retryIntervalSeconds", 120))

    def _retries_left(self) -> int | None:
        cfg, _ = config.load_config(self.config_path)
        max_retries = int(cfg.get("maxRetries", 5))
        failures = int(self.state.get("failuresSinceSuccess", 0))
        return max_retries - failures

    def status_snapshot(self) -> dict[str, Any]:
        snapshot = dict(self.state)
        snapshot["daemonRunning"] = True
        snapshot["updatedAt"] = self.state.get("updatedAt")
        return snapshot


def now_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()
