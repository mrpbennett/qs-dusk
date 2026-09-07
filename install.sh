#!/usr/bin/env bash
# Install Dusk - automatic Omarchy theme switching.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUSK_SOURCE_DIR="$SCRIPT_DIR"
DUSK_HOME="${DUSK_HOME:-$HOME/.local/lib/dusk}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
UNIT_DIR="${UNIT_DIR:-$HOME/.config/systemd/user}"
PLUGIN_DIR="${PLUGIN_DIR:-$HOME/.config/omarchy/plugins/mrpbennett.dusk}"
export DUSK_SOURCE_DIR DUSK_HOME BIN_DIR UNIT_DIR PLUGIN_DIR

"$SCRIPT_DIR/bin/dusk-install" "$@"

[[ ${1:-} == --check ]] && exit

echo "Dusk installed."
echo "  commands: $BIN_DIR/omarchy-auto-theme, $BIN_DIR/dusk-scheduler"
echo "  service:  $UNIT_DIR/dusk.service"
echo "  widget:   $PLUGIN_DIR"
