"""Composition root: wire storage, service and UI together.

This is the only place that knows about concrete implementations. The
storage backend can be selected per environment, e.g.::

    SNAKE_TODO_BACKEND=postgres python -m snake_todo

Once a PostgreSQL backend exists in ``persistence.factory``.

Exactly one process may own the app: ``build_application`` enforces a
single-instance guard (local unix socket). A second launch does not open
another window or touch the database — it signals the running instance to
raise its window and exits.
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
from snake_todo.single_instance import SingleInstanceGuard
from snake_todo.ui.icons import create_todo_icon
from snake_todo.ui.main_window import MainWindow
from snake_todo.ui.tray import TrayIcon

_DEFAULT_BACKEND = "sqlite"


def build_application(
    argv: list[str] | None = None,
    *,
    single_instance: bool = True,
):
    """Create the fully wired Qt application (for tests and the real entry).

    Returns ``(app, guard, window, tray, primary)``. When ``single_instance``
    is on and another process already owns the app, ``primary`` is ``False``
    and ``window``/``tray`` are ``None``. Callers must keep ``guard`` alive
    for the whole app lifetime — it owns the lock that prevents duplicate
    instances.
    """
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(create_todo_icon())
    # The window hides to the tray instead of quitting on close.
    app.setQuitOnLastWindowClosed(False)

    guard = None
    backend = os.environ.get("SNAKE_TODO_BACKEND", _DEFAULT_BACKEND)
    db_path = default_db_path()
    if single_instance:
        lock_path = db_path.parent / f"{APP_NAME}.lock"
        guard = SingleInstanceGuard(lock_path, socket_name=f"{APP_NAME}-{os.getuid()}", parent=app)
        if not guard.start():
            return app, guard, None, None, False
        # Keep the guard (and with it the lock) alive for the app's lifetime,
        # even if a caller drops the returned reference.
        app._snake_todo_guard = guard

    repository = create_repository(backend, db_path)
    service = TodoService(repository)

    window = MainWindow(service, tray_enabled=True)
    tray = TrayIcon(window)
    if guard is not None:
        guard.show_requested.connect(window.show_window)
    window.show()
    return app, guard, window, tray, True


def main(argv: list[str] | None = None) -> int:
    app, guard, window, tray, primary = build_application(argv)
    if not primary:
        return 0
    # ``guard`` stays referenced here, keeping the instance lock held for the
    # entire event-loop lifetime.
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())