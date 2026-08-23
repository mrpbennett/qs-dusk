# Dusk — Usage

Dusk switches your whole Omarchy desktop between two themes automatically, using
`omarchy theme set` as the only mechanism. Nothing else touches application
configs, backgrounds, or hooks.

## Requirements

- Omarchy 4.x on Hyprland, graphical user session.
- `python3` (stdlib only — no pip packages needed) and `systemd --user`.

## Install

Dusk is a standard Omarchy shell plugin. Install it with Omarchy's plugin
manager — no scripts to clone or run:

```sh
omarchy plugin add https://github.com/mrpbennett/qs-dusk.git --enable
```

This clones Dusk into `~/.config/omarchy/plugins/mrpbennett.dusk`, validates
its manifest, and enables the bar widget. The first time the widget loads it
symlinks the `omarchy-auto-theme` and `dusk-scheduler` commands into
`~/.local/bin`, writes the `dusk.service` user unit (running the scheduler
straight from the plugin folder), and starts the daemon for the graphical
session. Everything runs from the plugin folder, so `omarchy plugin update`
keeps the extension current.

The widget shows the current appearance with an icon and lets you switch Light /
Dark / Automatic from the bar. Automatic normally uses sunrise and sunset from
your Omarchy weather location. Existing fixed schedules remain available through
the CLI and are preserved when Automatic is selected in the panel.

### Keybindings (optional)

If you prefer the keyboard over the bar, add these to
`~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + SHIFT + ALT + Z", "Dusk: Auto mode", "omarchy-auto-theme solar")
o.bind("SUPER + SHIFT + ALT + L", "Dusk: Light mode", "omarchy-auto-theme manual light")
o.bind("SUPER + SHIFT + ALT + D", "Dusk: Dark mode", "omarchy-auto-theme manual dark")
```

`SUPER + SHIFT + ALT + Z` avoids conflicts with stock Omarchy bindings.

## Configure

First pick your theme pair. Use slugs as shown by `omarchy theme list`
(lowercase, dashes):

```sh
omarchy-auto-theme themes --light catppuccin-latte --dark catppuccin
```

Then choose a mode:

```sh
omarchy-auto-theme solar                          # sunrise/sunset from Omarchy weather
omarchy-auto-theme scheduled --light 07:00 --dark 19:00
omarchy-auto-theme manual light                   # apply once, stop automatic switching
```

`manual` reports when the requested theme is already active instead of running
`omarchy theme set` again; if the scheduler daemon is not running, the command
still applies the theme itself so manual mode works standalone.

Adjust solar timing and fallback:

```sh
omarchy-auto-theme offsets --sunrise 0 --sunset 0   # signed minutes; negative = earlier
```

Solar mode uses the coordinates Omarchy already stores in
`~/.local/state/omarchy/settings/weather.json`. If they are missing or invalid,
dusk uses the configured scheduled fallback times and says so in status.

## Status

```sh
omarchy-auto-theme status          # human readable
omarchy-auto-theme status --json   # machine readable
```

Example:

```
Theme: Catppuccin Latte
Mode: Solar
Next transition: Dark at 20:22
Theme pair: Catppuccin Latte / Catppuccin
Location: Omarchy weather coordinates
```

Error and fallback conditions always show up in status (e.g. `Fallback:
weather coordinates unavailable — using 07:00/19:00`).

`status --json` emits the scheduler's full state record (the same document
stored in `state.json`) plus the live theme pair, so scripts and widgets can
consume one stable schema whether or not the daemon is running.

## Service

```sh
systemctl --user status dusk
systemctl --user restart dusk
journalctl --user -u dusk -f
```

The scheduler begins with the graphical session, survives shell restarts, and
recomputes after resume, clock/timezone changes, and config changes. It does not
poll; it sleeps until the next transition and recalculates on wake.

## Files

- Config: `~/.config/omarchy/dusk/config.json`
- Runtime state: `~/.local/state/omarchy/dusk/state.json`
- Control socket: `$XDG_RUNTIME_DIR/dusk/control.sock`

## Safety notes

- Stock themes and Omarchy-managed state are never modified; overlays live in
  `~/.config/omarchy/themes/<slug>/` and are selected normally.
- Dusk never force-kills applications. Omarchy's reload/restart path plus your
  existing `theme-set` hooks handle that.
- If a `omarchy theme set` fails, dusk keeps the last good theme, reports the
  error, and retries — state is never corrupted.
