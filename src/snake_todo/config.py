"""Application configuration: metadata and paths."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "snake-todo"
APP_DISPLAY_NAME = "Snake Todo"
APP_VERSION = "0.1.0"
ORG_NAME = "SnakeTodo"

_ORG_DIR = "SnakeTodo"


def default_db_path() -> Path:
    """Return the default SQLite database location.

    Overridable via the ``SNAKE_TODO_DB`` environment variable. Follows the
    XDG base directory spec on Linux, with a sensible fallback elsewhere.
    """
    override = os.environ.get("SNAKE_TODO_DB")
    if override:
        return Path(override).expanduser()

    base = os.environ.get("XDG_DATA_HOME")
    data_home = Path(base) if base else Path.home() / ".local" / "share"
    return data_home / _ORG_DIR / APP_NAME / "todos.db"