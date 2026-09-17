#!/usr/bin/env bash
# Remove the XDG user-level installation of todo-snake:
#   desktop entry, icon and venv (default XDG install location).

set -euo pipefail

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_ID="todo-snake"

rm -f "$XDG_DATA_HOME/applications/$APP_ID.desktop"
rm -f "$XDG_DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -rf "$XDG_DATA_HOME/$APP_ID/venv"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q "$XDG_DATA_HOME/applications" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q "$XDG_DATA_HOME/icons" 2>/dev/null || true
fi

echo "Removed todo-snake XDG installation (desktop entry, icon, venv)."