# Dusk — Design

Dusk is a user-level Omarchy extension that performs automatic appearance by
switching between two named Omarchy themes according to solar or fixed daily
times. It is not a theme engine: every desktop change goes through
`omarchy theme set <theme>`, which is the only mechanism that stages the theme,
updates the running shell, transitions the background, reloads supported
applications, and runs the user's `theme-set` hooks.

## Data flow

```
~/.config/omarchy/dusk/config.json  ──┐
~/.local/state/omarchy/settings/weather.json ──┐
                                             ├─> scheduler → omarchy theme set <slug>
~/.local/state/omarchy/current/theme.name ───┘              ├─> shell, backgrounds,
       (read-only observation of current theme)             │    app reloads, hooks
~/.local/state/omarchy/dusk/state.json ◄── scheduler writes ┘
$XDG_RUNTIME_DIR/dusk/control.sock ◄── CLI / bar widget
```

## Components

- **`omarchy-auto-theme`** (CLI) — edits the config atomically and asks the
  running daemon to reload. `status --json` queries the daemon; falls back to
  reading state files when the daemon is not running.
- **`dusk-scheduler`** (daemon) — a `systemd --user` service started with the
  graphical session. Owns the decision loop and all `omarchy theme set` calls.
- **`dusk` bar widget** (optional Quickshell plugin) — reflects daemon state and
  drives the CLI. Never calls `omarchy theme set` itself.
- **`dusk.service`** — user unit bound to `graphical-session.target`; survives
  shell restarts; independent of the Quickshell process.

## Files

| Path | Role | Owned by |
|---|---|---|
| `~/.config/omarchy/dusk/config.json` | user preferences | dusk |
| `~/.local/state/omarchy/dusk/state.json` | runtime state | dusk |
| `$XDG_RUNTIME_DIR/dusk/control.sock` | control socket | dusk |
| `~/.local/state/omarchy/current/theme.name` | observed current theme | Omarchy (read-only) |
| `~/.local/state/omarchy/settings/weather.json` | observed location | Omarchy (read-only) |

All dusk files use atomic writes (temp file + `os.replace`). Missing or malformed
config/state falls back to safe defaults and never overwrites user data.

## Config schema

```json
{
  "version": 1,
  "mode": "solar",
  "lightTheme": "catppuccin-latte",
  "darkTheme": "catppuccin",
  "manualTheme": "light",
  "scheduled": { "light": "07:00", "dark": "19:00" },
  "solar": {
    "sunriseOffsetMinutes": 0,
    "sunsetOffsetMinutes": 0,
    "fallback": { "light": "07:00", "dark": "19:00" }
  },
  "retryIntervalSeconds": 120,
  "maxRetries": 5
}
```

- `lightTheme`/`darkTheme` must resolve against `omarchy theme list` before
  automation is enabled; both `None` means "not configured" and the scheduler
  idles without applying anything.
- `scheduled` times are local `HH:MM` and must differ.
- `solar.fallback` is used only when solar data is unavailable (no weather
  coordinates, invalid coordinates, or calculation failure) — the fallback
  reason is always surfaced in status.
- `manual` applies one selected theme once and schedules no transitions until
  the mode is changed back.

## Scheduling model

Daily **events** are the unit of scheduling. Each event is
`(local datetime, kind)` where kind is `light` or `dark`.

- **scheduled**: two events per local day — `light@light-time`, `dark@dark-time`
  (chronological; a schedule where `dark < light` crosses midnight and is
  handled by pure ordering).
- **solar**: sunrise→light, sunset→dark, each offset by the configured minutes.
  Polar day → no events, default kind `light`; polar night → no events, default
  kind `dark`. Missing/invalid coordinates or failed calculation → scheduled
  fallback events with a visible reason.
- **manual**: a single desired theme, no events.

For a given `now`, the **active theme** is the target of the most recent event
with `at <= now` (across yesterday and today; for an event-less polar day the
midnight default kind is a marker). The **next transition** is the earliest
event with `at > now` (across today and tomorrow). If there is no next
transition the daemon re-evaluates daily, which also absorbs resume/late-wake
and clock/timezone jumps.

## Solar calculation

NOAA sunrise/sunset algorithm (see `solar.py`), computed in UTC and converted
to the local zone via `zoneinfo`. Validated against `astral` and
sunrise-sunset.org within ~1–2 minutes across solstices, DST, and leap days.
Zenith 90.833°. Two-pass refinement on the hour angle. Handles polar
day/night by solar-noon altitude; never raises for extreme latitudes.

## Apply / no-op / failure

One shared **apply engine** (`dusk/engine.py`) turns a desired slug into a
recorded outcome, for both the daemon's tick and the CLI's standalone manual
path:

1. Read current theme slug from `~/.local/state/omarchy/current/theme.name`.
2. If the retry target changed, reset the per-target retry budget.
3. If it equals the desired slug → record no-op; do **not** call Omarchy.
4. Otherwise, if the retry budget for this target is spent (`maxRetries`),
   withhold until the next transition or a reload.
5. Run `omarchy theme set <slug>` (argv list, no shell), wait for it to
   finish, capture exit code. In-flight transitions are serialized because
   the daemon is single-threaded and blocks until the call completes.
6. On success: record `appliedTheme` + `lastSuccess`, clear error. On
   failure: keep the last successful state, record `lastError`, and retry
   after `retryIntervalSeconds` up to `maxRetries` times.

The interactive `manual` command skips budgeting (`maxRetries` off): it
reports its result instead, including an explicit "already active" no-op when
the requested theme is current.

A manual `omarchy theme set` outside dusk is respected: because the engine
compares against the *observed* current theme, the next recompute re-applies the
desired theme only when the mode is automatic.

## Control socket

Line-delimited JSON over a unix socket in `$XDG_RUNTIME_DIR/dusk/`.
`status` returns the full state snapshot — the same document `state.json`
holds, plus a live echo of the config's theme pair; keys are owned by
DuskState's wire format alone. `reload` triggers a recompute.
The CLI falls back to reading files if the daemon is unreachable; `manual`
may then apply directly through the apply engine, recording the outcome
in `state.json` via the same DuskState rules, so it works standalone.