"""Application configuration: metadata and paths."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "todo-snake"
APP_DISPLAY_NAME = "Todo Snake"
APP_VERSION = "0.3.0"
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


def default_log_path() -> Path:
    """Return the default sync log file location (next to the database)."""
    return default_db_path().parent / "sync.log"


_true_strings = frozenset({"1", "true", "yes", "on"})


def parse_bool(value: object, default: bool = False) -> bool:
    """Parse a value read back from ``QSettings`` into a bool.

    ``QSettings`` writes booleans to its ini file as the strings ``true``/``false``.
    Within one process it returns them as typed booleans (via its in-memory
    cache), but on a cold read — i.e. after an app restart — they come back as
    plain strings. ``bool("false")`` is ``True``, so a naive cast silently flips
    every disabled flag back on. Parse explicitly instead.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return default
    return str(value).strip().lower() in _true_strings
