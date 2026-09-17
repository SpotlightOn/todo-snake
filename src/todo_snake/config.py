"""Application configuration: metadata and paths."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "todo-snake"
APP_DISPLAY_NAME = "Todo Snake"
APP_VERSION = "0.1.0"
ORG_NAME = "TodoSnake"

_ORG_DIR = "TodoSnake"


def default_db_path() -> Path:
    """Return the default SQLite database location.

    Overridable via the ``TODO_SNAKE_DB`` environment variable. Follows the
    XDG base directory spec on Linux, with a sensible fallback elsewhere.
    """
    override = os.environ.get("TODO_SNAKE_DB")
    if override:
        return Path(override).expanduser()

    base = os.environ.get("XDG_DATA_HOME")
    data_home = Path(base) if base else Path.home() / ".local" / "share"
    return data_home / _ORG_DIR / APP_NAME / "todos.db"