# Dusk

Automatic Omarchy theme switching — solar or scheduled — through the native
`omarchy theme set` path. A user-level scheduler plus optional bar widget.

- [Design](docs/design.md)
- [Usage](docs/usage.md)

```
~/.config/omarchy/dusk/config.json        preferences
~/.local/state/omarchy/dusk/state.json    runtime state
omarchy-auto-theme status | solar | scheduled | manual | themes | offsets | reload
dusk.service (systemd --user)             scheduler daemon
dusk (bar widget plugin)                  optional visual control
```

The scheduler decides *when* and *which* theme. Omarchy keeps deciding *how*
every desktop component changes (shell, background, app reloads, `theme-set`
hooks).

Install with `./install.sh`, configure with `omarchy-auto-theme`, and enable the
widget with `omarchy plugin enable dusk right`.
