# Dusk — Domain & Architecture Vocabulary

Shared language for the codebase. Use these terms exactly when discussing
design; deeper architecture vocabulary (module, interface, depth, seam,
adapter, locality) follows the codebase-design glossary.

## Domain terms

- **Appearance** — the desktop-wide light/dark look. Dusk switches it by
  invoking `omarchy theme set`; it never changes themes any other way.
- **Kind** — `light` or `dark`. The two appearance targets.
- **Mode** — how the desired kind is chosen: `solar` (sunrise/sunset at the
  configured **Location**), `scheduled` (fixed daily times), or `manual`
  (one selected kind, no transitions).
- **Event / Transition** — a `(local datetime, kind)` pair. Daily events are
  built for yesterday/today/tomorrow; the active kind is the latest event at
  or before *now*, the next transition is the earliest after it. A manual
  mode has no events.
- **Decision** — the pure result of resolving mode, config, time, zone, and
  location into a desired theme/kind and the next transition
  (`dusk/schedule.py`). Producing it has no side effects.
- **Apply engine** — turns a desired theme slug into a recorded outcome:
  observe Omarchy, reset the retry budget per target, detect no-ops, apply,
  record. One shared implementation (`dusk/engine.py`) behind both the
  Daemon's Tick and the CLI's standalone manual path; the only side effect is
  the `omarchy theme set` call through the Omarchy adapter.
- **Config** — user preferences at `~/.config/omarchy/dusk/config.json`.
- **State** — runtime record of what was applied/attempted at
  `~/.local/state/omarchy/dusk/state.json` (distinct from Omarchy's own
  `current/theme.name`, which dusk only observes). Owned by `dusk/state.py`
  as an immutable **DuskState** record: the schema, its camelCase wire
  format, and every mutation rule (`synced_from`, `observe_current`,
  `reset_retry_budget`, `mark_no_op`, `record_apply`) live behind that one
  interface; callers never touch fields by name.
- **Daemon** — `dusk-scheduler`, the `systemd --user` service that owns every
  apply and all retry behavior.
- **Control socket** — `$XDG_RUNTIME_DIR/dusk/control.sock`; line-delimited
  JSON (`status`, `reload`). The CLI and bar widget write intent through it;
  they never invoke `omarchy theme set` themselves. A successful `reload`
  response means a fresh Tick has completed and State has been persisted.
- **Status document** — the consumer-facing projection of State, the Config
  that produced it, and Daemon liveness. With the Daemon down it uses current
  Config but never presents a stale automatic Decision as current.
- **Theme catalog** — one coherent observation of Omarchy's installed themes
  for an operation: normalized slugs, display names, availability, and whether
  discovery succeeded. Failed discovery never masquerades as confirmed absence.
- **Installation** — the idempotent setup of Dusk's executable links, Daemon
  unit, and optional bar widget files. A successful check means the installed
  paths still point at the current Dusk source.

## Architecture terms

- **Tick** — one step of the engine (`Scheduler.tick`): sample time once, load
  config once, resolve the Decision, sync state, apply if healthy, persist, and
  return the seconds until the next wake together with the persistence outcome.
  Retry/backoff policy lives entirely here.
- **Pump** — `Scheduler.run`: wires wakes (socket requests, signal pipe,
  timeout) into ticks; owns no policy. A `reload` handler completes a fresh
  Tick before replying; observational requests preserve the current transition
  deadline, while timeout and signal wakes cause a fresh Tick.
- **Transition engine** — the tick implementation as a whole: the deep
  module behind which decision resolution, application, retries, state sync,
  and wait computation are hidden. Testable through `tick()` with an
  injected clock, timezone, location provider, and omarchy adapter.
- **Omarchy adapter** — `dusk/omarchy.py`, the only module that shells out to
  the `omarchy` binary or reads Omarchy-owned files.
- **Wake** — anything that ends a wait early: a control-socket request, the
  signal pipe (`SIGTERM`/`SIGINT` stop; `SIGUSR1` reload), or the daily cap.
