#!/usr/bin/env bash
# Install snake-todo and register it with the desktop environment.
#
# The installation follows the XDG Base Directory specification for
# user-level applications (no root required):
#
#   .desktop file  ->  $XDG_DATA_HOME/applications/   (default: ~/.local/share/applications)
#   icon           ->  $XDG_DATA_HOME/icons/hicolor/  (default: ~/.local/share/icons)
#   venv           ->  $XDG_DATA_HOME/snake-todo/venv (default: ~/.local/share/snake-todo/venv)
#
# Usage:
#   ./install.sh            XDG user-level install into a dedicated venv (recommended)
#   ./install.sh --src-venv install into a virtualenv at .venv/ in the repo
#   ./install.sh --system   system-wide install (requires root)
#   ./uninstall.sh          remove the XDG user-level installation

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_TEMPLATE="$REPO_DIR/todo-snake.desktop"
ICON_SVG="$REPO_DIR/src/snake_todo/resources/icons/todo.svg"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$XDG_DATA_HOME/applications"
ICON_DIR="$XDG_DATA_HOME/icons/hicolor/scalable/apps"
APP_ID="snake-todo"

register_desktop_resources() {
    local exec="$1"
    local icons_root="$2"
    local desktop_dir="$3"

    mkdir -p "$desktop_dir" "$icons_root/hicolor/scalable/apps"
    # Substitute the actual executable path into the desktop template.
    sed "s|^Exec=.*|Exec=$exec|" "$DESKTOP_TEMPLATE" > "$desktop_dir/$APP_ID.desktop"
    chmod +x "$desktop_dir/$APP_ID.desktop"
    cp "$ICON_SVG" "$icons_root/hicolor/scalable/apps/$APP_ID.svg"
    echo "  desktop entry: $desktop_dir/$APP_ID.desktop"
    echo "  icon: $icons_root/hicolor/scalable/apps/$APP_ID.svg"

    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q "$desktop_dir" 2>/dev/null || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q "$icons_root" 2>/dev/null || true
    fi
}

run_install_xdg() {
    local venv_dir="${XDG_DATA_HOME:-$HOME/.local/share}/snake-todo/venv"
    echo "Creating virtualenv at $venv_dir ..."
    python3 -m venv "$venv_dir"
    "$venv_dir/bin/pip" install --upgrade pip
    "$venv_dir/bin/pip" install --upgrade "$REPO_DIR"

    register_desktop_resources "$venv_dir/bin/snake-todo" "$XDG_DATA_HOME/icons" "$APP_DIR"
    echo ""
    echo "Done. Launch via the application menu, or run:"
    echo "  $venv_dir/bin/snake-todo"
    echo ""
    echo "Optional: add the venv to your PATH with:"
    echo "  export PATH=\"$venv_dir/bin:\$PATH\""
}

run_install_src_venv() {
    local venv_dir="${1:-$REPO_DIR/.venv}"
    echo "Creating virtualenv at $venv_dir ..."
    python3 -m venv "$venv_dir"
    "$venv_dir/bin/pip" install --upgrade pip
    "$venv_dir/bin/pip" install --upgrade "$REPO_DIR"

    register_desktop_resources "$venv_dir/bin/snake-todo" "$XDG_DATA_HOME/icons" "$APP_DIR"
    echo ""
    echo "Done. Run with: $venv_dir/bin/snake-todo"
}

run_install_system() {
    echo "Installing snake-todo system-wide..."
    pip install --upgrade "$REPO_DIR"

    register_desktop_resources "$(command -v snake-todo)" /usr/share/icons /usr/share/applications
    echo ""
    echo "Done. snake-todo is available as: snake-todo"
}

case "${1:-}" in
    "" | "--xdg")  run_install_xdg ;;
    "--src-venv")  run_install_src_venv "${2:-$REPO_DIR/.venv}" ;;
    "--system")    run_install_system ;;
    "-h" | "--help")
        grep '^#!' "$0" >/dev/null 2>&1 || true
        sed -n '/^# /p' "$0"
        ;;
    *)
        echo "Unknown option: $1" >&2
        echo "Usage: $0 [--xdg|--src-venv|--system]" >&2
        exit 1
        ;;
esac