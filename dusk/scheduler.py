"""The Dusk scheduler daemon.

Owns the decision loop as a tick engine: each :meth:`Scheduler.tick` advances
the engine one step — recompute the desired theme and next transition, apply
through `omarchy theme set` when needed, persist state, and report how long
the pump should wait. :meth:`Scheduler.run` is only a pump: it wires wakes
(socket requests, signals, timeouts) into ticks. All I/O that matters (clock,
zone, location, Omarchy) is injectable so the engine is testable without a
desktop.
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
from . import status as status_mod
from .engine import apply_and_record

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
        self.config = config.defaults()
        self.config_warning: str | None = None
        self.server: ipc.ControlServer | None = None
        self._stop = False
        self._wait_after_request: float | None = None
        self._last_persisted = True
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

        # signal.signal only works in the main thread; a background-thread
        # run() (tests) installs no handlers and is stopped via _stop.
        try:
            signal.signal(signal.SIGTERM, handler)
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGUSR1, handler)
        except ValueError:
            self.logger.debug("signal handlers unavailable off the main thread")

    def run(self) -> None:
        """Pump: tick, wait for the next wake, repeat.

        ``ControlServer.poll`` returns after the first ready round or timeout.
        Reload handlers complete their Tick before replying and supply the new
        wait. Observational requests preserve the current deadline; timeout and
        signal wakes cause a fresh Tick here.
        """
        self._install_signals()
        try:
            wait = self.tick()
            deadline = time.monotonic() + wait
            while not self._stop:
                if self._stop:
                    break
                if self.server is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        wait = self.tick()
                        deadline = time.monotonic() + wait
                        continue
                    handled = self.server.poll(remaining, handler=self._request_handler)
                    self.logger.debug(
                        "woke after %.1fs: %s",
                        wait,
                        [request.get("cmd") for request in handled],
                    )
                    if self._wait_after_request is not None:
                        wait = self._wait_after_request
                        self._wait_after_request = None
                        deadline = time.monotonic() + wait
                    elif handled and not any(
                        request.get("cmd") == "__signal" for request in handled
                    ):
                        continue
                    else:
                        wait = self.tick()
                        deadline = time.monotonic() + wait
                else:
                    time.sleep(min(wait, 1.0))
                    wait = self.tick()
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
            self._wait_after_request = self.tick()
            if not self._last_persisted:
                return {"ok": False, "error": "could not persist State"}
            return {"ok": True, "state": self.status_snapshot()}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    # ---- decision loop ----------------------------------------------------

    def tick(self) -> float:
        """Advance the engine one step and return seconds until the next wake.

        Loads config once, resolves the :class:`~dusk.schedule.Decision` for
        *now*, syncs runtime state, applies the desired theme when configured
        and healthy, persists state, then computes the wait: capped at
        ``MAX_WAIT_SECONDS`` (daily re-evaluation absorbs resume/clock jumps)
        and shortened to the retry interval while a failure is pending.
        """
        now = self.now_fn()
        tz = self.tz_fn()
        location = self.location_provider()
        cfg, cfg_warning = config.load_config(self.config_path)
        self.config = cfg
        self.config_warning = cfg_warning
        catalog = self.omarchy.theme_catalog(
            value for value in (cfg.get("lightTheme"), cfg.get("darkTheme")) if value
        )

        decision = schedule.resolve(
            cfg, now, tz, location, theme_available=catalog.available
        )
        if cfg_warning and decision.ok:
            decision.errors.append(cfg_warning)

        self.state = self.state.synced_from(decision, location, now)
        if decision.configured and decision.desiredTheme and decision.ok:
            self._apply(cfg, decision)
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
        return self._next_wait(now, decision, cfg)

    def _next_wait(self, now: datetime, decision: schedule.Decision, cfg: dict[str, Any]) -> float:
        """Seconds until the next scheduled wake, capped and retry-aware.

        Uses the live ``decision.nextTransition``; the ISO string in
        ``state["nextTransition"]`` exists only for persistence.
        """
        seconds = MAX_WAIT_SECONDS
        nxt = decision.nextTransition
        if nxt is not None:
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=self.tz_fn())
            seconds = (nxt - now).total_seconds()
        seconds = max(1.0, min(seconds, MAX_WAIT_SECONDS))

        failures = self.state.failures_since_success
        if failures > 0 and int(cfg.get("maxRetries", 5)) - failures > 0:
            seconds = min(seconds, float(cfg.get("retryIntervalSeconds", 120)))
        return seconds

    def _apply(self, cfg: dict[str, Any], decision: schedule.Decision) -> None:
        desired = decision.desiredTheme
        if not desired:
            return

        self.state, outcome = apply_and_record(
            self.state,
            self.omarchy,
            desired,
            now=self.now_fn(),
            max_retries=int(cfg.get("maxRetries", 5)),
        )

        if outcome.noop:
            self.logger.info("theme %r already active; no-op", desired)
            return
        if outcome.exhausted:
            self.logger.warning("giving up on theme %r until the next transition", desired)
            return
        if outcome.attempted:
            self.logger.info("applying theme %r via `omarchy theme set`", desired)
        if self.state.last_error:
            self.logger.error("%s", self.state.last_error)

    def _persist_state(self) -> None:
        self._last_persisted = True
        try:
            state_mod.save_state(self.state, self.state_path)
        except OSError as exc:
            self._last_persisted = False
            self.logger.error("could not persist state: %s", exc)

    # ---- helpers ----------------------------------------------------------

    def status_snapshot(self) -> dict[str, Any]:
        return status_mod.document(
            self.state,
            self.config,
            daemon_running=True,
            config_warning=self.config_warning,
        )
