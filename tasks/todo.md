# Dusk — Omarchy Automatic Theme Switching

## Status

Refinement complete. Existing saved scheduled configurations are preserved;
the normal panel flow is a reliable Auto / Light / Dark controller with a
polished, keyboard-operable panel.

## Plugin Layout Refinement

- [x] Move the plugin manifest and QML entry points to the repository root.
- [x] Update installation and validation references for the root plugin folder.
- [x] Validate the root folder using Omarchy's plugin validator.

### Plugin Layout Review

- `omarchy plugin validate .` — passed.
- `bash -n install.sh` — passed.
- `git diff --check` — passed.

## Refinement Plan

- [x] Fix automatic-mode and retry recovery correctness.
- [x] Make daemon-down status and malformed CLI input reliable.
- [x] Polish panel initialization, truthful appearance state, action feedback,
  and mutually exclusive theme dropdowns.
- [x] Make the installed widget able to locate its CLI and receive updates.
- [x] Add regression coverage; run tests, lint, and plugin validation.

## Panel Polish Plan

- [x] Refine hierarchy, state language, interaction targets, and feedback.
- [x] Make panel height follow its content, including expanded lists/notices.
- [x] Add keyboard activation and validate the plugin.

## Goal

Build a user-level Omarchy extension ("dusk") that switches between two complete
Omarchy themes according to solar or fixed daily times, using `omarchy theme set`
as the sole desktop-application mechanism. Includes a scheduler daemon, a
`omarchy-auto-theme` CLI, a `systemd --user` service, and an optional Quickshell
bar widget.

## Deliverables

- [x] `dusk/` Python package (stdlib-only)
  - [x] `paths.py` — config/state/socket path resolution
  - [x] `config.py` — atomic JSON config load/save + validation
  - [x] `state.py` — atomic JSON runtime-state load/save
  - [x] `solar.py` — NOAA sunrise/sunset, DST/polar handling
  - [x] `schedule.py` — mode decision, active theme, next transition
  - [x] `omarchy.py` — `omarchy theme list/current/set` facade (argv only, no shell)
  - [x] `ipc.py` — unix socket control server + client
  - [x] `scheduler.py` — daemon engine (injectable clock/tz/location/omarchy)
  - [x] `cli.py` — `omarchy-auto-theme` command
- [x] `bin/omarchy-auto-theme`, `bin/dusk-scheduler` launchers
- [x] `systemd/dusk.service.tpl` user unit
- [x] Root-level Quickshell bar-widget plugin (manifest, Service, Panel, Icon)
- [x] `install.sh` installer
- [x] `tests/` unittest suite (injected clock/timezone/location, fake omarchy)
- [x] Install into real environment, validate plugin schema, enable service

## Design decisions

- **Language**: Python 3 stdlib only (available at `/usr/bin/python3` for systemd;
  `python3` via mise for the CLI). No network in transition path.
- **Config**: `~/.config/omarchy/dusk/config.json` (documented, distinct filename).
- **State**: `~/.local/state/omarchy/dusk/state.json` (Omarchy-owned dir, dusk-owned
  file; never write Omarchy's own `current/`).
- **Control**: unix socket `$XDG_RUNTIME_DIR/dusk/control.sock`. CLI writes config
  atomically then asks the daemon to `reload`; `status` queries the daemon.
- **Transitions**: chronological daily events. Scheduled: `light@HH:MM`,
  `dark@HH:MM` each day (midnight-crossing handled by ordering). Solar: sunrise→light,
  sunset→dark; polar day/night → fixed default kind; no data → scheduled fallback
  with visible reason.
- **Apply**: compare desired slug to `~/.local/state/omarchy/current/theme.name`;
  no-op if equal; else `omarchy theme set <slug>` (argv list, wait for completion).
  Retry with backoff on failure; keep last successful state.
- **Wait**: single next-transition wait, capped at 24 h daily recompute (catches
  sleep/resume + clock jumps); no polling.

## Verification

- `python3 -m unittest discover -s tests -v` (scheduler logic, independent of desktop)
- `ruff check` on Python sources
- `omarchy plugin validate .`
- Manual: install, `omarchy-auto-theme status`, enable service, observe a transition

## Review

All steps verified:

- **Tests**: `/usr/bin/python3 -m unittest discover` — 72 tests, OK. Suite covers solar
  accuracy (validated against astral/sunrise-sunset.org), scheduled midnight-crossing,
  polar day/night, invalid-location fallback, config validation, atomic state, scheduler
  retry/no-op/transition-wait logic, IPC server/client, and CLI end-to-end with a fake
  omarchy.
- **Lint**: `ruff check dusk/ bin/ tests/` — all checks passed.
- **Plugin schema**: `omarchy plugin validate .` — rc 0.
- **Sandbox E2E**: fake `omarchy` CLI; verified startup apply, no-op when already active,
  `manual dark`→apply, `solar`/`scheduled`/`offsets` reload via socket, weather-coordinate
  solar path (sunset 20:21 BST for Poole on 2026-08-19), machine-readable `status --json`.
- **Real install**: `install.sh` → `~/.local/lib/dusk`, symlinks in `~/.local/bin`,
  `dusk.service` enabled + running (`graphical-session.target`). Real transition exercised:
  `manual dark` applied `catppuccin` (light→dark) via `omarchy theme set`, `solar` returned
  to `catppuccin-latte`; current `status` shows solar mode, next transition dark at 20:21.

### Known fixes along the way

- `_resolve_solar()` added in `schedule.py`; solar branch now validates coordinates and
  uses `_resolve_solar`; removed dead `_solar_events()`.
- `compute_wait()` in `scheduler.py` only shortens the wait by the retry interval when
  `failuresSinceSuccess > 0`.
- `ipc.py` `poll()` returns after the first ready event round so a `reload` reaches the
  recompute loop promptly instead of waiting out the transition sleep.
- Launchers use `os.path.realpath(__file__)` so the symlinked `~/.local/bin` commands
  resolve the installed package dir.

### Left to the user (optional)

- Enable the bar widget: `omarchy plugin enable dusk right` (files already at
  `~/.config/omarchy/plugins/dusk`).

## Refinement Review

- `python3 -m unittest discover -s tests -v` — 75 tests passed.
- `ruff check dusk bin tests` — passed.
- `omarchy plugin validate .` — passed.
- `bash -n install.sh` and `git diff --check` — passed.
- Panel polish: `omarchy plugin validate .`, `ruff check dusk bin tests`,
  and the 75-test suite passed.
