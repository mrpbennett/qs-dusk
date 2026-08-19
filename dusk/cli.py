"""The `omarchy-auto-theme` command.

Controls the Dusk scheduler. Every theme change is delegated to the scheduler
daemon, which applies it through `omarchy theme set`; when the daemon is not
running, `manual` still applies directly through the same Omarchy command so
it works standalone.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from . import config as config_mod
from . import ipc, paths
from . import omarchy as omarchy_mod

EXIT_OK = 0
EXIT_ERROR = 1


def _load() -> dict[str, Any]:
    cfg, _ = config_mod.load_config()
    return cfg


def _save(cfg: dict[str, Any]) -> None:
    config_mod.save_config(cfg)


def _notify_daemon() -> bool:
    try:
        ipc.ControlClient(paths.socket_path()).request("reload")
        return True
    except ipc.ControlError:
        return False


def _theme_available(slug: str, om: omarchy_mod.Omarchy) -> bool:
    return om.theme_available(slug)


def _require_daemon_or_warn(notified: bool) -> None:
    if not notified:
        print("note: scheduler is not running; the change applies on next start", file=sys.stderr)


def _pretty_theme(slug: str | None) -> str:
    if not slug:
        return "(unset)"
    om = omarchy_mod.Omarchy()
    for line in om.list_theme_slugs():
        if line == omarchy_mod.normalize_slug(slug):
            # Find the display name Omarchy prints.
            for name in _theme_display_names():
                if omarchy_mod.normalize_slug(name) == line:
                    return name
            break
    return slug


def _theme_display_names() -> list[str]:
    import subprocess

    try:
        proc = subprocess.run(
            ["omarchy", "theme", "list"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


# ---- subcommands ----------------------------------------------------------

def cmd_status(json_out: bool) -> int:
    daemon_state: dict[str, Any] | None = None
    daemon_running = False
    try:
        response = ipc.ControlClient(paths.socket_path()).request("status")
        if response.get("ok"):
            daemon_state = response.get("state") or {}
            daemon_running = True
    except ipc.ControlError:
        pass

    cfg, cfg_warning = config_mod.load_config()
    if daemon_state is None:
        from . import state as state_mod

        daemon_state = state_mod.load_state(paths.state_file())
        daemon_state["daemonRunning"] = False

        # Persisted state describes the last daemon run, not newly saved
        # preferences. Do not present it as current while the daemon is down.
        if cfg.get("mode") == "manual":
            kind = cfg.get("manualTheme")
            desired_theme = cfg.get("lightTheme") if kind == "light" else cfg.get("darkTheme")
        else:
            kind = None
            desired_theme = None
        daemon_state.update(
            {
                "configured": bool(cfg.get("lightTheme") and cfg.get("darkTheme")),
                "mode": cfg.get("mode"),
                "desiredKind": kind,
                "desiredTheme": desired_theme,
                "nextTransition": None,
                "nextTransitionKind": None,
                "location": None,
                "locationSource": None,
                "solarUnavailable": None,
            }
        )

    merged = {
        "daemonRunning": daemon_running,
        "configured": bool(daemon_state.get("configured")),
        "mode": daemon_state.get("mode") or cfg.get("mode"),
        "desiredKind": daemon_state.get("desiredKind"),
        "desiredTheme": daemon_state.get("desiredTheme"),
        "appliedTheme": daemon_state.get("appliedTheme"),
        "currentTheme": daemon_state.get("currentTheme"),
        "nextTransition": daemon_state.get("nextTransition"),
        "nextTransitionKind": daemon_state.get("nextTransitionKind"),
        "lightTheme": cfg.get("lightTheme"),
        "darkTheme": cfg.get("darkTheme"),
        "location": daemon_state.get("location"),
        "locationSource": daemon_state.get("locationSource"),
        "solarUnavailable": daemon_state.get("solarUnavailable"),
        "lastError": daemon_state.get("lastError"),
        "lastSuccess": daemon_state.get("lastSuccess"),
        "updatedAt": daemon_state.get("updatedAt"),
        "configWarning": cfg_warning,
    }

    if json_out:
        print(json.dumps(merged, indent=2, sort_keys=True))
        return EXIT_OK

    mode = merged["mode"] or "unknown"
    mode_label = {
        "solar": "Solar",
        "scheduled": "Scheduled",
        "manual": "Manual",
    }.get(mode, mode.title())

    if not merged["configured"]:
        print("Mode: Not configured (set a theme pair with `omarchy-auto-theme themes --light .. --dark ..`)")
    else:
        om = omarchy_mod.Omarchy()
        current = merged.get("currentTheme")
        if current is None:
            current = om.current_theme()
        print(f"Theme: {_pretty_theme(current)}")
        print(f"Mode: {mode_label}")
        if merged.get("nextTransition"):
            nxt = merged["nextTransition"]
            try:
                nxt_dt = datetime.fromisoformat(nxt)
                at = nxt_dt.strftime("%H:%M")
            except ValueError:
                at = nxt
            print(f"Next transition: {(merged['nextTransitionKind'] or 'theme').title()} at {at}")
        else:
            print("Next transition: none (manual or no events)")
        print(f"Theme pair: {_pretty_theme(merged['lightTheme'])} / {_pretty_theme(merged['darkTheme'])}")

    location_source = merged.get("locationSource")
    if location_source == "weather":
        print("Location: Omarchy weather coordinates")
    else:
        print("Location: none")
    if merged.get("solarUnavailable"):
        print(f"Fallback: {merged['solarUnavailable']}")
    if merged.get("lastError"):
        print(f"Error: {merged['lastError']}")
    if not daemon_running:
        print("Scheduler: not running")
    return EXIT_OK


def cmd_solar() -> int:
    cfg = _load()
    cfg["mode"] = "solar"
    errors = config_mod.validate_config(cfg)
    if errors:
        print("invalid config: " + "; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    _save(cfg)
    _require_daemon_or_warn(_notify_daemon())
    print("Mode: Solar")
    return EXIT_OK


def cmd_scheduled(light: str, dark: str) -> int:
    cfg = _load()
    errors = config_mod.validate_hm_pair(light, dark, "scheduled")
    if errors:
        print("invalid schedule: " + "; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    cfg["scheduled"] = {"light": light, "dark": dark}
    cfg["mode"] = "scheduled"
    errors = config_mod.validate_config(cfg)
    if errors:
        print("invalid config: " + "; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    _save(cfg)
    _require_daemon_or_warn(_notify_daemon())
    print(f"Mode: Scheduled (light {light}, dark {dark})")
    return EXIT_OK


def cmd_manual(kind: str) -> int:
    if kind not in ("light", "dark"):
        print(f"manual requires 'light' or 'dark', got {kind!r}", file=sys.stderr)
        return EXIT_ERROR
    cfg = _load()
    cfg["manualTheme"] = kind
    cfg["mode"] = "manual"
    errors = config_mod.validate_config(cfg)
    if errors:
        print("invalid config: " + "; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    _save(cfg)

    slug = cfg.get("lightTheme") if kind == "light" else cfg.get("darkTheme")
    if not slug:
        print("themes not configured; `manual` set the mode but nothing is applied", file=sys.stderr)
        return EXIT_ERROR
    if _notify_daemon():
        print(f"Mode: Manual ({kind}) — theme {slug} will be applied by the scheduler")
        return EXIT_OK
    # Daemon not running: apply directly so manual still works standalone.
    om = omarchy_mod.Omarchy()
    result = om.apply_theme(slug)
    if result.success:
        print(f"Mode: Manual ({kind}) — applied theme {slug}")
        return EXIT_OK
    print(f"failed to apply theme {slug}: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
    return EXIT_ERROR


def cmd_themes(light: str | None, dark: str | None) -> int:
    om = omarchy_mod.Omarchy()
    cfg = _load()
    errors: list[str] = []
    if light is not None:
        light_slug = omarchy_mod.normalize_slug(light)
        if not _theme_available(light_slug, om):
            errors.append(f"light theme {light!r} is not installed")
        else:
            cfg["lightTheme"] = light_slug
    if dark is not None:
        dark_slug = omarchy_mod.normalize_slug(dark)
        if not _theme_available(dark_slug, om):
            errors.append(f"dark theme {dark!r} is not installed")
        else:
            cfg["darkTheme"] = dark_slug
    if errors:
        print("; ".join(errors), file=sys.stderr)
        print("available themes: " + ", ".join(sorted(om.list_theme_slugs())), file=sys.stderr)
        return EXIT_ERROR
    errors = config_mod.validate_config(cfg, theme_available=om.theme_available)
    if errors:
        print("invalid config: " + "; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    _save(cfg)
    _require_daemon_or_warn(_notify_daemon())
    print(f"Theme pair: {cfg.get('lightTheme')} / {cfg.get('darkTheme')}")
    return EXIT_OK


def cmd_themes_list(json_out: bool) -> int:
    om = omarchy_mod.Omarchy()
    names = _theme_display_names()
    themes: list[dict[str, str]] = []
    if names:
        seen: set[str] = set()
        for name in names:
            slug = omarchy_mod.normalize_slug(name)
            if slug and slug not in seen:
                seen.add(slug)
                themes.append({"slug": slug, "name": name})
    else:
        for slug in sorted(om.list_theme_slugs()):
            if slug:
                themes.append({"slug": slug, "name": slug.replace("-", " ").title()})
    cfg, _ = config_mod.load_config()
    if json_out:
        payload = {
            "themes": themes,
            "lightTheme": cfg.get("lightTheme"),
            "darkTheme": cfg.get("darkTheme"),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return EXIT_OK
    print("available themes:")
    for entry in themes:
        print(f"  {entry['name']}")
    print(f"current pair: light={cfg.get('lightTheme')} / dark={cfg.get('darkTheme')}")
    return EXIT_OK


def cmd_offsets(sunrise: str, sunset: str) -> int:
    def parse_offset(value: str) -> int | None:
        try:
            return int(value)
        except ValueError:
            return None

    sunrise_min = parse_offset(sunrise)
    sunset_min = parse_offset(sunset)
    if sunrise_min is None or sunset_min is None:
        print("offsets must be integers (minutes)", file=sys.stderr)
        return EXIT_ERROR
    errors = config_mod.validate_offset(sunrise_min, "solar.sunriseOffsetMinutes")
    errors += config_mod.validate_offset(sunset_min, "solar.sunsetOffsetMinutes")
    if errors:
        print("; ".join(errors), file=sys.stderr)
        return EXIT_ERROR
    cfg = _load()
    cfg["solar"] = {
        **cfg.get("solar", {}),
        "sunriseOffsetMinutes": sunrise_min,
        "sunsetOffsetMinutes": sunset_min,
    }
    _save(cfg)
    _require_daemon_or_warn(_notify_daemon())
    print(f"Solar offsets: sunrise {sunrise_min:+d} min, sunset {sunset_min:+d} min")
    return EXIT_OK


def cmd_reload() -> int:
    if _notify_daemon():
        print("reload sent to scheduler")
        return EXIT_OK
    print("scheduler is not running", file=sys.stderr)
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(usage())
        return EXIT_OK

    cmd, rest = argv[0], argv[1:]

    def option_value(flag: str) -> str | None:
        if flag not in rest:
            return None
        index = rest.index(flag) + 1
        return rest[index] if index < len(rest) else None

    if cmd == "status":
        return cmd_status("--json" in rest)

    if cmd == "solar":
        return cmd_solar()

    if cmd == "scheduled":
        light = option_value("--light")
        dark = option_value("--dark")
        if light is not None and dark is not None:
            return cmd_scheduled(light, dark)
        print("scheduled requires --light HH:MM --dark HH:MM", file=sys.stderr)
        return EXIT_ERROR

    if cmd == "manual":
        return cmd_manual(rest[0] if rest else "")

    if cmd == "themes":
        if "--json" in rest:
            return cmd_themes_list(True)
        has_light = "--light" in rest
        has_dark = "--dark" in rest
        if not has_light and not has_dark:
            return cmd_themes_list(False)
        light = option_value("--light") if has_light else None
        dark = option_value("--dark") if has_dark else None
        if (has_light and light is None) or (has_dark and dark is None):
            print("themes requires a slug after --light or --dark", file=sys.stderr)
            return EXIT_ERROR
        return cmd_themes(light, dark)

    if cmd == "offsets":
        sunrise = option_value("--sunrise")
        sunset = option_value("--sunset")
        if sunrise is not None and sunset is not None:
            return cmd_offsets(sunrise, sunset)
        print("offsets requires --sunrise MIN --sunset MIN", file=sys.stderr)
        return EXIT_ERROR

    if cmd == "reload":
        return cmd_reload()

    print(f"unknown command {cmd!r}", file=sys.stderr)
    print(usage(), file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
