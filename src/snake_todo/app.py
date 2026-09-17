"""Composition root: wire storage, service and UI together.

This is the only place that knows about concrete implementations. The
storage backend can be selected per environment, e.g.::

    SNAKE_TODO_BACKEND=postgres python -m snake_todo

Once a PostgreSQL backend exists in ``persistence.factory``.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from snake_todo.config import (
    APP_DISPLAY_NAME,
    APP_NAME,
    APP_VERSION,
    ORG_NAME,
    default_db_path,
)
from snake_todo.persistence import create_repository
from snake_todo.service import TodoService
from snake_todo.ui.icons import create_todo_icon
from snake_todo.ui.main_window import MainWindow
from snake_todo.ui.tray import TrayIcon

_DEFAULT_BACKEND = "sqlite"


def build_application(argv: list[str] | None = None):
    """Create the fully wired Qt application (for tests and the real entry)."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(create_todo_icon())
    # The window hides to the tray instead of quitting on close.
    app.setQuitOnLastWindowClosed(False)

    backend = os.environ.get("SNAKE_TODO_BACKEND", _DEFAULT_BACKEND)
    db_path = default_db_path()
    repository = create_repository(backend, db_path)
    service = TodoService(repository)

    window = MainWindow(service, tray_enabled=True)
    tray = TrayIcon(window)
    window.show()
    return app, window, tray


def main(argv: list[str] | None = None) -> int:
    app, window, tray = build_application(argv)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())