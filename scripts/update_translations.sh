#!/usr/bin/env bash
# Regenerate the Qt translation files (.ts) and compiled catalogs (.qm).
#
# The .ts files are the translator's workbench (edit them by hand or with
# Qt Linguist: pyside6-linguist). The .qm files ship inside the Python
# package (see pyproject.toml package-data) and are loaded at startup by
# todo_snake.i18n.
#
# Usage:
#   ./scripts/update_translations.sh [lang ...]
#   ./scripts/update_translations.sh         # refresh all known languages
#   ./scripts/update_translations.sh de      # refresh just German

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
I18N_DIR="$REPO_DIR/src/todo_snake/resources/i18n"
SRC_DIR="$REPO_DIR/src"

# Prefer the project venv binaries, fall back to whatever is on PATH.
LUPDATE="$(command -v "$REPO_DIR/.venv/bin/pyside6-lupdate" || command -v pyside6-lupdate)"
LRELEASE="$(command -v "$REPO_DIR/.venv/bin/pyside6-lrelease" || command -v pyside6-lrelease)"
if [ -z "$LUPDATE" ] || [ -z "$LRELEASE" ]; then
    echo "pyside6-lupdate / pyside6-lrelease not found" >&2
    echo "Install PySide6 (e.g. .venv/bin/pip install -e '.[dev]')" >&2
    exit 1
fi

LANGS=("${@}")
if [ ${#LANGS[@]} -eq 0 ]; then
    LANGS=()
    for ts in "$I18N_DIR"/todo_snake_*.ts; do
        [ -e "$ts" ] || continue
        lang="$(basename "$ts" .ts)"
        LANGS+=("${lang#todo_snake_}")
    done
fi

for lang in "${LANGS[@]}"; do
    echo "== $lang =="
    "$LUPDATE" -extensions py "$SRC_DIR" \
        -ts "$I18N_DIR/todo_snake_$lang.ts"
    "$LRELEASE" "$I18N_DIR/todo_snake_$lang.ts"
done