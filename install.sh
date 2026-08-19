#!/usr/bin/env bash
# Install Dusk — automatic Omarchy theme switching.
#
# Copies the scheduler into ~/.local/lib/dusk, symlinks the CLI and daemon into
# ~/.local/bin, installs the systemd user unit for the graphical session, and
# copies the optional Quickshell bar widget into ~/.config/omarchy/plugins/dusk.
#
# Usage: ./install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUSK_HOME="${DUSK_HOME:-$HOME/.local/lib/dusk}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${UNIT_DIR:-$HOME/.config/systemd/user}"
PLUGIN_DIR="${PLUGIN_DIR:-$HOME/.config/omarchy/plugins/dusk}"

# A python3 interpreter that always exists for the systemd unit (the CLI uses
# `env python3` from the user's PATH instead).
if [[ -x /usr/bin/python3 ]]; then
  PYTHON=/usr/bin/python3
else
  PYTHON="$(command -v python3)"
fi
[[ -n $PYTHON ]] || { echo "python3 not found on PATH" >&2; exit 1; }

echo "== Dusk installer =="
echo "  install dir:  $DUSK_HOME"
echo "  interpreter:  $PYTHON"

mkdir -p "$DUSK_HOME" "$BIN_DIR" "$UNIT_DIR"
cp -a "$SCRIPT_DIR/dusk" "$DUSK_HOME/"
cp -a "$SCRIPT_DIR/bin" "$DUSK_HOME/"
cp -a "$SCRIPT_DIR/docs" "$DUSK_HOME/"

chmod +x "$DUSK_HOME/bin/omarchy-auto-theme" "$DUSK_HOME/bin/dusk-scheduler"
ln -sf "$DUSK_HOME/bin/omarchy-auto-theme" "$BIN_DIR/omarchy-auto-theme"
ln -sf "$DUSK_HOME/bin/dusk-scheduler" "$BIN_DIR/dusk-scheduler"
echo "  commands:     $BIN_DIR/omarchy-auto-theme, $BIN_DIR/dusk-scheduler"

sed -e "s|__DUSK_HOME__|$DUSK_HOME|g" -e "s|__PYTHON__|$PYTHON|g" \
  "$SCRIPT_DIR/systemd/dusk.service.tpl" > "$UNIT_DIR/dusk.service"
echo "  service:      $UNIT_DIR/dusk.service"

mkdir -p "$PLUGIN_DIR"
cp -a "$SCRIPT_DIR/shell/dusk/." "$PLUGIN_DIR/"
echo "  widget:       $PLUGIN_DIR updated (enable with: omarchy plugin enable dusk right)"

systemctl --user daemon-reload
systemctl --user enable dusk.service
systemctl --user start dusk.service
echo
echo "Dusk installed. Configure with:"
echo "  omarchy-auto-theme themes --light <slug> --dark <slug>"
echo "  omarchy-auto-theme solar | scheduled --light 07:00 --dark 19:00 | manual light"
echo "  omarchy-auto-theme status"
echo "The scheduler starts with your graphical session and survives shell restarts."
