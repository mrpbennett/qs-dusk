"""The `omarchy-auto-theme` command.

Controls the Dusk scheduler. Every theme change is delegated to the scheduler
daemon, which applies it through `omarchy theme set`; when the daemon is not
running, `manual` still applies directly through the same Omarchy command so
it works standalone.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from . import config as config_mod
from . import ipc, paths, status
from . import omarchy as omarchy_mod
from . import schedule as schedule_mod

EXIT_OK = 0
EXIT_ERROR = 1


@dataclass(frozen=True)
class Deps:
    """The external context for one invocation.

    Production resolves paths, time, streams, and adapters once in
    :func:`_production_deps`; tests pass them through this interface instead
    of changing process-wide state.
    """

    omarchy: omarchy_mod.Omarchy
    control: Callable[[Path], Any]
    config_path: Path = field(default_factory=paths.config_file)
    state_path: Path = field(default_factory=paths.state_file)
    socket_path: Path = field(default_factory=paths.socket_path)
    now_fn: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)


def _production_deps() -> Deps:
    return Deps(omarchy=omarchy_mod.Omarchy(), control=ipc.ControlClient)


def _load(deps: Deps) -> dict[str, Any]:
    cfg, _ = config_mod.load_config(deps.config_path)
    return cfg


def _save(cfg: dict[str, Any], deps: Deps) -> None:
    config_mod.save_config(cfg, deps.config_path)


class ReloadResult(Enum):
    COMPLETED = "completed"
    UNREACHABLE = "unreachable"
    REJECTED = "rejected"


def _notify_daemon(deps: Deps) -> ReloadResult:
    try:
        response = deps.control(deps.socket_path).request("reload")
        if response.get("ok") is True:
            return ReloadResult.COMPLETED
        return ReloadResult.REJECTED
    except ipc.ControlError:
        return ReloadResult.UNREACHABLE


def _require_daemon_or_warn(result: ReloadResult, deps: Deps) -> None:
    if result is ReloadResult.UNREACHABLE:
        print("note: scheduler is not running; the change applies on next start", file=deps.stderr)
    elif result is ReloadResult.REJECTED:
        print(
            "note: scheduler did not complete reload; it will retry on its next Tick",
            file=deps.stderr,
        )


def _validate_or_fail(cfg: dict[str, Any], deps: Deps, **kwargs: Any) -> bool:
    errors = config_mod.validate_config(cfg, **kwargs)
    if errors:
        print("invalid config: " + "; ".join(errors), file=deps.stderr)
        return False
    return True


def _save_and_notify(cfg: dict[str, Any], deps: Deps) -> None:
    _save(cfg, deps)
    _require_daemon_or_warn(_notify_daemon(deps), deps)


# ---- subcommands ----------------------------------------------------------

def cmd_status(json_out: bool, deps: Deps) -> int:
    merged: dict[str, Any] | None = None
    catalog: omarchy_mod.ThemeCatalog | None = None
    try:
        response = deps.control(deps.socket_path).request("status")
        if response.get("ok"):
            merged = dict(response.get("state") or {})
    except ipc.ControlError:
        pass

    if merged is None:
        from . import state as state_mod

        cfg, cfg_warning = config_mod.load_config(deps.config_path)
        configured_themes = tuple(
            value for value in (cfg.get("lightTheme"), cfg.get("darkTheme")) if value
        )
        catalog = deps.omarchy.theme_catalog(configured_themes)
        if catalog.discovery_error:
            cfg_warning = "; ".join(filter(None, (cfg_warning, catalog.discovery_error)))
        merged = status.document(
            state_mod.load_state(deps.state_path),
            cfg,
            daemon_running=False,
            config_warning=cfg_warning,
            theme_available=lambda slug: catalog.availability(slug) is not False,
            now=deps.now_fn(),
        )

    if json_out:
        print(json.dumps(merged, indent=2, sort_keys=True), file=deps.stdout)
        return EXIT_OK

    mode = merged["mode"] or "unknown"
    mode_label = {
        "solar": "Solar",
        "scheduled": "Scheduled",
        "manual": "Manual",
    }.get(mode, mode.title())

    if not merged["configured"]:
        print(
            "Mode: Not configured (set a theme pair with `omarchy-auto-theme themes --light .. --dark ..`)",
            file=deps.stdout,
        )
    else:
        current = merged.get("currentTheme")
        if current is None:
            current = deps.omarchy.current_theme()
        if catalog is None:
            catalog = deps.omarchy.theme_catalog(
                value
                for value in (current, merged.get("lightTheme"), merged.get("darkTheme"))
                if value
            )
            if catalog.discovery_error:
                merged["configWarning"] = "; ".join(
                    filter(
                        None,
                        (merged.get("configWarning"), catalog.discovery_error),
                    )
                )
        print(f"Theme: {catalog.display_name(current) or '(unset)'}", file=deps.stdout)
        print(f"Mode: {mode_label}", file=deps.stdout)
        if merged.get("nextTransition"):
            nxt = merged["nextTransition"]
            try:
                nxt_dt = datetime.fromisoformat(nxt)
                at = nxt_dt.strftime("%H:%M")
            except ValueError:
                at = nxt
            print(
                f"Next transition: {(merged['nextTransitionKind'] or 'theme').title()} at {at}",
                file=deps.stdout,
            )
        else:
            print("Next transition: none (manual or no events)", file=deps.stdout)
        print(
            f"Theme pair: {catalog.display_name(merged['lightTheme']) or '(unset)'}"
            f" / {catalog.display_name(merged['darkTheme']) or '(unset)'}",
            file=deps.stdout,
        )

    location_source = merged.get("locationSource")
    if location_source == "weather":
        print("Location: Omarchy weather coordinates", file=deps.stdout)
    else:
        print("Location: none", file=deps.stdout)
    if merged.get("solarUnavailable"):
        print(f"Fallback: {merged['solarUnavailable']}", file=deps.stdout)
    if merged.get("lastError"):
        print(f"Error: {merged['lastError']}", file=deps.stdout)
    if merged.get("configWarning"):
        print(f"Warning: {merged['configWarning']}", file=deps.stdout)
    if not merged["daemonRunning"]:
        print("Scheduler: not running", file=deps.stdout)
    return EXIT_OK


def cmd_solar(deps: Deps) -> int:
    cfg = _load(deps)
    cfg["mode"] = "solar"
    if not _validate_or_fail(cfg, deps):
        return EXIT_ERROR
    _save_and_notify(cfg, deps)
    print("Mode: Solar", file=deps.stdout)
    return EXIT_OK


def cmd_scheduled(light: str, dark: str, deps: Deps) -> int:
    cfg = _load(deps)
    errors = config_mod.validate_hm_pair(light, dark, "scheduled")
    if errors:
        print("invalid schedule: " + "; ".join(errors), file=deps.stderr)
        return EXIT_ERROR
    cfg["scheduled"] = {"light": light, "dark": dark}
    cfg["mode"] = "scheduled"
    if not _validate_or_fail(cfg, deps):
        return EXIT_ERROR
    _save_and_notify(cfg, deps)
    print(f"Mode: Scheduled (light {light}, dark {dark})", file=deps.stdout)
    return EXIT_OK


def cmd_manual(kind: str, deps: Deps) -> int:
    if kind not in ("light", "dark"):
        print(f"manual requires 'light' or 'dark', got {kind!r}", file=deps.stderr)
        return EXIT_ERROR
    cfg = _load(deps)
    cfg["manualTheme"] = kind
    cfg["mode"] = "manual"
    if not _validate_or_fail(cfg, deps):
        return EXIT_ERROR
    _save(cfg, deps)

    # One definition of "what does manual <kind> mean": the same pure
    # Decision the daemon resolves.
    now = deps.now_fn()
    decision = schedule_mod.resolve(cfg, now, now.tzinfo, None)
    slug = decision.desiredTheme if decision.ok else None
    if not slug:
        print(
            "themes not configured; `manual` set the mode but nothing is applied",
            file=deps.stderr,
        )
        return EXIT_ERROR
    reload_result = _notify_daemon(deps)
    if reload_result is ReloadResult.COMPLETED:
        print(
            f"Mode: Manual ({kind}) — theme {slug} will be applied by the scheduler",
            file=deps.stdout,
        )
        return EXIT_OK
    if reload_result is ReloadResult.REJECTED:
        print("scheduler did not complete reload", file=deps.stderr)
        return EXIT_ERROR

    # Daemon not running: apply directly so manual still works standalone,
    # through the same apply engine the daemon's Tick drives. Retry budgeting
    # is a daemon concern; an interactive command reports its result instead.
    from . import engine
    from . import state as state_mod

    state_path = deps.state_path
    self_state, outcome = engine.apply_and_record(
        state_mod.load_state(state_path),
        deps.omarchy,
        slug,
        now=now,
        max_retries=None,
    )
    try:
        state_mod.save_state(self_state, state_path)
    except OSError as exc:
        print(f"note: could not record state: {exc}", file=deps.stderr)

    if outcome.noop:
        print(f"Mode: Manual ({kind}) — theme {slug} already active", file=deps.stdout)
        return EXIT_OK
    result = outcome.result
    if result is not None and result.success:
        print(f"Mode: Manual ({kind}) — applied theme {slug}", file=deps.stdout)
        return EXIT_OK
    detail = (result.stderr or result.stdout) if result is not None else ""
    print(f"failed to apply theme {slug}: {detail.strip()}", file=deps.stderr)
    return EXIT_ERROR


def cmd_themes(light: str | None, dark: str | None, deps: Deps) -> int:
    om = deps.omarchy
    cfg = _load(deps)
    errors: list[str] = []
    light_slug = omarchy_mod.normalize_slug(light) if light is not None else None
    dark_slug = omarchy_mod.normalize_slug(dark) if dark is not None else None
    catalog = om.theme_catalog(
        value
        for value in (light_slug, dark_slug, cfg.get("lightTheme"), cfg.get("darkTheme"))
        if value
    )
    if light is not None:
        availability = catalog.availability(light_slug or "")
        if availability is True:
            cfg["lightTheme"] = light_slug
        elif availability is False:
            errors.append(f"lightTheme: theme {light_slug!r} is not installed")
        else:
            errors.append(catalog.discovery_error or f"could not inspect light theme {light!r}")
    if dark is not None:
        availability = catalog.availability(dark_slug or "")
        if availability is True:
            cfg["darkTheme"] = dark_slug
        elif availability is False:
            errors.append(f"darkTheme: theme {dark_slug!r} is not installed")
        else:
            errors.append(catalog.discovery_error or f"could not inspect dark theme {dark!r}")
    for label in ("lightTheme", "darkTheme"):
        slug = cfg.get(label)
        if not slug:
            continue
        availability = catalog.availability(slug)
        if availability is False:
            errors.append(f"{label}: theme {slug!r} is not installed")
        elif availability is None:
            errors.append(catalog.discovery_error or f"could not inspect theme {slug!r}")
    if errors:
        print("; ".join(dict.fromkeys(errors)), file=deps.stderr)
        if catalog.discovery_error is None:
            print("available themes: " + ", ".join(catalog.slugs()), file=deps.stderr)
        return EXIT_ERROR
    if not _validate_or_fail(cfg, deps):
        return EXIT_ERROR
    if catalog.discovery_error:
        print(f"note: {catalog.discovery_error}", file=deps.stderr)
    _save_and_notify(cfg, deps)
    print(f"Theme pair: {cfg.get('lightTheme')} / {cfg.get('darkTheme')}", file=deps.stdout)
    return EXIT_OK


def cmd_themes_list(json_out: bool, deps: Deps) -> int:
    catalog = deps.omarchy.theme_catalog()
    if catalog.discovery_error:
        print(catalog.discovery_error, file=deps.stderr)
        return EXIT_ERROR
    themes = catalog.as_dicts()
    cfg, _ = config_mod.load_config(deps.config_path)
    if json_out:
        payload = {
            "themes": themes,
            "lightTheme": cfg.get("lightTheme"),
            "darkTheme": cfg.get("darkTheme"),
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=deps.stdout)
        return EXIT_OK
    print("available themes:", file=deps.stdout)
    for entry in themes:
        print(f"  {entry['name']}", file=deps.stdout)
    print(
        f"current pair: light={cfg.get('lightTheme')} / dark={cfg.get('darkTheme')}",
        file=deps.stdout,
    )
    return EXIT_OK


def cmd_offsets(sunrise: str, sunset: str, deps: Deps) -> int:
    def parse_offset(value: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            return None

    sunrise_min = parse_offset(sunrise)
    sunset_min = parse_offset(sunset)
    if sunrise_min is None or sunset_min is None:
        print("offsets must be integers (minutes)", file=deps.stderr)
        return EXIT_ERROR
    errors = config_mod.validate_offset(sunrise_min, "solar.sunriseOffsetMinutes")
    errors += config_mod.validate_offset(sunset_min, "solar.sunsetOffsetMinutes")
    if errors:
        print("; ".join(errors), file=deps.stderr)
        return EXIT_ERROR
    cfg = _load(deps)
    cfg["solar"] = {
        **cfg.get("solar", {}),
        "sunriseOffsetMinutes": sunrise_min,
        "sunsetOffsetMinutes": sunset_min,
    }
    _save_and_notify(cfg, deps)
    print(
        f"Solar offsets: sunrise {sunrise_min:+d} min, sunset {sunset_min:+d} min",
        file=deps.stdout,
    )
    return EXIT_OK


def cmd_reload(deps: Deps) -> int:
    if _notify_daemon(deps) is ReloadResult.COMPLETED:
        print("reload sent to scheduler", file=deps.stdout)
        return EXIT_OK
    print("scheduler did not complete reload", file=deps.stderr)
    return EXIT_ERROR


def usage() -> str:
    return """Usage: omarchy-auto-theme <command> [options]

