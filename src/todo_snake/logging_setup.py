"""Application logging: a rotating sync log file.

Sync problems are hard to diagnose without a trace of what was requested and
which status came back, so we write a rotating log next to the database.
Credentials never appear here: they are sent as an ``Authorization`` header and
the URLs we log do not contain secrets.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from todo_snake.config import default_log_path

LOGGER_NAME = "todo_snake.sync"
_MAX_BYTES = 1_000_000
_BACKUPS = 2

_configured = False


def get_sync_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def configure_logging() -> None:
    """Install the rotating file handler once (idempotent, safe to call twice)."""
    global _configured
    logger = get_sync_logger()
    if _configured:
        return
    logger.setLevel(logging.INFO)
    path = default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    _configured = True
