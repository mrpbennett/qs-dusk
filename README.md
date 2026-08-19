# Dusk

![dusk](./assets/dusk.png)

Automatically switch your complete Omarchy desktop between light and dark
themes. Dusk follows sunrise and sunset when location data is available, falls
back to a schedule when it is not, and always applies changes through Omarchy's
native `omarchy theme set` path.

## Why Dusk

- Changes the whole desktop, not just a wallpaper or color scheme.
- Uses solar time from Omarchy's existing weather location, with configurable
  scheduled fallback times.
- Runs independently as a `systemd --user` service, so switching continues
  while the shell is restarted.
- Includes an optional bar widget for switching between Automatic, Light, and
  Dark modes without opening a terminal.
- Leaves Omarchy's themes, current-state files, and application configuration
  under Omarchy's ownership.

## Quick Start

```sh
./install.sh

# Choose the themes to use. List available slugs with: omarchy theme list
omarchy-auto-theme themes --light catppuccin-latte --dark catppuccin

# Follow your Omarchy weather location's sunrise and sunset.
omarchy-auto-theme solar
```

Enable the optional bar control in the section you prefer:

```sh
omarchy plugin enable mrpbennett.dusk right
```

## Choose a Mode

```sh
# Automatic, driven by sunrise and sunset.
omarchy-auto-theme solar

# Automatic, driven by local wall-clock times.
omarchy-auto-theme scheduled --light 07:00 --dark 19:00

# Apply one appearance and pause automatic switching.
omarchy-auto-theme manual light
omarchy-auto-theme manual dark
```

Use `omarchy-auto-theme status` to see the selected mode, current theme, next
transition, and any solar fallback reason.

## How It Works

1. The CLI saves your theme pair and scheduling preferences to Dusk's config.
2. The `dusk.service` scheduler determines the desired appearance from the
   selected mode: sunrise/sunset, fixed local times, or a manual choice.
3. Before changing anything, it compares the desired theme with Omarchy's
   current theme state, avoiding unnecessary theme applications.
4. When a change is needed, it runs `omarchy theme set <slug>`. Omarchy then
   applies the theme to the shell, background, supported applications, and any
   `theme-set` hooks you already use.
5. The bar widget and `status` command read scheduler state through Dusk's local
   control socket. The widget never applies a theme itself.

Solar mode reads the coordinates already stored by Omarchy's weather widget. If
they are unavailable or invalid, Dusk uses the configured scheduled fallback and
reports that fact in `status` instead of silently guessing.

The scheduler reads only the state it needs and stores its own data separately:

| Path | Purpose |
| --- | --- |
| `~/.config/omarchy/dusk/config.json` | Preferences and schedule |
| `~/.local/state/omarchy/dusk/state.json` | Scheduler status and last successful change |
| `$XDG_RUNTIME_DIR/dusk/control.sock` | CLI and widget control channel |

## Documentation

- [Usage guide](docs/usage.md): requirements, installation, configuration, and service commands.
- [Design](docs/design.md): scheduling model, solar calculation, state, and failure handling.