Commands:
  status [--json]                     Show mode, current theme, next transition
  solar                               Enable sunrise/sunset mode
  scheduled --light HH:MM --dark HH:MM  Enable fixed daily schedule
  manual light|dark                   Apply one theme once, stop automation
  themes                              List available themes and current pair
  themes --light <slug> [--dark <slug>] Set the theme pair (either or both)
  themes --json                       Machine-readable theme list (for widgets)
  offsets --sunrise MIN --sunset MIN  Solar offsets in minutes (signed)
  reload                              Tell the scheduler to re-evaluate
  help                                Show this help
"""


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # pragma: no cover - trivial override
        raise _ArgumentError(message)


def _build_parser() -> _Parser:
    parser = _Parser(prog="omarchy-auto-theme", add_help=False)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", add_help=False)
    p_status.add_argument("--json", action="store_true")

    sub.add_parser("solar", add_help=False)
    sub.add_parser("reload", add_help=False)

    p_scheduled = sub.add_parser("scheduled", add_help=False)
    p_scheduled.add_argument("--light", required=True, metavar="HH:MM")
    p_scheduled.add_argument("--dark", required=True, metavar="HH:MM")

    p_manual = sub.add_parser("manual", add_help=False)
    p_manual.add_argument("kind", nargs="?", default="")

    p_themes = sub.add_parser("themes", add_help=False)
    p_themes.add_argument("--light")
    p_themes.add_argument("--dark")
    p_themes.add_argument("--json", action="store_true")

    p_offsets = sub.add_parser("offsets", add_help=False)
    p_offsets.add_argument("--sunrise", required=True, metavar="MIN")
    p_offsets.add_argument("--sunset", required=True, metavar="MIN")

    return parser


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    deps = deps or _production_deps()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(usage(), file=deps.stdout)
        return EXIT_OK

    try:
        args = _build_parser().parse_args(argv)
    except _ArgumentError as exc:
        print(str(exc), file=deps.stderr)
        return EXIT_ERROR

    if args.command == "status":
        return cmd_status(args.json, deps)
    if args.command == "solar":
        return cmd_solar(deps)
    if args.command == "reload":
        return cmd_reload(deps)
    if args.command == "scheduled":
        return cmd_scheduled(args.light, args.dark, deps)
    if args.command == "manual":
        return cmd_manual(args.kind, deps)
    if args.command == "offsets":
        return cmd_offsets(args.sunrise, args.sunset, deps)

    # args.command == "themes"
    if args.json:
        return cmd_themes_list(True, deps)
    if args.light is None and args.dark is None:
        return cmd_themes_list(False, deps)
    return cmd_themes(args.light, args.dark, deps)


if __name__ == "__main__":
    sys.exit(main())
